"""Caso de uso: reservar. Orquesta; no decide ninguna regla por su cuenta.

Camino de escritura (modelo-datos §5.0), con lo que I-1 tiene y lo que le falta:

    1. identidad PROBADA (token firmado)            -> I-6  (SEC-2, ADR-26)
    2. CONTADOR DE INTENTOS por identidad           -> I-6  (SEC-1, ADR-29)
    3. lecturas de estado, consistencia fuerte      -> I-1  aqui
    4. evaluacion pura RR-01..RR-10                 -> I-1  parcial (ver reglas)
    5. TRANSACCION CONDICIONAL                      -> I-1  aqui

**Los pasos 1 y 2 no existen todavia y su ausencia esta declarada, no
disimulada.** En I-1 la unidad llega como dato del llamador porque no hay borde
publico ni autorizador: nada de I-1 se expone a nadie.

Lo que si esta entero aqui es ADR-04, que es la decision que mas facil se
implementa mal:

    en cuanto una solicitud sufre un fallo de condicion o un conflicto sobre un
    item de FRANJA, queda marcada "en carrera"; a partir de ahi, cualquier
    rechazo suyo sobre esa franja es RR-11, jamas RR-10.

Sin esa marca, el reintento tras un conflicto vuelve a leer, ve la franja
ocupada y devuelve RR-10 a quien SI llego a la vez. Eso **esconde la carrera** y
puede dejar K-01 sin ningun RR-11, con lo que se declararia medicion fallida
cuando la carrera si ocurrio. La marca vive en el ambito de la solicitud y muere
con ella: no se persiste (ADR-25).
"""

from __future__ import annotations

import random
import time
import uuid
from datetime import datetime

from ..config import Reintentos
from ..desenlaces import Cubo, Desenlace
from ..nucleo import reglas
from ..nucleo.modelo import Franja, Solicitud, TipoOcupacion
from ..puertos import ClaseItem, RazonCancelacion, TipoResultado

REGLA_POR_CLASE = {
    ClaseItem.CUPO: "RR-07",
    ClaseItem.AGENDA: "RR-08",
    ClaseItem.FRANJA: "RR-11",
}


def reservar(
    solicitud: Solicitud,
    adaptador,
    instante_ref: datetime,
    token_solicitud: str | None = None,
    reintentos: Reintentos | None = None,
    aleatorio: random.Random | None = None,
) -> Desenlace:
    """Atiende una solicitud y devuelve su desenlace, ya en su cubo."""
    reintentos = reintentos or Reintentos()
    aleatorio = aleatorio or random.Random()
    token = token_solicitud or uuid.uuid4().hex
    id_reserva = uuid.uuid4().hex

    franjas_en_carrera: set[Franja] = set()
    t_inicio = time.perf_counter()
    t_escritura: float | None = None
    intentos = 0

    while True:
        intentos += 1
        estado = adaptador.leer_estado(solicitud)
        veredicto = reglas.evaluar(solicitud, estado, instante_ref)

        if not veredicto.aceptada:
            regla = veredicto.regla
            # La marca pegajosa. Es lo unico que impide que un reintento
            # convierta un RR-11 legitimo en un RR-10 y esconda la carrera.
            if regla == "RR-10" and veredicto.franja_culpable in franjas_en_carrera:
                regla = "RR-11"
            return _fin(
                Cubo.RECHAZADA_REGLA,
                solicitud,
                regla=regla,
                t_inicio=t_inicio,
                t_escritura=t_escritura,
                intentos=intentos,
            )

        if t_escritura is None:
            t_escritura = time.perf_counter()
        resultado = adaptador.intentar_confirmar(veredicto.intencion, token, id_reserva)

        if resultado.tipo is TipoResultado.ACEPTADA:
            return _fin(
                Cubo.CONFIRMADA,
                solicitud,
                id_reserva=resultado.id_reserva,
                t_inicio=t_inicio,
                t_escritura=t_escritura,
                intentos=intentos,
            )

        if resultado.tipo is TipoResultado.CAPACIDAD:
            # No hay constancia de que llegara a disputar: no cuenta como
            # competidora efectiva (D-P4-08 punto 2).
            return _fin(
                Cubo.SYS_CAPACIDAD,
                solicitud,
                t_inicio=t_inicio,
                t_escritura=t_escritura,
                intentos=intentos,
                detalle=resultado.detalle,
            )

        _marcar_en_carrera(resultado.items_en_fallo, franjas_en_carrera)

        if resultado.tipo is TipoResultado.CONDICION_INCUMPLIDA:
            # ADR-25 · idempotencia. Si el item del hueco lleva MI token, la
            # transaccion ya se aplico antes y esta es una repeticion: no es un
            # rechazo, es la misma confirmacion.
            if _lleva_mi_token(resultado.items_en_fallo, token):
                return _fin(
                    Cubo.CONFIRMADA,
                    solicitud,
                    id_reserva=id_reserva,
                    t_inicio=t_inicio,
                    t_escritura=t_escritura,
                    intentos=intentos,
                    detalle="idempotencia por token de solicitud (ADR-25)",
                )
            return _fin(
                Cubo.RECHAZADA_REGLA,
                solicitud,
                regla=_atribuir(resultado.items_en_fallo),
                t_inicio=t_inicio,
                t_escritura=t_escritura,
                intentos=intentos,
                detalle=resultado.detalle,
            )

        # Conflicto entre transacciones (N-f). Es lo unico que se reintenta.
        if intentos > reintentos.maximo:
            break
        espera = min(
            reintentos.espera_maxima_ms,
            reintentos.espera_base_ms * (2 ** (intentos - 1)),
        )
        # Aleatoria a proposito: una espera fija volveria a sincronizar a los
        # perdedores y produciria una segunda tanda de conflictos identica.
        time.sleep(aleatorio.uniform(0, espera) / 1000.0)

    # Se agotaron los reintentos. Una sola lectura, solo en el camino perdedor.
    ocupacion = adaptador.leer_ocupacion(solicitud.franjas, solicitud.espacio)
    tomada = any(f in ocupacion for f in solicitud.franjas)
    if tomada:
        bloqueada = any(
            ocupacion[f].tipo is TipoOcupacion.BLOQUEO
            for f in solicitud.franjas
            if f in ocupacion
        )
        return _fin(
            Cubo.RECHAZADA_REGLA,
            solicitud,
            regla="RR-09" if bloqueada else "RR-11",
            t_inicio=t_inicio,
            t_escritura=t_escritura,
            intentos=intentos,
        )
    # La franja sigue libre y nadie gano. Devolver RR-11 seria mentir con
    # precision: diria "alguien se te adelanto" cuando nadie lo hizo.
    return _fin(
        Cubo.SYS_CONTENCION,
        solicitud,
        t_inicio=t_inicio,
        t_escritura=t_escritura,
        intentos=intentos,
    )


