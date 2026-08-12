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

PENDIENTES_I4 = ()
"""Vacio desde I-4. Hasta entonces contenia RR-01…RR-06, registradas en su orden
pero sin cuerpo. **El hueco se dejaba a la vista a proposito**, y esta tupla
existia para que una prueba pudiera afirmarlo en vez de confiarlo a un comentario.

Se conserva vacia, y no se borra, porque la prueba que la lee sigue teniendo
trabajo: comprueba que la union de las tuplas cubre el orden de creacion entero.
Si manana se anadiera una regla y nadie la implementara, esa prueba lo diria."""

IMPLEMENTADAS_I1 = ("RR-07", "RR-08", "RR-09", "RR-10")

IMPLEMENTADAS_I4 = ("RR-01", "RR-02", "RR-03", "RR-04", "RR-05", "RR-06")
"""Las seis del flujo de creacion que I-4 llena. Dos matices que el codigo de
`evaluar` explica y que conviene tener tambien aqui:

  - **RR-03 no comprueba la rejilla**: la impone la canonizacion, antes de que
    exista la Solicitud. El caso R-07 del banco muere en esa frontera.
  - **RR-04 no comprueba el cero**: `Solicitud` rechaza cero franjas al
    construirse. El caso R-11 muere alli.

Las dos son fronteras mas fuertes que una regla -no dependen de que nadie las
llame- pero **se declaran**, porque decir "RR-03 atrapa R-07" seria falso."""

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
    # RR-01 · Unidad valida y activa.
    # Inexistente e inactiva producen el MISMO rechazo, a proposito: el sistema
    # no confirma ni desmiente que la unidad exista (RF-17). Que las dos ramas
    # devuelvan la misma cadena no es pereza, es el requisito.
    if estado.unidad is None or not estado.unidad.activa:
        return Veredicto.rechaza("RR-01")

    # RR-02 · Espacio existente y habilitado.
    # Deshabilitado NO es lo mismo que en mantenimiento (RR-09): el primero no
    # admite ninguna reserva, el segundo solo las franjas bloqueadas.
    if estado.parametros is None or not estado.parametros.habilitado:
        return Veredicto.rechaza("RR-02")

    parametros = estado.parametros

    # RR-03 · Rejilla, ventana y medianoche.
    #
    # La REJILLA ya la impone la canonizacion: una solicitud fuera de rejilla no
    # llega a existir como Solicitud (modelo, "no hay clave aproximada"). El
    # caso R-07 del banco se cierra en esa frontera, no aqui, y **se declara**
    # en vez de fingir que esta regla lo atrapa.
    #
    # Lo que si se comprueba aqui: que TODAS las franjas caen dentro de la
    # ventana del espacio, y que la reserva no cruza la medianoche.
    ultima_hora = solicitud.inicio.hour + solicitud.n_franjas
    if solicitud.inicio.hour < parametros.apertura or ultima_hora > parametros.cierre:
        return Veredicto.rechaza("RR-03")
    if ultima_hora > 24:
        return Veredicto.rechaza("RR-03")

    # RR-04 · Duracion permitida, ambos limites inclusive.
    # Cero franjas tampoco llega hasta aqui: Solicitud lo rechaza al construirse.
    if not (
        parametros.duracion_minima <= solicitud.n_franjas <= parametros.duracion_maxima
    ):
        return Veredicto.rechaza("RR-04")

    # RR-05 · Antelacion minima, limite INCLUSIVO.
    # Va despues de RR-03 a proposito: el caso L-08 del banco es un limite de
    # antelacion exacto que cae FUERA de la ventana, y el banco declara que debe
    # informarse RR-03, no RR-05. El orden es lo que produce esa respuesta.
    horas_de_antelacion = (solicitud.inicio - instante_ref).total_seconds() / 3600.0
    if horas_de_antelacion < parametros.antelacion_minima_horas:
        return Veredicto.rechaza("RR-05")

    # RR-06 · Horizonte maximo, en dias de calendario y limite INCLUSIVO.
    # En dias y no en horas: el banco lo enuncia sobre la FECHA de inicio.
    dias_de_horizonte = (solicitud.inicio.date() - instante_ref.date()).days
    if dias_de_horizonte > parametros.horizonte_maximo_dias:
        return Veredicto.rechaza("RR-06")

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
