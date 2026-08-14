"""El sistema servido por HTTP, sin AWS. **El otro punto de entrada.**

    python -m herramientas.servidor --desarrollo --sembrar    # tu maquina
    python -m herramientas.servidor --host 0.0.0.0            # desplegado

Hay dos formas de arrancar este sistema y las dos componen las MISMAS
dependencias y llaman al MISMO `manejar`:

    reservas/entrada.py     -> Lambda, detras de API Gateway   (AWS)
    herramientas/servidor.py-> un proceso HTTP                 (aqui)

Existe por dos razones distintas y conviene no mezclarlas:

  **T7a y CD2** — el repositorio tiene que poder ejecutarse en la maquina de un
  desconocido. Sin esto, ver funcionar el sistema exige una cuenta de nube, y
  pedirle eso a quien revisa el repositorio es pedirle demasiado.

  **El argumento economico de §6.1 del README** — el instrumento es una
  superficie de consumo abierta y anunciada a desconocidos. Con la cuenta de AWS
  en Plan de Pago y cero creditos, dejar esa superficie viva y desatendida alli
  es el riesgo que este proyecto describio como no acotable con codigo. La demo
  publica vive aqui; AWS se usa en ventanas cortas y supervisadas.

**Se llamaba `servidor_local.py` y el nombre dejo de ser cierto** en cuanto paso
a servir la demo publica. Renombrado en vez de dejarlo: un fichero que se llama
"local" y esta desplegado es la clase de texto falso que este proyecto persigue.

------------------------------------------------------------------------------
ESTO NO ES API GATEWAY, Y LA DIFERENCIA IMPORTA
------------------------------------------------------------------------------
Traduce una peticion HTTP al **formato de carga 2.0** y llama a
`api_gateway.manejar`, que es exactamente el camino de la funcion desplegada. De
ahi para adentro **no hay ninguna segunda implementacion**: mismo caso de uso,
mismo traductor, mismos controles.

De ahi para AFUERA si hay diferencias, y se declaran en vez de disimularse:

  - **El emparejado de rutas lo hace este fichero.** En produccion lo hace API
    Gateway a partir de las `RouteKey` de la plantilla. Aqui se calca leyendo
    `atender.RUTAS`, que es la misma tabla que la plantilla tiene que respetar
    (lo vigila `test_infra.py`). Pero es un calco, no el original.
  - **No hay estrangulamiento del borde.** El `ThrottlingRateLimit` de la etapa
    no existe aqui, asi que la mitad del borde de la desigualdad de SEC-1 no se
    ejerce. El contador por identidad si, porque vive en la tabla.
  - **CORS no se ejerce**: pagina y API salen del mismo origen, asi que el
    navegador no pregunta. En produccion manda la `CorsConfiguration` del API.
  - **No hay arranque en frio.** La dispersion de la barrera que mida el
    instrumento contra esto sera mejor que la real.

Lo que se mide aqui vale para C1 —una confirmacion por franja— y **no vale como
medicion de rendimiento** del sistema desplegado.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone

from reservas import config, entrada
from reservas.adaptadores import api_gateway, dynamodb
from reservas.casos_uso.atender import RUTAS
from reservas.nucleo import tiempo

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PAGINA = RAIZ / "frontend" / "index.html"

CUERPO_MAXIMO = 64 * 1024
"""Tope del cuerpo de una peticion. API Gateway trae uno de serie; esto no
traia ninguno. El cuerpo legitimo mas grande de este sistema es una reserva,
que son unos cientos de bytes."""


def casar_ruta(metodo: str, camino: str):
    """Camino concreto -> (plantilla, parametros). Lo que hace API Gateway.

    Se resuelve contra `atender.RUTAS`, que es la misma tabla que la plantilla
    de CloudFormation tiene que declarar. Que las dos no se separen lo vigila
    `test_infra.py`; aqui solo se usa la que ya existe.
    """
    partes_camino = [p for p in camino.strip("/").split("/") if p != ""]
    for metodo_ruta, plantilla in RUTAS:
        if metodo_ruta != metodo:
            continue
        partes = [p for p in plantilla.strip("/").split("/") if p != ""]
        if len(partes) != len(partes_camino):
            continue
        parametros = {}
        for esperada, recibida in zip(partes, partes_camino):
            if esperada.startswith("{") and esperada.endswith("}"):
                parametros[esperada[1:-1]] = urllib.parse.unquote(recibida)
            elif esperada != recibida:
                break
        else:
            return plantilla, parametros
    return None, {}


class Manejador(http.server.BaseHTTPRequestHandler):
    """Traduce HTTP a evento 2.0 y devuelve lo que la funcion responda."""

    protocol_version = "HTTP/1.1"
    dependencias = None  # lo pone `arrancar`
    _local = threading.local()

    def log_message(self, formato, *args):  # menos ruido, mas legible
        sys.stderr.write(f"  {self.command} {self.path} -> {args[1]}\n")

    # -- utilidades --------------------------------------------------------

    def _responder(self, codigo: int, cuerpo: bytes, tipo: str):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _pagina(self):
        if not PAGINA.exists():
            return self._responder(404, b"falta frontend/index.html", "text/plain")
        self._responder(
            200, PAGINA.read_bytes(), "text/html; charset=utf-8"
        )

    def _api(self, metodo: str):
        partes = urllib.parse.urlsplit(self.path)
        plantilla, parametros = casar_ruta(metodo, partes.path)
        if plantilla is None:
            # Igual que API Gateway: lo que no esta declarado no llega a la
            # funcion. Se responde 404 sin invocar nada.
            return self._responder(
                404, b'{"message":"Not Found"}', "application/json"
            )

        longitud = int(self.headers.get("Content-Length") or 0)
        if longitud > CUERPO_MAXIMO:
            # **API Gateway trae un tope de 10 MB de serie; esto no traia
            # ninguno.** Sin el, un desconocido anuncia un cuerpo de un giga y
            # el proceso lo lee entero en memoria antes de que nadie mire si la
            # peticion tiene sentido. El tope es holgado: el cuerpo legitimo mas
            # grande de este sistema es una reserva, que son unos cientos de
            # bytes.
            return self._responder(
                413, b'{"resultado":"peticion-mal-formada"}', "application/json"
            )
        crudo = self.rfile.read(longitud).decode("utf-8") if longitud else None
        consulta = {
            k: v[0] for k, v in urllib.parse.parse_qs(partes.query).items()
        }

        evento = {
            "version": "2.0",
            "routeKey": f"{metodo} {plantilla}",
            "rawPath": partes.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "queryStringParameters": consulta or None,
            "pathParameters": parametros or None,
            "requestContext": {
                "http": {
                    "method": metodo,
                    "path": partes.path,
                    # El origen para la cuota del dispensador. En produccion lo
                    # pone el borde y el cliente no lo elige; aqui es la IP del
                    # socket, que es lo mas parecido que hay.
                    "sourceIp": self.client_address[0],
                }
            },
            "body": crudo,
            "isBase64Encoded": False,
        }

        salida = api_gateway.manejar(
            evento, self.dependencias, api_gateway.ahora_local()
        )
        cuerpo = (salida.get("body") or "").encode("utf-8")
        self.send_response(salida["statusCode"])
        for nombre, valor in (salida.get("headers") or {}).items():
            self.send_header(nombre, valor)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    # -- verbos ------------------------------------------------------------

    def do_GET(self):
        camino = urllib.parse.urlsplit(self.path).path
        if camino in ("/", "/index.html"):
            return self._pagina()
        if camino == "/salud":
            # Para la sonda del alojamiento. **No toca el motor a proposito:**
            # una sonda que leyera la tabla cada pocos segundos convertiria la
            # vigilancia en consumo, que es justo lo que aqui se esta evitando.
            return self._responder(200, b'{"estado":"vivo"}', "application/json")
        self._api("GET")

    def do_POST(self):
        self._api("POST")

    def do_OPTIONS(self):
        """Lo contesta API Gateway en produccion, a partir de su
        `CorsConfiguration`. Aqui se contesta para que el navegador no se
        atasque, y **no prueba nada sobre la configuracion real**."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type,authorization")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()


