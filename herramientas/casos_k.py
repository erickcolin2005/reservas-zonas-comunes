"""Los casos de concurrencia K-01, K-02 y K-03, con barrera de disparo.

Se usa desde dos sitios y a proposito: desde las pruebas del CI y desde la linea
de ordenes. El instrumento que un extrano ejecutara (M2-INS) es de I-6 y NO esta
aqui; lo que si esta es el motor de medicion que aquel reutilizara.

Cada caso se expresa en las tres capas del banco §5.0, y confundirlas es como se
produce un falso verde:

    I-1 CORRECCION   confirmadas <= 1 por franja. Es C1. Si se viola, ROJO.
    I-2 VIVACIDAD    cada franja disputada tiene exactamente 1 confirmada.
                     Es el guardia contra el sistema que rechaza todo, que
                     satisface la correccion y no sirve para nada. Si se viola,
                     ROJO con clase distinta.
    I-3 VALIDEZ      la corrida tenia derecho a opinar. Si no, MEDICION
                     INVALIDA: no rompe el build y NO se publica como evidencia.

Uso:  python -m herramientas.casos_k [--repeticiones N]
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from reservas import concurrencia, config, sembrado
from reservas.adaptadores import dynamodb
from reservas.casos_uso.reservar import reservar
from reservas.desenlaces import Desglose, Invariantes, Simultaneidad, evaluar_invariantes, informe
from reservas.nucleo import tiempo
from reservas.nucleo.modelo import Solicitud


@dataclass(frozen=True)
class CasoK:
    """Un caso de concurrencia, con sus tres capas ya declaradas."""

    id: str
    descripcion: str
    solicitudes: tuple[Solicitud, ...]
    confirmadas_esperadas: int
    minimo_competidoras: int
    confirmadas_por_franja: int = 1


@dataclass
class Resultado:
    caso: CasoK
    desglose: Desglose
    simultaneidad: Simultaneidad
    invariantes: Invariantes
    texto: str = ""
    errores: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Los tres casos. Los valores salen del banco §5.1 tal cual.
# ---------------------------------------------------------------------------


def k01(t0: datetime, conjunto: sembrado.Conjunto) -> CasoK:
    """50 unidades distintas, la MISMA franja. E-CAN D+4 10:00-11:00.

    Cincuenta transacciones sobre la misma clave. Una aplica.
    """
    unidades = conjunto.rafaga[:50]
    inicio = tiempo.instante_mas(t0, 4, 10)
    return CasoK(
        id="K-01",
        descripcion="50 unidades distintas por la misma franja de E-CAN",
        solicitudes=tuple(
            Solicitud(unidad=u, espacio="E-CAN", inicio=inicio, n_franjas=1)
            for u in unidades
        ),
        confirmadas_esperadas=1,
        minimo_competidoras=50,
    )


def k02(t0: datetime, conjunto: sembrado.Conjunto) -> CasoK:
    """Solapamiento PARCIAL: E-SAL D+6 10:00-14:00 contra 12:00-16:00.

    Es el caso que separa un sistema de un tutorial. Comparten las claves de las
    12 y las 13 y nada mas. Un diseno que escribiera franja a franja podria
    dejar a cada una con la mitad y **ninguna confirmar**, ademas de dejar
    franjas tomadas por reservas que no existen. La transaccion todo-o-nada es
    lo que lo impide.
    """
    return CasoK(
        id="K-02",
        descripcion="solapamiento parcial 10-14 contra 12-16 en E-SAL",
        solicitudes=(
            Solicitud(conjunto.rafaga[0], "E-SAL", tiempo.instante_mas(t0, 6, 10), 4),
            Solicitud(conjunto.rafaga[1], "E-SAL", tiempo.instante_mas(t0, 6, 12), 4),
        ),
        confirmadas_esperadas=1,
        # Con solo dos solicitudes, un solo SYS-CAPACIDAD invalida la corrida
        # entera: hay que repetirla, no interpretarla.
        minimo_competidoras=2,
    )


def k03(t0: datetime, conjunto: sembrado.Conjunto) -> CasoK:
    """50 repartidas entre 5 franjas de E-CAN D+4, 10 por franja.

    **Este es el guardia contra el sistema que rechaza todo.** Un sistema que
    devolviera siempre "no" satisface la correccion —jamas hay dos
    confirmaciones— y falla la vivacidad. K-03 exige CINCO confirmadas, no cero
    dobles: cinco grupos de claves disjuntos, y rechazar de mas seria rechazar
    claves que nadie disputa.
    """
    unidades = conjunto.rafaga[:50]
    solicitudes = []
    for indice, unidad in enumerate(unidades):
        hora = 10 + (indice % 5)
        solicitudes.append(
            Solicitud(unidad, "E-CAN", tiempo.instante_mas(t0, 4, hora), 1)
        )
    return CasoK(
        id="K-03",
        descripcion="50 simultaneas repartidas entre 5 franjas de E-CAN",
        solicitudes=tuple(solicitudes),
        confirmadas_esperadas=5,
        minimo_competidoras=50,
    )


CASOS = {"K-01": k01, "K-02": k02, "K-03": k03}


# ---------------------------------------------------------------------------
# Ejecucion
# ---------------------------------------------------------------------------


def ejecutar(
    caso: CasoK,
    endpoint: str,
    t0: datetime,
    fabrica_adaptador=None,
    tabla: str = config.TABLA,
) -> Resultado:
    """Lanza el caso con barrera de disparo y mide lo que ocurrio.

    `fabrica_adaptador(cliente, indice)` permite inyectar una implementacion
    distinta, y distinta por solicitud. Es lo que usa H2 para revertir la
    defensa y comprobar que la prueba sabe ponerse en rojo. El indice importa:
    una de las mutaciones necesita que la MITAD de las solicitudes normalice de
    otra manera, que es como se produce el fallo que se quiere demostrar.
    """
    fabrica_adaptador = fabrica_adaptador or (
        lambda cliente, indice: dynamodb.AdaptadorDynamoDB(cliente, tabla)
    )
    adaptadores: dict[int, object] = {}

    def calentar(indice: int) -> None:
        """TODO lo caro ocurre aqui, ANTES de la barrera.

        Crear el cliente, abrir la conexion y usarla una vez. Sin esto, el
        establecimiento de conexion produce una fila justo donde no puede
        haberla, y la prueba mediria el orden de arranque de los hilos en vez de
        la carrera.
        """
        cliente = dynamodb.crear_cliente(endpoint)
        cliente.describe_table(TableName=tabla)
        adaptadores[indice] = fabrica_adaptador(cliente, indice)

    def tarea(indice: int):
        return lambda: reservar(caso.solicitudes[indice], adaptadores[indice], t0)

    corrida = concurrencia.lanzar_con_barrera(
        [tarea(i) for i in range(len(caso.solicitudes))], calentar=calentar
    )

    desglose = Desglose.de(corrida.desenlaces)
    simultaneidad = concurrencia.medir_simultaneidad(corrida)
    invariantes = evaluar_invariantes(
        concurrencia.agrupar_por_franja(corrida.desenlaces),
        minimo_competidoras=caso.minimo_competidoras,
        confirmadas_esperadas_total=caso.confirmadas_esperadas,
        maximo_confirmadas_por_franja=caso.confirmadas_por_franja,
    )
    texto = informe(
        f"{caso.id} — {caso.descripcion}", desglose, simultaneidad, invariantes
    )
    if corrida.errores:
        texto += "  errores de ejecucion:\n" + "\n".join(
            f"      - {e}" for e in corrida.errores
        )
        texto += "\n"
    return Resultado(caso, desglose, simultaneidad, invariantes, texto, corrida.errores)


def preparar(cliente, t0: datetime) -> sembrado.Conjunto:
    """Tabla limpia y sembrada. Los casos no acumulan estado entre si."""
    dynamodb.recrear_tabla(cliente, config.TABLA)
    return sembrado.sembrar(cliente, config.TABLA, t0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Casos de concurrencia K de I-1")
    parser.add_argument("--repeticiones", type=int, default=1)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--casos", nargs="*", default=list(CASOS))
    parser.add_argument(
        "--evidencia",
        default=None,
        help="fichero donde dejar constancia de la salida",
    )
    args = parser.parse_args(argv)

    endpoint = args.endpoint or config.endpoint()
    cliente = dynamodb.crear_cliente(endpoint)
    t0 = tiempo.t0_desde(datetime.now(timezone.utc))

    partes = [
        f"Casos K contra el sustituto local — {endpoint}",
        f"T0 derivado: {t0.isoformat()}",
        "",
    ]
    rojo = False
    for repeticion in range(1, args.repeticiones + 1):
        for nombre in args.casos:
            conjunto = preparar(cliente, t0)
            resultado = ejecutar(CASOS[nombre](t0, conjunto), endpoint, t0)
            cabecera = (
                f"[repeticion {repeticion}/{args.repeticiones}]"
                if args.repeticiones > 1
                else ""
            )
            partes.append(cabecera)
            partes.append(resultado.texto)
            rojo = rojo or resultado.invariantes.build_en_rojo

    salida = "\n".join(partes)
    print(salida)
    if args.evidencia:
        destino = pathlib.Path(args.evidencia)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(salida + "\n", encoding="utf-8")
    return 1 if rojo else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
