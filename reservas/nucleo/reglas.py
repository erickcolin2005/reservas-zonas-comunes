"""El nucleo de reglas. Puro: sin reloj, sin red, sin motor, sin aleatoriedad.

`evaluar(solicitud, estado, instante_ref) -> Veredicto`

**El numero de la regla ES su orden de evaluacion** (banco §3). Se devuelve la
primera violada (RF-06). El orden es el que hace el banco verificable: sin el,
dos ejecuciones del mismo caso informarian reglas distintas.

------------------------------------------------------------------------------
QUE HAY EN I-1 Y QUE NO — leelo antes de dar esto por completo
------------------------------------------------------------------------------
I-1 cierra la carrera y nada mas. De las once reglas del camino de creacion,
aqui viven implementadas **las cuatro que el mecanismo de concurrencia
necesita**, porque son las que comparten codigo con las condiciones de la
transaccion:

    RR-07  cupo          (lectura; la condicion del contador manda)
    RR-08  choque propio (lectura; la condicion de AGENDA# manda)
    RR-09  mantenimiento (lectura, por tipo=BLOQUEO)
    RR-10  solapamiento  (SOLO lectura previa)

Las seis primeras —RR-01 unidad, RR-02 espacio, RR-03 ventana y medianoche,
RR-04 duracion, RR-05 antelacion, RR-06 horizonte— **no se evaluan en I-1**.
Estan registradas en el orden que les toca y marcadas como pendientes, para que
I-4 rellene el cuerpo sin tocar el orden. Registrarlas vacias en su sitio es mas
honesto que no registrarlas: el hueco se ve.

De la rejilla de RR-03 si hay una parte aqui: la alineacion a la rejilla la
comprueba `tiempo.canonizar_inicio` antes de construir ninguna clave (§4.3
regla 4). Lo que falta de RR-03 es la ventana horaria y la medianoche.

**RR-11 no esta en este modulo y no puede estarlo.** Es alcanzable solo desde la
condicion de escritura. Que `evaluar()` no pueda devolverla nunca es una
propiedad estructural y tiene su prueba:
`pruebas/test_reglas_nucleo.py::test_rr11_es_inalcanzable_desde_la_lectura`.
Ahi es donde la distincion RR-10 / RR-11 deja de ser una etiqueta.
"""

from __future__ import annotations

from datetime import datetime

from .modelo import (
    EstadoLeido,
    IntencionEscritura,
    Solicitud,
    TipoOcupacion,
    Veredicto,
)

ORDEN_CREACION = (
    "RR-01",
    "RR-02",
    "RR-03",
    "RR-04",
    "RR-05",
    "RR-06",
    "RR-07",
    "RR-08",
    "RR-09",
    "RR-10",
    "RR-11",
)

PENDIENTES_I4 = ("RR-01", "RR-02", "RR-03", "RR-04", "RR-05", "RR-06")
"""Reglas registradas en su orden pero **sin cuerpo en I-1**. Las llena I-4."""

IMPLEMENTADAS_I1 = ("RR-07", "RR-08", "RR-09", "RR-10")

SOLO_CONDICION = ("RR-11",)
"""Inalcanzable desde la lectura. Vive en la condicion de escritura."""


class PrecondicionAusente(Exception):
    """Falta un dato que en I-1 se da por presente.

    En I-1 el sembrado garantiza que el espacio y la unidad existen. Cuando no
    existen, la respuesta correcta es RR-02 o RR-01 — y esas son de I-4. Se
    levanta esta excepcion en vez de inventar un veredicto, porque un veredicto
    inventado aqui pasaria por bueno en el CI.
    """


def evaluar(
    solicitud: Solicitud, estado: EstadoLeido, instante_ref: datetime
) -> Veredicto:
    """Evalua en orden numerico y devuelve la PRIMERA regla violada."""
    if estado.parametros is None:
        raise PrecondicionAusente(
            f"el espacio {solicitud.espacio!r} no esta en el estado leido; "
            "RR-02 es de I-4 y aqui no se puede fabricar un veredicto"
        )
    if estado.unidad is None:
        raise PrecondicionAusente(
            f"la unidad {solicitud.unidad!r} no esta en el estado leido; "
            "RR-01 es de I-4 y aqui no se puede fabricar un veredicto"
        )

    # RR-01 .. RR-06 -> pendientes de I-4. Su hueco esta aqui, en su orden.

    # RR-07 · Cupo por unidad.
    # La lectura solo atribuye; quien decide es la condicion del contador dentro
    # de la transaccion. Que esten los dos no es duplicidad: sin la lectura no
    # se puede nombrar la regla antes de escribir; sin la condicion, dos
    # solicitudes simultaneas de la misma unidad en franjas distintas exceden el
    # cupo (K-05).
    if estado.cupo_consumido >= estado.parametros.cupo:
        return Veredicto.rechaza("RR-07")

    # RR-08 · Choque con reserva propia, aunque sea de otro espacio.
    for franja in solicitud.franjas:
        if franja in estado.agenda:
            return Veredicto.rechaza("RR-08", franja)

    # RR-09 · Bloqueo por mantenimiento. Antes que RR-10: una franja bloqueada
    # no debe informarse como "ocupada por otro residente".
    for franja in solicitud.franjas:
        ocupacion = estado.ocupacion.get(franja)
        if ocupacion is not None and ocupacion.tipo is TipoOcupacion.BLOQUEO:
            return Veredicto.rechaza("RR-09", franja)

    # RR-10 · Solapamiento con reserva confirmada.
    # Con franjas, el solapamiento en sus cuatro formas es coincidencia de
    # clave. La adyacencia no comparte clave, luego no choca.
    for franja in solicitud.franjas:
        ocupacion = estado.ocupacion.get(franja)
        if ocupacion is not None and ocupacion.tipo is TipoOcupacion.RESERVA:
            return Veredicto.rechaza("RR-10", franja)

    # Ninguna violada: el nucleo devuelve una INTENCION, no una confirmacion.
    return Veredicto.acepta(
        IntencionEscritura(
            solicitud=solicitud,
            franjas=solicitud.franjas,
            periodo_cupo=estado.parametros.periodo_de(solicitud.dia),
            tope_cupo=estado.parametros.cupo,
        )
    )


def menor_regla(*reglas: str | None) -> str | None:
    """La regla de menor numero entre varias violadas (RF-06).

    Se usa cuando la transaccion cancela por varias condiciones a la vez: gana
    la primera del orden, igual que en la lectura.
    """
    candidatas = [r for r in reglas if r]
    if not candidatas:
        return None
    return min(candidatas, key=lambda r: ORDEN_CREACION.index(r))