class Servidor(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    request_queue_size = 128
    """La cola de escucha del socket. **El defecto son 5, y con 5 esto no sirve
    para lo que existe.**

    Se descubrio ejecutandolo, no leyendolo: el instrumento lanza 50 conexiones
    a la vez y el sistema operativo rechazaba dos o tres antes de que el
    servidor llegara a aceptarlas. El instrumento las clasificaba como `otro` y
    las descontaba de las competidoras efectivas —**se comporto bien**, no
    conto como competidora algo de lo que no constaba que hubiera competido—
    pero la medicion quedaba con 48 de 50 por un limite del andamio, no del
    sistema medido.

    Es la clase de defecto que ninguna prueba iba a encontrar, porque las
    pruebas llaman a `atender` en proceso y nunca abren un socket."""


def esperar_motor(cliente, segundos: float = 60.0) -> None:
    """Espera a que el motor responda. **Hace falta en un contenedor.**

    El proceso del sustituto y este arrancan a la vez, y el primero es una JVM:
    tarda mas. Sin esta espera el servidor muere al arrancar con un error de
    conexion, el alojamiento lo reinicia, y vuelve a pasar — un bucle de
    reinicios cuya causa no se parece en nada a su sintoma.
    """
    limite = time.monotonic() + segundos
    ultimo = None
    while time.monotonic() < limite:
        try:
            cliente.list_tables(Limit=1)
            return
        except Exception as error:  # noqa: BLE001 - se reintenta a proposito
            ultimo = error
            time.sleep(1.0)
    raise RuntimeError(f"el motor no respondio en {segundos:.0f} s: {ultimo!r}")


def preparar(endpoint: str, sembrar: bool):
    """Cliente contra el sustituto, tabla creada y datos sembrados."""
    cliente = dynamodb.crear_cliente(endpoint)
    esperar_motor(cliente)
    conjunto = None
    if sembrar:
        from reservas import sembrado

        dynamodb.recrear_tabla(cliente, config.TABLA)
        conjunto = sembrado.sembrar(
            cliente, config.TABLA, tiempo.t0_desde(datetime.now(timezone.utc))
        )
    return cliente, conjunto


def main(argv=None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--puerto", type=int, default=int(os.environ.get("PORT", 8080)))
    analizador.add_argument(
        "--host",
        default="127.0.0.1",
        help="127.0.0.1 por defecto. Un contenedor necesita 0.0.0.0, y hay que "
        "escribirlo: escuchar en todas las interfaces es una decision",
    )
    analizador.add_argument(
        "--endpoint", default=None, help="sustituto local; por defecto config.endpoint()"
    )
    analizador.add_argument("--sembrar", action="store_true")
    analizador.add_argument("--unidades", default=None, help="lista separada por comas")
    analizador.add_argument(
        "--desarrollo",
        action="store_true",
        help="rellena los parametros con valores de demostracion en vez de "
        "exigirlos del entorno. **Solo para tu maquina.**",
    )
    args = analizador.parse_args(argv)

    # **La guarda que hace segura esta herramienta.** Es un servidor de
    # desarrollo: si arrancara apuntando al motor real, cada peticion de quien
    # estuviera probando seria dinero (D-P4-19, D-P4-17).
    if config.motor_real():
        print(
            "RESERVAS_MOTOR_REAL esta puesta. Este servidor es de desarrollo y "
            "no habla con AWS: quitala y vuelve a intentarlo.",
            file=sys.stderr,
        )
        return 1

    endpoint = args.endpoint or config.endpoint()
    cliente, conjunto = preparar(endpoint, args.sembrar)

    if args.unidades:
        activas = args.unidades
    elif conjunto is not None:
        activas = ",".join(conjunto.activas)
    else:
        print(
            "sin --sembrar hay que decir que unidades existen ya: usa --unidades",
            file=sys.stderr,
        )
        return 1

    # -----------------------------------------------------------------------
    # La configuracion sale del ENTORNO, igual que en Lambda. `--desarrollo`
    # solo rellena los huecos que nadie quiere teclear en su maquina.
    #
    # El orden importa y es este a proposito: **lo que el entorno diga manda**.
    # Si fuera al reves, desplegar con una variable mal puesta arrancaria con un
    # valor de demostracion y pareceria configurado.
    # -----------------------------------------------------------------------
    demo = {}
    if args.desarrollo:
        n = len(activas.split(","))
        demo = {
            "RESERVAS_ESPACIOS": "E-SAL,E-BBQ,E-CAN",
            "RESERVAS_VENTANA_SEGUNDOS": "300",
            "RESERVAS_TOPE_POR_IDENTIDAD": "5",
            "RESERVAS_TOPE_POR_ORIGEN": "20",
            "RESERVAS_CAPACIDAD_DEL_BORDE": str(n * 5),
            "RESERVAS_ENFRIAMIENTO_SEGUNDOS": "20",
            "RESERVAS_ORIGEN_PERMITIDO": f"http://localhost:{args.puerto}",
            # Clave nueva en cada arranque: en desarrollo no hay nada que
            # conservar entre reinicios, y una clave fija en el codigo acabaria
            # copiada a un despliegue.
            "RESERVAS_CLAVE_FIRMA": secrets.token_urlsafe(48),
        }
    entorno = {**demo, **{k: v for k, v in os.environ.items() if v}}
    entorno["RESERVAS_UNIDADES_ACTIVAS"] = activas

    try:
        Manejador.dependencias = entrada.dependencias(entorno=entorno, cliente=cliente)
    except entrada.ConfiguracionIncompleta as error:
        print(f"{error}\n", file=sys.stderr)
        print(
            "Si esto es tu maquina y no un despliegue, usa --desarrollo.",
            file=sys.stderr,
        )
        return 1

    n = len(activas.split(","))
    tope = int(entorno["RESERVAS_TOPE_POR_IDENTIDAD"])
    print(f"Sistema escuchando en {args.host}:{args.puerto}")
    print(f"  motor .......... {endpoint}  (sustituto local, NUNCA AWS)")
    print(f"  origen CORS .... {entorno['RESERVAS_ORIGEN_PERMITIDO']}")
    print(f"  identidades .... {n} en conjunto cerrado")
    print(f"  tope ........... {tope} intentos por identidad y ventana "
          f"-> techo {n * tope}")
    print(f"  enfriamiento ... {entorno['RESERVAS_ENFRIAMIENTO_SEGUNDOS']} s entre "
          "ejecuciones del instrumento (D-CE4-1)")
    print()
    print(f"  el instrumento:  python -m herramientas.m2_instrumento "
          f"--url http://localhost:{args.puerto}")
    print(flush=True)

    with Servidor((args.host, args.puerto), Manejador) as servidor:
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nparado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
