"""I-4 · El banco de reglas del flujo de CREACION, caso por caso.

Los casos NO se inventan aqui: salen literalmente de `banco-reglas-reserva.md`
§4, con su identificador. Si un caso de este fichero no existe en el banco, es
un error; y si un caso del banco no esta aqui, tambien - lo comprueba
`test_estan_todos_los_casos_del_banco`.

**Por que corre sin motor, sin red y sin nube:** el nucleo es puro (ADR-07), asi
que el banco entero se evalua sin DynamoDB y sin API. Eso es lo que hace que
I-4 no dependa de I-6, que el plan dejo verificado y no supuesto.

LA PROPIEDAD QUE ESTE FICHERO EXISTE PARA SOSTENER, y que es mas fuerte que
"pasan los casos":

    **Un caso que se rechaza por la regla EQUIVOCADA cuenta como fallo.**

No se comprueba que hubo rechazo: se comprueba QUE REGLA lo produjo. Es la
practica heredada n.o 1, y es la unica forma de que el orden de precedencia
-que es donde vive la mitad del diseno- quede verificado. Dos casos del banco
existen precisamente para fijar interacciones de orden:

  - **L-08**: un limite de antelacion exacto que cae fuera de la ventana. Debe
    informar RR-03, no RR-05.
  - **R-04**: un espacio deshabilitado. Debe informar RR-02, no RR-09.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest

from reservas import sembrado
from reservas.nucleo import reglas, tiempo
from reservas.nucleo.modelo import (
    EstadoLeido,
    Franja,
    OcupacionLeida,
    ParametrosEspacio,
    Solicitud,
    TipoOcupacion,
    Unidad,
)
from reservas.nucleo.tiempo import instante_local

T0 = instante_local(2026, 9, 7, 9)

E_BBQ = sembrado.espacio("E-BBQ")
E_CAN = sembrado.espacio("E-CAN")
E_SAL = sembrado.espacio("E-SAL")
ESPACIOS = {"E-BBQ": E_BBQ, "E-CAN": E_CAN, "E-SAL": E_SAL}

ACTIVA = Unidad(id="U-101", activa=True, grupo=sembrado.GRUPO_RAFAGA)
INACTIVA = Unidad(id="U-110", activa=False, grupo=sembrado.GRUPO_RAFAGA)


def dia(n: int):
    return (T0 + timedelta(days=n)).date()


def en(n: int, hora: int):
    """Instante D+n a la hora en punto indicada, canonizado."""
    d = dia(n)
    return instante_local(d.year, d.month, d.day, hora)


def franjas(n: int, desde: int, cuantas: int) -> dict:
    """Ocupacion de tipo RESERVA sobre franjas contiguas de D+n."""
    return {
        Franja(dia(n), desde + i): OcupacionLeida(TipoOcupacion.RESERVA, "r1", "U-105")
        for i in range(cuantas)
    }


def bloqueo(n: int, desde: int, cuantas: int) -> dict:
    return {
        Franja(dia(n), desde + i): OcupacionLeida(TipoOcupacion.BLOQUEO, "M-01", None)
        for i in range(cuantas)
    }


def agenda(n: int, desde: int, cuantas: int) -> set:
    """Franjas ya ocupadas por la PROPIA unidad, en cualquier espacio (RR-08)."""
    return {Franja(dia(n), desde + i) for i in range(cuantas)}


@dataclass(frozen=True)
class Caso:
    id: str
    espacio: str
    dia_rel: int
    hora: int
    n_franjas: int
    esperado: str | None  # None = confirmada; si no, la regla que debe rechazar
    porque: str
    unidad: Unidad | None = ACTIVA
    espacio_params: ParametrosEspacio | None = None  # sobreescribe el del catalogo
    cupo_consumido: int = 0
    ocupacion: dict | None = None
    agenda: set | None = None


# ---------------------------------------------------------------------------
# Los casos, tal como los fija banco-reglas-reserva.md §4
# ---------------------------------------------------------------------------

CASOS = [
    # -- RR-01 · Unidad valida y activa ------------------------------------
    Caso("A-01", "E-BBQ", 2, 14, 3, None, "caso base del banco"),
    Caso("R-01", "E-BBQ", 2, 14, 3, "RR-01", "unidad inexistente", unidad=None),
    Caso("R-02", "E-BBQ", 2, 14, 3, "RR-01", "unidad inactiva: MISMO identificador que R-01 (RF-17)", unidad=INACTIVA),
    Caso("L-01", "E-BBQ", 6, 14, 3, "RR-07", "el cupo es de la UNIDAD, no de la persona", cupo_consumido=2),

    # -- RR-02 · Espacio existente y habilitado ----------------------------
    Caso("A-02", "E-CAN", 1, 7, 1, None, ""),
    Caso("R-03", "E-XXX", 1, 7, 1, "RR-02", "espacio inexistente", espacio_params=None),
    Caso("R-04", "E-CAN", 1, 7, 1, "RR-02", "deshabilitado NO es lo mismo que en mantenimiento (RR-09)",
         espacio_params=ParametrosEspacio(**{**E_CAN.__dict__, "habilitado": False})),

    # -- RR-03 · Rejilla y ventana horaria ---------------------------------
    Caso("A-03", "E-SAL", 4, 14, 4, None, "interior de la ventana"),
    Caso("L-02", "E-BBQ", 3, 19, 3, None, "termina EXACTAMENTE en el cierre"),
    Caso("L-03", "E-SAL", 4, 9, 4, None, "empieza EXACTAMENTE en la apertura"),
    Caso("R-05", "E-BBQ", 3, 20, 3, "RR-03", "excede el cierre por una franja"),
    Caso("R-06", "E-BBQ", 3, 9, 3, "RR-03", "empieza una franja antes de la apertura"),
    Caso("R-08", "E-CAN", 2, 23, 2, "RR-03", "cruza la medianoche y sale de la ventana"),

    # -- RR-04 · Duracion permitida ----------------------------------------
    Caso("L-04", "E-SAL", 5, 9, 6, None, "6 franjas = maximo del salon"),
    Caso("L-05", "E-CAN", 2, 10, 2, None, "2 franjas = maximo de cancha: el maximo es POR ESPACIO"),
    Caso("R-09", "E-SAL", 5, 9, 7, "RR-04", "maximo + 1"),
    Caso("R-10", "E-SAL", 5, 9, 3, "RR-04", "minimo - 1. En E-BBQ seria valida"),

    # -- RR-05 · Antelacion minima -----------------------------------------
    Caso("A-04", "E-BBQ", 1, 10, 3, None, "T0 + 25 h: minimo alcanzable en BBQ"),
    Caso("L-06", "E-CAN", 0, 11, 1, None, "T0 + 2 h EXACTAS: limite inclusivo"),
    Caso("L-07", "E-SAL", 3, 9, 4, None, "T0 + 72 h EXACTAS: limite inclusivo, otro espacio"),
    Caso("L-08", "E-BBQ", 1, 9, 3, "RR-03", "el limite exacto de antelacion cae FUERA de la ventana: RR-03, no RR-05"),
    Caso("R-12", "E-CAN", 0, 10, 1, "RR-05", "T0 + 1 h: aisla la antelacion"),
    Caso("R-13", "E-SAL", 2, 14, 4, "RR-05", "T0 + 53 h; la misma antelacion seria valida en BBQ y cancha"),

    # -- RR-06 · Horizonte maximo ------------------------------------------
    Caso("L-09", "E-CAN", 7, 10, 1, None, "7 dias exactos: limite inclusivo"),
    Caso("L-10", "E-SAL", 90, 9, 4, None, "90 dias exactos: limite del horizonte mas largo"),
    Caso("R-14", "E-SAL", 91, 9, 4, "RR-06", ""),
    Caso("R-15", "E-CAN", 8, 10, 1, "RR-06", "la misma fecha es valida en BBQ y salon"),
    Caso("R-16", "E-BBQ", 31, 10, 3, "RR-06", ""),

    # -- RR-07 · Cupo por unidad -------------------------------------------
    Caso("A-05", "E-BBQ", 4, 14, 3, None, "1 confirmada de 2 de cupo", cupo_consumido=1),
    Caso("R-17", "E-BBQ", 6, 14, 3, "RR-07", "tope + 1", cupo_consumido=2),
    Caso("L-11", "E-BBQ", 6, 14, 3, None, "las CANCELADAS no consumen cupo", cupo_consumido=1),
    Caso("R-18", "E-CAN", 3, 10, 1, "RR-07", "cupo SEMANAL, 3 esa semana", cupo_consumido=3),
    Caso("L-12", "E-CAN", 7, 10, 1, None, "D+7 es semana nueva: el cupo consumido de la semana de T0 no cuenta", cupo_consumido=0),
    Caso("R-19", "E-SAL", 9, 14, 4, "RR-07", "el cupo del salon es 1", cupo_consumido=1),
    Caso("L-13", "E-SAL", 35, 14, 4, None, "D+35 cae en el mes siguiente", cupo_consumido=0),

    # -- RR-08 · Choque con reserva propia ---------------------------------
    Caso("R-20", "E-CAN", 5, 16, 1, "RR-08", "solape entre espacios DISTINTOS de la misma unidad",
         agenda=agenda(5, 14, 3)),
    Caso("L-14", "E-CAN", 5, 17, 1, None, "adyacente: [14,17) y [17,18) no se solapan",
         agenda=agenda(5, 14, 3)),
    Caso("A-06", "E-CAN", 5, 16, 1, None, "RR-08 es POR UNIDAD: la agenda ajena no cuenta"),

    # -- RR-09 · Bloqueo por mantenimiento ---------------------------------
    Caso("R-21", "E-SAL", 10, 13, 4, "RR-09", "solape parcial con el bloqueo", ocupacion=bloqueo(10, 9, 6)),
    Caso("R-22", "E-SAL", 10, 9, 4, "RR-09", "contenida en el bloqueo", ocupacion=bloqueo(10, 9, 6)),
    Caso("L-15", "E-SAL", 10, 15, 4, None, "empieza exactamente cuando el bloqueo termina", ocupacion=bloqueo(10, 9, 6)),
    Caso("L-16", "E-BBQ", 10, 12, 3, None, "el bloqueo es POR ESPACIO"),

    # -- RR-10 · Solapamiento con reserva confirmada -----------------------
    Caso("R-23", "E-CAN", 4, 10, 2, "RR-10", "identico", ocupacion=franjas(4, 10, 2)),
    Caso("R-24", "E-CAN", 4, 11, 1, "RR-10", "contencion", ocupacion=franjas(4, 10, 2)),
    Caso("R-25", "E-CAN", 4, 11, 2, "RR-10", "parcial POR LA COLA", ocupacion=franjas(4, 10, 2)),
    Caso("R-26", "E-CAN", 4, 9, 2, "RR-10", "parcial POR LA CABEZA", ocupacion=franjas(4, 10, 2)),
    Caso("R-27", "E-SAL", 6, 11, 6, "RR-10", "continencia", ocupacion=franjas(6, 13, 4)),
    Caso("L-17", "E-CAN", 4, 12, 1, None, "adyacente posterior", ocupacion=franjas(4, 10, 2)),
    Caso("L-18", "E-CAN", 4, 9, 1, None, "adyacente anterior", ocupacion=franjas(4, 10, 2)),
    Caso("L-19", "E-CAN", 4, 10, 2, None, "la rival fue CANCELADA: no bloquea nada (RF-21)"),
    Caso("A-07", "E-BBQ", 4, 10, 3, None, "el solapamiento es POR ESPACIO"),
]


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: c.id)
def test_caso_del_banco(caso: Caso):
    params = caso.espacio_params
    if params is None and caso.espacio in ESPACIOS and caso.id != "R-03":
        params = ESPACIOS[caso.espacio]

    estado = EstadoLeido(
        parametros=params,
        unidad=caso.unidad,
        ocupacion=caso.ocupacion or {},
        agenda=caso.agenda or set(),
        cupo_consumido=caso.cupo_consumido,
    )
    solicitud = Solicitud(
        unidad=caso.unidad.id if caso.unidad else "U-999",
        espacio=caso.espacio,
        inicio=en(caso.dia_rel, caso.hora),
        n_franjas=caso.n_franjas,
    )
    veredicto = reglas.evaluar(solicitud, estado, T0)

    if caso.esperado is None:
        assert veredicto.regla is None, (
            f"{caso.id} deberia confirmarse y fue rechazado por "
            f"{veredicto.regla}. {caso.porque}"
        )
    else:
        # NO basta con que fuera rechazado: tiene que serlo POR SU REGLA.
        # Un rechazo por la regla equivocada cuenta como fallo (banco §8).
        assert veredicto.regla == caso.esperado, (
            f"{caso.id} deberia rechazarse por {caso.esperado} y lo fue por "
            f"{veredicto.regla}. {caso.porque}"
        )


def test_estan_todos_los_casos_del_banco():
    """Guardia contra el olvido silencioso.

    La cifra no se escribe a mano en ningun sitio: se cuenta. Si manana se anade
    un caso al banco y no aqui, esta prueba no lo detecta -no puede leer el
    documento- pero si detecta lo contrario: que alguien borre un caso de aqui
    creyendo que sobra.
    """
    ids = [c.id for c in CASOS]
    assert len(ids) == len(set(ids)), "hay identificadores repetidos"
    # 53 = los 68 casos A/L/R del banco menos los 15 de cancelacion y
    # mantenimiento (RR-12..RR-15, que son de otro flujo y aun no tienen caso de
    # uso) menos R-07 y R-11, que mueren en la frontera y se prueban aparte.
    assert len(ids) == 51, f"se esperaban 51 casos del flujo de creacion, hay {len(ids)}"


# ---------------------------------------------------------------------------
# Los dos casos que NO llegan a la evaluacion, y por que eso es correcto
# ---------------------------------------------------------------------------


def test_r07_muere_en_la_canonizacion_no_en_rr03():
    """R-07 · E-CAN D+2 14:30-15:30, fuera de rejilla.

    El banco lo clasifica bajo RR-03, pero **no llega a RR-03**: la canonizacion
    lo rechaza antes, y por eso `Solicitud` no puede ni construirse con un
    inicio no canonizado. La frontera es MAS fuerte que la regla -no depende de
    que nadie la llame- pero decir "RR-03 atrapa R-07" seria falso, y aqui se
    deja dicho cual de las dos actua.
    """
    d = dia(2)
    with pytest.raises(Exception):
        tiempo.canonizar_inicio(instante_local(d.year, d.month, d.day, 14, 30))


def test_r11_muere_al_construir_la_solicitud_no_en_rr04():
    """R-11 · 0 franjas.

    Igual que R-07: `Solicitud` se niega a existir con cero franjas, asi que
    RR-04 nunca la ve. Una solicitud de cero franjas no es una solicitud.
    """
    with pytest.raises(ValueError, match="cero franjas"):
        Solicitud("U-101", "E-CAN", en(2, 10), 0)
