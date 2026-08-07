"""Datos sinteticos: generados, nunca anonimizados a partir de nada real.

Determinista, versionado, y **relativo a T0**: ninguna fecha escrita a mano. Un
banco con fechas fijas se pudre en silencio — llega un dia en que todos sus casos
de antelacion son pasado y el verde deja de significar nada (RNF-17).

Que siembra, y por que exactamente eso (modelo-datos §11):

  50 unidades activas del grupo RAFAGA   con menos, el instrumento no puede
                                         lanzar 50 solicitudes simultaneas y
                                         D-A deja de ser comprobable.
  1 unidad inactiva (U-110)              R-02: distinguir inexistente de
                                         inactiva sin revelar cual.
  1 identidad de administracion          RF-22, RF-23. NO prestable: un extrano
                                         con ella podria vaciar el calendario.
  3 espacios que difieren en TODO        si compartieran parametros, un sistema
                                         con los valores escritos fijos en el
                                         codigo pasaria el banco entero sin
                                         haber implementado una sola regla
                                         configurable.

**Comprobacion propia del sembrado** (ADR-30 consecuencia d): falla si
`n_max_rafaga < 50`. Se atrapa donde se origina, no en la ejecucion del
instrumento tres incrementos despues.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .adaptadores.dynamodb import BOOL, N, S
from .nucleo import claves
from .nucleo.modelo import ParametrosEspacio, TipoPeriodo

MINIMO_RAFAGA = 50
"""Minimo del banco §2 y del hallazgo 2. No es una preferencia."""

UNIDAD_INACTIVA = "U-110"
ADMINISTRACION = "ADM-001"

GRUPO_RAFAGA = "RAFAGA"
GRUPO_SESION = "SESION"
GRUPO_NINGUNO = "NINGUNO"
"""La administracion y la unidad inactiva no pertenecen a ningun grupo
prestable (modelo-datos §11)."""


class SembradoInvalido(Exception):
    """El sembrado se niega a producir un conjunto que rompe el instrumento."""


# --- El catalogo de espacios (banco §2) -------------------------------------
# Los valores son ASUMIDOS por `analyst-agent` y estan marcados VALIDAR-ERICK.
# Viven aqui, en el sembrado, y llegan al nucleo como DATO leido de
# `ESP#.../META`. Nunca como constante del codigo: si estuvieran fijos en el
# codigo, tres espacios distintos no probarian nada.

ESPACIOS: tuple[ParametrosEspacio, ...] = (
    ParametrosEspacio(
        id="E-SAL",
        nombre="Salon social",
        apertura=9,
        cierre=23,
        duracion_minima=4,
        duracion_maxima=6,
        antelacion_minima_horas=72,
        horizonte_maximo_dias=90,
        cupo=1,
        tipo_periodo=TipoPeriodo.MENSUAL,
        plazo_cancelacion_horas=48,
    ),
    ParametrosEspacio(
        id="E-BBQ",
        nombre="Zona BBQ",
        apertura=10,
        cierre=22,
        duracion_minima=3,
        duracion_maxima=4,
        antelacion_minima_horas=24,
        horizonte_maximo_dias=30,
        cupo=2,
        tipo_periodo=TipoPeriodo.MENSUAL,
        plazo_cancelacion_horas=12,
    ),
    ParametrosEspacio(
        id="E-CAN",
        nombre="Cancha multiple",
        apertura=6,
        cierre=21,
        duracion_minima=1,
        duracion_maxima=2,
        antelacion_minima_horas=2,
        horizonte_maximo_dias=7,
        cupo=3,
        tipo_periodo=TipoPeriodo.SEMANAL,
        plazo_cancelacion_horas=2,
    ),
)


@dataclass(frozen=True)
class Conjunto:
    """Lo que quedo sembrado. Se devuelve para que nadie lo tenga que adivinar."""

    rafaga: tuple[str, ...]
    sesion: tuple[str, ...]
    inactiva: str
    administracion: str
    espacios: tuple[str, ...]
    t0: datetime

    @property
    def activas(self) -> tuple[str, ...]:
        return self.rafaga + self.sesion


def unidades_rafaga(n: int) -> tuple[str, ...]:
    """`U-101`, `U-102`, ... saltando la inactiva `U-110`.

    Saltarla no es un detalle: el banco pide 50 unidades **activas** MAS una
    inactiva. Si U-110 estuviera dentro de las 50, serian 49 activas y K-01 no
    tendria con que competir.
    """
    salida: list[str] = []
    numero = 101
    while len(salida) < n:
        identificador = f"U-{numero}"
        if identificador != UNIDAD_INACTIVA:
            salida.append(identificador)
        numero += 1
    return tuple(salida)


def sembrar(
    cliente,
    tabla: str,
    t0: datetime,
    n_max_rafaga: int = MINIMO_RAFAGA,
    reserva_sesion: int = 0,
) -> Conjunto:
    """Siembra el catalogo. Determinista: mismos parametros, mismo resultado.

    `reserva_sesion` es el tamano del grupo de sesion (ADR-30). Su valor real es
    de `design-agent` y **no esta cerrado**; por defecto es 0 porque en I-1 no
    existe el dispensador ni hay navegador que pida una identidad. Poner aqui un
    numero inventado lo haria pasar por acordado.
    """
    if n_max_rafaga < MINIMO_RAFAGA:
        raise SembradoInvalido(
            f"n_max_rafaga = {n_max_rafaga} < {MINIMO_RAFAGA}. Con menos de "
            f"{MINIMO_RAFAGA} unidades el instrumento no puede lanzar 50 "
            "solicitudes simultaneas y D-A deja de ser comprobable."
        )

    total = n_max_rafaga + reserva_sesion
    todas = unidades_rafaga(total)
    rafaga = todas[:n_max_rafaga]
    sesion = todas[n_max_rafaga:]

    peticiones: list[dict] = []

    for espacio in ESPACIOS:
        peticiones.append(
            {
                "PutRequest": {
                    "Item": {
                        "PK": S(claves.pk_espacio(espacio.id)),
                        "SK": S(claves.sk_meta()),
                        "nombre": S(espacio.nombre),
                        "apertura": N(espacio.apertura),
                        "cierre": N(espacio.cierre),
                        "duracion_minima": N(espacio.duracion_minima),
                        "duracion_maxima": N(espacio.duracion_maxima),
                        "antelacion_minima_horas": N(espacio.antelacion_minima_horas),
                        "horizonte_maximo_dias": N(espacio.horizonte_maximo_dias),
                        "cupo": N(espacio.cupo),
                        "tipo_periodo": S(espacio.tipo_periodo.value),
                        "plazo_cancelacion_horas": N(espacio.plazo_cancelacion_horas),
                        "habilitado": BOOL(espacio.habilitado),
                    }
                }
            }
        )

    for unidad in rafaga:
        peticiones.append(_unidad(unidad, activa=True, grupo=GRUPO_RAFAGA))
    for unidad in sesion:
        peticiones.append(_unidad(unidad, activa=True, grupo=GRUPO_SESION))
    peticiones.append(_unidad(UNIDAD_INACTIVA, activa=False, grupo=GRUPO_NINGUNO))
    peticiones.append(_unidad(ADMINISTRACION, activa=True, grupo=GRUPO_NINGUNO))

    for lote in _en_lotes(peticiones, 25):
        pendientes = {tabla: lote}
        while pendientes:
            respuesta = cliente.batch_write_item(RequestItems=pendientes)
            pendientes = respuesta.get("UnprocessedItems") or {}

    return Conjunto(
        rafaga=rafaga,
        sesion=sesion,
        inactiva=UNIDAD_INACTIVA,
        administracion=ADMINISTRACION,
        espacios=tuple(e.id for e in ESPACIOS),
        t0=t0,
    )


def _unidad(identificador: str, activa: bool, grupo: str) -> dict:
    return {
        "PutRequest": {
            "Item": {
                "PK": S(claves.pk_unidad(identificador)),
                "SK": S(claves.sk_meta()),
                "activa": BOOL(activa),
                "grupo": S(grupo),
            }
        }
    }


def _en_lotes(secuencia, tamano):
    for i in range(0, len(secuencia), tamano):
        yield secuencia[i : i + tamano]


def espacio(identificador: str) -> ParametrosEspacio:
    for e in ESPACIOS:
        if e.id == identificador:
            return e
    raise KeyError(identificador)
