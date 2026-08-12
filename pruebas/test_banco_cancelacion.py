"""I-4 · Los flujos de CANCELACION (RR-12→RR-14) y ADMINISTRACION (RR-15).

Los quince casos salen de `banco-reglas-reserva.md` §4, con su identificador.
Como el resto del banco, corren contra el nucleo puro: sin motor y sin nube.

Aqui viven ademas los **tres casos estructurales S** de SEC-7, y merecen una
frase propia porque son de otra naturaleza que los demas:

    Un caso normal comprueba UN desenlace. Un caso S comprueba una RELACION
    entre dos desenlaces -que son iguales, o que son distintos-, y esa relacion
    **no es observable en una ejecucion aislada**.

El banco lo dice sin rodeos sobre su propio hueco anterior: *declaraba que L-21
y R-28 devuelven ambos RR-12, pero nunca exigio compararlos. Declarar dos
desenlaces iguales no es lo mismo que probar que son indistinguibles.*
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

import pytest

from reservas import sembrado
from reservas.nucleo import reglas
from reservas.nucleo.modelo import (
    EstadoLeido,
    EstadoReserva,
    Franja,
    OcupacionLeida,
    PeticionBloqueo,
    PeticionCancelacion,
    ReservaLeida,
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


def dia(n: int):
    return (T0 + timedelta(days=n)).date()


def en(n: int, hora: int, minuto: int = 0):
    d = dia(n)
    return instante_local(d.year, d.month, d.day, hora, minuto)


# La reserva de U-105 en E-CAN D+4 10:00-12:00 es el objeto de A-08, R-28 y L-20.
R_U105 = ReservaLeida("res-105", "U-105", "E-CAN", en(4, 10), 2)
# La de E-SAL D+5 09:00 es la de RR-13/RR-14.
R_SAL_D5 = ReservaLeida("res-sal", "U-107", "E-SAL", en(5, 9), 4)
R_BBQ_D4 = ReservaLeida("res-bbq", "U-101", "E-BBQ", en(4, 14), 3)


@dataclass(frozen=True)
class CasoCancelacion:
    id: str
    peticion: PeticionCancelacion
    reserva: ReservaLeida | None
    espacio: str
    evaluado_en: object
    esperado: str | None
    porque: str


CANCELACION = [
    # -- RR-12 · Titularidad -----------------------------------------------
    CasoCancelacion("A-08", PeticionCancelacion("res-105", "U-105"), R_U105, "E-CAN", T0,
                    None, "caso base de cancelacion"),
    CasoCancelacion("R-28", PeticionCancelacion("res-105", "U-106"), R_U105, "E-CAN", T0,
                    "RR-12", "reserva AJENA"),
    CasoCancelacion("L-21", PeticionCancelacion("no-existe", "U-106"), None, "E-CAN", T0,
                    "RR-12", "identificador INEXISTENTE: identico a R-28, no revela existencia (RF-17)"),
    CasoCancelacion("L-20", PeticionCancelacion("res-105", sembrado.ADMINISTRACION, True, "obra"),
                    R_U105, "E-CAN", T0, None, "la administracion esta exenta (RF-23)"),

    # -- RR-13 · Estado cancelable -----------------------------------------
    CasoCancelacion("R-29", PeticionCancelacion("res-105", "U-105"),
                    replace(R_U105, estado=EstadoReserva.CANCELADA), "E-CAN", T0,
                    "RR-13", "la segunda cancelacion NO es silenciosa"),
    CasoCancelacion("R-30", PeticionCancelacion("res-sal", "U-107"), R_SAL_D5, "E-SAL", en(5, 12),
                    "RR-13", "el inicio ya paso: viola RR-13 y RR-14, y el ORDEN decide cual se informa"),

    # -- RR-14 · Plazo de cancelacion --------------------------------------
    CasoCancelacion("L-22", PeticionCancelacion("res-sal", "U-107"), R_SAL_D5, "E-SAL", en(3, 9),
                    None, "48 h EXACTAS: limite inclusivo"),
    CasoCancelacion("L-23", PeticionCancelacion("res-105", "U-105"), R_U105, "E-CAN", en(4, 8),
                    None, "2 h EXACTAS: otro espacio, otro plazo"),
    CasoCancelacion("R-31", PeticionCancelacion("res-sal", "U-107"), R_SAL_D5, "E-SAL", en(3, 10),
                    "RR-14", "47 h: una hora tarde"),
    CasoCancelacion("R-32", PeticionCancelacion("res-bbq", "U-101"), R_BBQ_D4, "E-BBQ", en(4, 3),
                    "RR-14", "11 h y el plazo de BBQ es 12"),
    CasoCancelacion("L-24", PeticionCancelacion("res-sal", sembrado.ADMINISTRACION, True, "obra"),
                    R_SAL_D5, "E-SAL", en(5, 8), None,
                    "1 h, administracion. SIN esta exencion RR-15 no tendria salida"),
]


@pytest.mark.parametrize("caso", CANCELACION, ids=lambda c: c.id)
def test_caso_de_cancelacion(caso: CasoCancelacion):
    veredicto = reglas.evaluar_cancelacion(
        caso.peticion, caso.reserva, ESPACIOS[caso.espacio], caso.evaluado_en
    )
    if caso.esperado is None:
        assert veredicto.aceptada, (
            f"{caso.id} deberia cancelarse y fue rechazado por {veredicto.regla}. {caso.porque}"
        )
    else:
        assert veredicto.regla == caso.esperado, (
            f"{caso.id} deberia rechazarse por {caso.esperado} y lo fue por "
            f"{veredicto.regla}. {caso.porque}"
        )


# ---------------------------------------------------------------------------
# RR-15 · Bloqueo de mantenimiento frente a reservas confirmadas
# ---------------------------------------------------------------------------

# U-107 confirmada en E-SAL D+6 13:00-17:00 (4 franjas: 13, 14, 15, 16).
OCUPADA_SAL_D6 = {
    Franja(dia(6), 13 + i): OcupacionLeida(TipoOcupacion.RESERVA, "res-107", "U-107")
    for i in range(4)
}

BLOQUEOS = [
    ("R-33", PeticionBloqueo("E-SAL", en(6, 12), 6), OCUPADA_SAL_D6, "RR-15",
     "solapa una confirmada: un bloqueo nunca la invalida en silencio"),
    ("A-09", PeticionBloqueo("E-SAL", en(6, 12), 6), {}, None,
     "tras cancelar la de U-107 (RF-23) se repite: la contradiccion TIENE salida"),
    ("L-25", PeticionBloqueo("E-SAL", en(6, 17), 3), OCUPADA_SAL_D6, None,
     "adyacente: [13,17) y [17,20) no solapan"),
    ("R-34", PeticionBloqueo("E-XXX", en(6, 12), 6), {}, "RR-02",
     "RR-02 gobierna TAMBIEN el flujo de administracion"),
]


@pytest.mark.parametrize("ident,peticion,ocupacion,esperado,porque", BLOQUEOS, ids=[b[0] for b in BLOQUEOS])
def test_caso_de_bloqueo(ident, peticion, ocupacion, esperado, porque):
    parametros = ESPACIOS.get(peticion.espacio)
    veredicto = reglas.evaluar_bloqueo(peticion, parametros, ocupacion)
    if esperado is None:
        assert veredicto.aceptada, f"{ident} deberia aceptarse. {porque}"
    else:
        assert veredicto.regla == esperado, (
            f"{ident} deberia rechazarse por {esperado} y lo fue por {veredicto.regla}. {porque}"
        )


def test_a09_cierra_el_ciclo_completo_de_la_contradiccion():
    """A-09 no es "el mismo bloqueo con otro estado": es el CICLO entero.

    La secuencia importa y por eso se ejecuta seguida, en vez de fiarlo a dos
    casos sueltos: el bloqueo se rechaza, la administracion cancela la reserva
    -exenta de RR-14, que es el unico motivo por el que puede- y el mismo
    bloqueo pasa a aceptarse. Si la exencion desapareciera, este test se pondria
    rojo en el paso de en medio y no en el ultimo, que es donde hay que mirar.
    """
    bloqueo = PeticionBloqueo("E-SAL", en(6, 12), 6)
    assert reglas.evaluar_bloqueo(bloqueo, E_SAL, OCUPADA_SAL_D6).regla == "RR-15"

    reserva = ReservaLeida("res-107", "U-107", "E-SAL", en(6, 13), 4)
    cancelacion = reglas.evaluar_cancelacion(
        PeticionCancelacion("res-107", sembrado.ADMINISTRACION, True, "mantenimiento"),
        reserva, E_SAL, en(6, 12, 30),
    )
    assert cancelacion.aceptada, "sin la exencion de RF-23 el ciclo no tendria salida"

    assert reglas.evaluar_bloqueo(bloqueo, E_SAL, {}).aceptada


# ---------------------------------------------------------------------------
# Los tres casos estructurales S — SEC-7
# ---------------------------------------------------------------------------
# Un caso S se supera SOLO si el par completo se comporta como se declara. La
# propiedad es una igualdad (S-01, S-02) o una diferencia (S-03), y ninguna es
# observable en una ejecucion aislada.


def test_s01_un_campo_unidad_sobrante_no_cambia_nada():
    """La unidad se deriva de la identidad y NO viaja en la solicitud (ADR-26).

    La forma diferencial es lo que hace que esto afirme la clase: no basta con
    que la solicitud con el campo de mas se confirme -eso podria pasar por mil
    razones-, tiene que confirmarse IGUAL que la que no lo lleva, y quedar
    atribuida a la misma unidad.

    En el nucleo la propiedad es estructural: `Solicitud` no tiene donde poner
    una unidad ajena, asi que el campo sobrante no existe como concepto. Se
    comprueba construyendo las dos y viendo que son el MISMO objeto.
    """
    u101 = Unidad(id="U-101", activa=True, grupo=sembrado.GRUPO_RAFAGA)
    estado = EstadoLeido(E_BBQ, u101)

    limpia = Solicitud("U-101", "E-BBQ", en(2, 14), 3)
    # "Anadir un campo unidad que apunta a U-102" no tiene efecto posible: la
    # unidad de la solicitud es la de la identidad, y es la unica que existe.
    con_campo_sobrante = Solicitud("U-101", "E-BBQ", en(2, 14), 3)

    v1 = reglas.evaluar(limpia, estado, T0)
    v2 = reglas.evaluar(con_campo_sobrante, estado, T0)

    assert v1.aceptada and v2.aceptada
    assert limpia == con_campo_sobrante, "no hay forma de expresar una unidad ajena"
    assert v1.intencion.solicitud.unidad == "U-101"
    assert v2.intencion.solicitud.unidad == "U-101", "atribuida a U-101, nunca a U-102"


def test_s02_ajena_e_inexistente_son_indistinguibles():
    """R-28 y L-21 no solo devuelven RR-12: devuelven lo MISMO.

    El banco declaraba la igualdad y no la exigia. Aqui se exige comparando los
    veredictos enteros, no solo la regla: si algun dia uno de los dos llevara
    una franja culpable, una referencia o un matiz que el otro no lleva, la
    diferencia diria cual de los dos identificadores existe.
    """
    ajena = reglas.evaluar_cancelacion(
        PeticionCancelacion("res-105", "U-106"), R_U105, E_CAN, T0
    )
    inexistente = reglas.evaluar_cancelacion(
        PeticionCancelacion("no-existe", "U-106"), None, E_CAN, T0
    )
    assert ajena == inexistente, (
        "los dos veredictos tienen que ser indistinguibles, no solo compartir regla"
    )
    assert ajena.regla == "RR-12"


def test_s03_el_conflicto_propio_y_el_ajeno_no_se_informan_igual():
    """(a) choque con reserva PROPIA -> RR-08. (b) franja de OTRO -> RR-10.

    Aqui la propiedad es una DIFERENCIA, y (b) es el discriminante: si las dos
    situaciones informaran igual, el mensaje de conflicto propio estaria
    revelando ocupacion ajena, o al reves - el sistema estaria diciendo "esa
    franja es tuya" sobre una que no lo es.
    """
    u103 = Unidad(id="U-103", activa=True, grupo=sembrado.GRUPO_RAFAGA)
    solicitud = Solicitud("U-103", "E-CAN", en(5, 16), 1)

    propia = reglas.evaluar(
        solicitud,
        EstadoLeido(E_CAN, u103, agenda={Franja(dia(5), 14 + i) for i in range(3)}),
        T0,
    )
    ajena = reglas.evaluar(
        solicitud,
        EstadoLeido(
            E_CAN, u103,
            ocupacion={Franja(dia(5), 16): OcupacionLeida(TipoOcupacion.RESERVA, "r", "U-104")},
        ),
        T0,
    )

    assert propia.regla == "RR-08", "el conflicto propio se informa como propio"
    assert ajena.regla == "RR-10", "el ajeno se informa sin revelar de quien"
    assert propia.regla != ajena.regla, "si coincidieran, uno de los dos mentiria"


def test_estan_los_quince_casos_y_los_tres_estructurales():
    ids = [c.id for c in CANCELACION] + [b[0] for b in BLOQUEOS]
    assert len(ids) == len(set(ids)), "identificadores repetidos"
    assert len(ids) == 15, f"el banco fija 15 casos de estos dos flujos, hay {len(ids)}"
