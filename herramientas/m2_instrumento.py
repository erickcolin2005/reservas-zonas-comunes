"""M2-INS — el instrumento. Un comando que un extrano ejecuta contra el sistema.

Es el elemento que hace **comprobable por otro** la unica afirmacion del
proyecto: *exactamente una confirmacion por franja, con cincuenta pidiendola a
la vez*. Sin el se incumple CD2 y el veredicto de validacion cae a debil
`[V — vision-producto §5]`. Por eso no se recorta nunca.

    python -m herramientas.m2_instrumento --url https://... --n 50

------------------------------------------------------------------------------
LAS CINCO EXIGENCIAS, Y DONDE ESTA CADA UNA
------------------------------------------------------------------------------
`arquitectura.md` §9 fija cinco. Se listan aqui con su linea, para que quien lea
esto pueda comprobar que estan y no fiarse de que lo digan:

  1. **El lote se pide UNA vez y ANTES del calentamiento.** Una llamada al
     dispensador por ejecucion (D-SEC-5). Pedirlo despues gastaria la cuota por
     origen en mitad de la medicion.                          -> `_pedir_lote`
  2. **Ronda de calentamiento declarada.** El arranque en frio dispersa las
     llegadas y es enemigo de la medicion.                    -> `_calentar`
  3. **Barrera de disparo.** Sin ella el bucle produce una fila, no una tanda:
     es FF1 exacto.                     -> `concurrencia.lanzar_con_barrera`
  4. **Devolver el lote al terminar.** Ver abajo: no se implementa, y se dice
     por que en vez de fingirlo.
  5. **Negarse a mentir.**                              -> `_validez` y RF-14

------------------------------------------------------------------------------
LO QUE ESTE INSTRUMENTO NO PUEDE MEDIR, Y LO DICE
------------------------------------------------------------------------------
**S-2 no existe desde aqui.** El solapamiento de ventanas de escritura se
calcula con instantes que toma el servidor —cuando empieza a evaluar y cuando
intenta escribir— y por HTTP el cliente no los ve. `casos_k.py` si los tiene
porque corre en el mismo proceso que el motor.

Lo que queda es mejor de lo que parece: **S-3, el numero de rechazos RR-11, es
inmune al reloj**. Solo puede existir si una condicion de escritura fallo sobre
una franja que la lectura previa vio libre — es decir, **solo puede existir si
hubo carrera**. No es una estimacion de simultaneidad: es evidencia directa de
ella. Por eso la validez de esta medicion se decide con S-3 y no con S-2.

**Devolucion del lote (exigencia 4): no se implementa, y no es un olvido.** El
dispensador no reserva nada al prestar —`prestar` toma una muestra del conjunto
activo y emite credenciales de 15 minutos— asi que **no hay estado que liberar**.
Un extremo de devolucion seria una ruta que no hace nada, y este proyecto ya
decidio que un metodo que existe y no hace nada se confunde con uno
implementado (`puertos.py`). Los prestamos caducan solos, que es la unica
revocacion que este sistema tiene y ya esta declarada (T-06).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from reservas import concurrencia
from reservas.desenlaces import Cubo, Desenlace, Desglose, Simultaneidad
from reservas.nucleo.modelo import Franja

TIEMPO_LIMITE_S = 30.0


# ---------------------------------------------------------------------------
# El transporte. Se inyecta para que las pruebas corran esto sin desplegar nada.
# ---------------------------------------------------------------------------


class TransporteHttp:
    """Habla HTTP con la biblioteca estandar. **Sin dependencias nuevas.**

    Es deliberado: esto lo ejecuta un desconocido en su maquina, y cada
    dependencia que haya que instalar antes es una razon mas para no ejecutarlo.
    """

    def __init__(self, base: str, tiempo_limite: float = TIEMPO_LIMITE_S):
        self.base = base.rstrip("/")
        self.tiempo_limite = tiempo_limite

    def enviar(self, metodo: str, ruta: str, cuerpo=None, token=None):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode()
        peticion = urllib.request.Request(
            f"{self.base}{ruta}", data=datos, method=metodo
        )
        peticion.add_header("Content-Type", "application/json")
        if token:
            peticion.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(
                peticion, timeout=self.tiempo_limite
            ) as respuesta:
                return respuesta.status, json.loads(respuesta.read() or b"{}")
        except urllib.error.HTTPError as error:
            # Un 401 o un 429 son respuestas, no averias: llevan cuerpo y hay
            # que leerlo. Tratarlos como excepcion perderia justo la
            # informacion que decide si la medicion vale.
            try:
                return error.code, json.loads(error.read() or b"{}")
            except ValueError:
                return error.code, {}


# ---------------------------------------------------------------------------
# El resultado
# ---------------------------------------------------------------------------


@dataclass
class Medicion:
    desglose: Desglose
    simultaneidad: Simultaneidad
    identidades_pedidas: int
    identidades_obtenidas: int
    motivos_invalidez: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    @property
    def valida(self) -> bool:
        return not self.motivos_invalidez

    @property
    def doble_reserva(self) -> bool:
        """**Lo unico que este instrumento existe para poder desmentir.**"""
        return self.desglose.confirmadas > 1


def _desenlace_de(codigo: int, cuerpo: dict, franjas: tuple) -> Desenlace:
    """De respuesta HTTP a desenlace, usando la frontera del 200 al reves.

    El instrumento **no reinterpreta**: lee la etiqueta que el sistema puso.
    Deducir el cubo de otra cosa que no sea lo que el sistema dijo seria el
    instrumento contando su propia version de los hechos.
    """
    etiqueta = str(cuerpo.get("resultado", ""))

    # La etiqueta se resuelve contra el ENUM, no contra una lista de codigos
    # escrita aqui. Enumerarlos a mano tenia un fallo que una prueba encontro:
    # un `SYS-CAPACIDAD` -que viaja con 503- caia en el cajon de "otro" por ser
    # distinto de 200, y con el se perdia un cubo que el proyecto publica con su
    # numero y descuenta de las competidoras efectivas. Derivandolo del enum,
    # **un cubo nuevo se traduce solo**.
    try:
        cubo = Cubo(etiqueta)
    except ValueError:
        cubo = None

    if cubo is None:
        # Un rechazo de negocio no lleva el nombre de su cubo: lleva el de su
        # REGLA (`Desenlace.etiqueta()`), y por eso no esta en el enum.
        if codigo == 200 and cuerpo.get("regla"):
            return Desenlace(
                cubo=Cubo.RECHAZADA_REGLA, regla=cuerpo["regla"], franjas=franjas
            )
        # Lo demas -"enfriamiento", "no-existe", "peticion-mal-formada", o algo
        # que este instrumento no conoce- no es un desenlace del dominio.
        return Desenlace(
            cubo=Cubo.OTRO, franjas=franjas, detalle=f"HTTP {codigo} · {etiqueta}"
        )

    if cubo is Cubo.CONFIRMADA:
        return Desenlace(
            cubo=Cubo.CONFIRMADA, id_reserva=cuerpo.get("reserva"), franjas=franjas
        )
    return Desenlace(cubo=cubo, regla=cuerpo.get("regla"), franjas=franjas)


# ---------------------------------------------------------------------------
# La ejecucion
# ---------------------------------------------------------------------------


def _pedir_lote(transporte, n: int) -> tuple[list, list]:
    """Exigencia 1: una sola llamada, antes de todo lo demas."""
    codigo, cuerpo = transporte.enviar(
        "POST", "/demo/credenciales", {"cantidad": n}
    )
    if codigo != 200:
        motivo = cuerpo.get("resultado", f"HTTP {codigo}")
        if motivo == "enfriamiento":
            return [], [
                "el sistema esta enfriando entre ejecuciones (D-CE4-1). **No es "
                "un fallo**: espera y vuelve a ejecutar"
            ]
        return [], [f"el dispensador no presto el lote: {motivo}"]
    return list(cuerpo.get("credenciales") or []), []


def ejecutar(
    transporte,
    espacio: str,
    inicio: datetime,
    n: int = 50,
    n_franjas: int = 1,
) -> Medicion:
    """Lanza `n` solicitudes simultaneas por LA MISMA franja y mide que paso."""
    franja_disputada = (Franja(inicio.date(), inicio.hour),)
    credenciales, problemas = _pedir_lote(transporte, n)

    if problemas or not credenciales:
        vacio = Desglose.de([])
        return Medicion(
            desglose=vacio,
            simultaneidad=Simultaneidad(lanzadas=0),
            identidades_pedidas=n,
            identidades_obtenidas=len(credenciales),
            motivos_invalidez=problemas or ["el dispensador no devolvio ninguna"],
        )

    cuerpo = {
        "espacio": espacio,
        "inicio": inicio.isoformat(),
        "n_franjas": n_franjas,
    }

    def calentar(indice: int) -> None:
        """Exigencia 2. **Todo lo caro ocurre aqui, antes de la barrera.**

        Se usa una ruta de lectura a proposito: no consume cuota del contador
        (solo cuentan las que escriben), asi que calentar no le quita al
        instrumento ninguno de sus intentos.
        """
        transporte.enviar("GET", "/espacios")

    def tarea(credencial):
        def lanzar():
            codigo, respuesta = transporte.enviar(
                "POST", "/reservas", cuerpo, token=credencial["token"]
            )
            return _desenlace_de(codigo, respuesta, franja_disputada)

        return lanzar

    corrida = concurrencia.lanzar_con_barrera(
        [tarea(c) for c in credenciales], calentar=calentar
    )
    desglose = Desglose.de(corrida.desenlaces)
    simultaneidad = concurrencia.medir_simultaneidad(corrida)

    return Medicion(
        desglose=desglose,
        simultaneidad=simultaneidad,
        identidades_pedidas=n,
        identidades_obtenidas=len(credenciales),
        motivos_invalidez=_validez(desglose, simultaneidad, n, len(credenciales)),
        avisos=[f"error: {e}" for e in corrida.errores],
    )


def _validez(desglose, simultaneidad, pedidas: int, obtenidas: int) -> list:
    """Exigencia 5 · **negarse a mentir** (RF-14).

    Las tres razones por las que una corrida no se publica como evidencia de C1.
    Ninguna de ellas es un fallo del sistema de reservas: las tres son fallos de
    la MEDICION, y confundirlas seria acusar al sistema de lo que hizo mal el
    instrumento.
    """
    motivos = []
    if obtenidas < pedidas:
        motivos.append(
            f"se pidieron {pedidas} identidades y se consiguieron {obtenidas}. "
            "**No se redondea**: sin N identidades distintas no hay N "
            "competidoras (D-P4-08)"
        )
    for cubo in (Cubo.SYS_IDENTIDAD, Cubo.SYS_TASA):
        if desglose.por_cubo[cubo]:
            motivos.append(
                f"{cubo.value} = {desglose.por_cubo[cubo]}. La culpa es del "
                "instrumento o del prestamo, **nunca del sistema de reservas**"
            )
    if simultaneidad.s3_rr11 == 0:
        motivos.append(
            "cero rechazos RR-11: no hay evidencia directa de carrera. Las "
            "solicitudes pudieron llegar en fila, y entonces esto no midio la "
            "concurrencia — midio un bucle"
        )
    return motivos


# ---------------------------------------------------------------------------
# Lo que se ve en pantalla (RF-13)
# ---------------------------------------------------------------------------


def informe(medicion: Medicion, espacio: str, inicio: datetime) -> str:
    lineas = [
        "== M2-INS · el instrumento " + "=" * 44,
        "",
        f"  espacio ........................... {espacio}",
        f"  franja disputada .................. {inicio.isoformat()}",
        f"  identidades .......................  {medicion.identidades_obtenidas}"
        f" de {medicion.identidades_pedidas} pedidas",
        f"  lanzadas .......................... {medicion.simultaneidad.lanzadas}",
        f"  competidoras efectivas ............ {medicion.desglose.competidoras_efectivas}",
        f"  CONFIRMADAS ....................... {medicion.desglose.confirmadas}",
        "",
        "  reparto por desenlace:",
    ]
    lineas.extend(medicion.desglose.lineas())
    lineas += ["", "  simultaneidad observada:"]
    lineas.append(
        f"    S-1 max en vuelo a la vez ....... {medicion.simultaneidad.s1_max_en_vuelo}"
        f" de {medicion.simultaneidad.lanzadas}"
    )
    lineas.append(
        f"    S-3 rechazos RR-11 .............. {medicion.simultaneidad.s3_rr11}"
        + ("" if medicion.simultaneidad.s3_rr11 else "   <-- SIN evidencia de carrera")
    )
    lineas.append(
        f"    dispersion de la barrera ........ "
        f"{medicion.simultaneidad.dispersion_barrera_ms:.2f} ms"
    )
    lineas.append(
        "    S-2 .............................. no observable por HTTP "
        "(la miden los casos K, en proceso)"
    )
    lineas += [""]

    if medicion.doble_reserva:
        lineas += [
            "  *** DOBLE RESERVA ***",
            f"  {medicion.desglose.confirmadas} confirmaciones sobre la misma franja.",
            "  Si ves esto, la afirmacion central del proyecto es falsa. Dilo.",
            "",
        ]
    elif medicion.valida:
        lineas += [
            "  C1: exactamente una confirmacion sobre la franja disputada,",
            f"  con {medicion.desglose.competidoras_efectivas} competidoras efectivas"
            f" y {medicion.simultaneidad.s3_rr11} RR-11 como evidencia de carrera.",
            "",
        ]

    if medicion.motivos_invalidez:
        lineas.append("  MEDICION INVALIDA — no se publica como evidencia de C1:")
        for m in medicion.motivos_invalidez:
            lineas.append(f"      - {m}")
        lineas.append("")
        lineas.append(
            "  Esto NO dice que el sistema falle. Dice que esta corrida no "
            "puede afirmar nada."
        )
        lineas.append("")
    if medicion.avisos:
        lineas.append("  avisos:")
        for a in medicion.avisos:
            lineas.append(f"      - {a}")
        lineas.append("")
    return "\n".join(lineas)


def main(argv=None) -> int:
    analizador = argparse.ArgumentParser(
        description="Lanza N solicitudes simultaneas por la misma franja y "
        "declara cuanta simultaneidad hubo."
    )
    analizador.add_argument("--url", required=True, help="base del despliegue")
    analizador.add_argument("--espacio", default="E-CAN")
    analizador.add_argument("--n", type=int, default=50)
    analizador.add_argument("--n-franjas", type=int, default=1)
    analizador.add_argument(
        "--dia",
        default=None,
        help="AAAA-MM-DD. Por defecto, manana (dentro de la antelacion de E-CAN)",
    )
    analizador.add_argument("--hora", type=int, default=10)
    args = analizador.parse_args(argv)

    dia = (
        date.fromisoformat(args.dia)
        if args.dia
        else (datetime.now().date() + timedelta(days=1))
    )
    inicio = datetime(dia.year, dia.month, dia.day, args.hora)

    medicion = ejecutar(
        TransporteHttp(args.url),
        espacio=args.espacio,
        inicio=inicio,
        n=args.n,
        n_franjas=args.n_franjas,
    )
    print(informe(medicion, args.espacio, inicio))

    # **Una doble reserva es lo unico que sale distinto de cero.** Una medicion
    # invalida no lo es: no ha demostrado que el sistema falle, y devolver
    # fallo por eso confundiria "no pude medir" con "esta roto".
    return 2 if medicion.doble_reserva else 0


if __name__ == "__main__":
    sys.exit(main())