def _marcar_en_carrera(items_en_fallo, franjas_en_carrera: set) -> None:
    for fallo in items_en_fallo:
        if fallo.clase is ClaseItem.FRANJA and fallo.franja is not None:
            if fallo.razon in (RazonCancelacion.CONDICION, RazonCancelacion.CONFLICTO):
                franjas_en_carrera.add(fallo.franja)


def _lleva_mi_token(items_en_fallo, token: str) -> bool:
    for fallo in items_en_fallo:
        if fallo.clase is not ClaseItem.FRANJA or not fallo.item_devuelto:
            continue
        if fallo.item_devuelto.get("token_solicitud", {}).get("S") == token:
            return True
    return False


def _atribuir(items_en_fallo) -> str:
    """De items en fallo a la regla que se informa. Gana la de menor numero."""
    candidatas: list[str] = []
    for fallo in items_en_fallo:
        if fallo.razon is not RazonCancelacion.CONDICION:
            continue
        if fallo.clase is ClaseItem.FRANJA:
            # RR-09 vs RR-11: se resuelve leyendo el tipo del item GANADOR.
            # Si el motor lo devuelve en el fallo, sale de ahi y no cuesta una
            # lectura extra. Funciona igual con las dos respuestas.
            item = fallo.item_devuelto or {}
            tipo = item.get("tipo", {}).get("S")
            candidatas.append("RR-09" if tipo == TipoOcupacion.BLOQUEO.value else "RR-11")
        else:
            candidatas.append(REGLA_POR_CLASE.get(fallo.clase, "RR-11"))
    return reglas.menor_regla(*candidatas) or "RR-11"


def _fin(
    cubo: Cubo,
    solicitud: Solicitud,
    regla: str | None = None,
    id_reserva: str | None = None,
    t_inicio: float | None = None,
    t_escritura: float | None = None,
    intentos: int = 1,
    detalle: str | None = None,
) -> Desenlace:
    return Desenlace(
        cubo=cubo,
        regla=regla,
        id_reserva=id_reserva,
        franjas=solicitud.franjas,
        unidad=solicitud.unidad,
        t_inicio_evaluacion=t_inicio,
        t_intento_escritura=t_escritura,
        t_fin=time.perf_counter(),
        intentos_internos=intentos,
        detalle=detalle,
    )
