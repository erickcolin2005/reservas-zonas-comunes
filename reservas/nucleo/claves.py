"""El unico lugar del sistema donde se compone una clave.

Regla 3 de la canonizacion (modelo-datos.md §4.3): *la clave se construye en un
unico lugar del nucleo y nadie mas la compone*.

Esa regla no se sostiene sola: la sostiene la prueba
`pruebas/test_canonizacion.py::test_ningun_otro_modulo_compone_claves`, que
recorre el arbol de fuentes y falla si algun otro fichero escribe uno de los
prefijos. Es el guardia que hace verdadera la afirmacion, porque una regla que
solo esta escrita en un comentario se incumple sin que nadie se entere.

Formato: ancho fijo siempre (regla 2). `AAAA-MM-DD` y `HH` de dos digitos.
Sin ancho fijo, `2026-9-7` y `2026-09-07` serian dos claves del mismo dia.
"""

from __future__ import annotations

from datetime import date

# Prefijos. Viven aqui y solo aqui.
_ESPACIO = "ESP#"
_UNIDAD = "UNI#"
_IDENTIDAD = "IDT#"
_DIA = "DIA#"
_FRANJA = "FRANJA#"
_AGENDA = "AGENDA#"
_CUPO = "CUPO#"
_RESERVA = "RES#"
_META = "META"


def _dia(valor: date) -> str:
    """`AAAA-MM-DD`, siempre diez caracteres."""
    return f"{valor.year:04d}-{valor.month:02d}-{valor.day:02d}"


def _hora(valor: int) -> str:
    """`HH`, siempre dos digitos."""
    if not 0 <= valor <= 23:
        raise ValueError(f"hora fuera de rango: {valor}")
    return f"{valor:02d}"


# --- El hueco. Es EL item: si existe, la franja esta tomada. ----------------


def pk_hueco(espacio: str, dia: date) -> str:
    return f"{_ESPACIO}{espacio}{'#'}{_DIA}{_dia(dia)}"


def sk_hueco(hora: int) -> str:
    return f"{_FRANJA}{_hora(hora)}"


# --- Espacio y unidad (catalogo) -------------------------------------------


def pk_espacio(espacio: str) -> str:
    return f"{_ESPACIO}{espacio}"


def pk_unidad(unidad: str) -> str:
    return f"{_UNIDAD}{unidad}"


def sk_meta() -> str:
    return _META


# --- Agenda de la unidad (RR-08) -------------------------------------------


def pk_agenda(unidad: str, dia: date) -> str:
    return f"{_UNIDAD}{unidad}{'#'}{_DIA}{_dia(dia)}"


def sk_agenda(hora: int) -> str:
    return f"{_AGENDA}{_hora(hora)}"


# --- Contador de cupo (RR-07) ----------------------------------------------


def sk_cupo(espacio: str, periodo: str) -> str:
    return f"{_CUPO}{espacio}#{periodo}"


# --- Cabecera de reserva ----------------------------------------------------


def sk_reserva(dia: date, id_reserva: str) -> str:
    return f"{_RESERVA}{_dia(dia)}#{id_reserva}"


# --- Contador de intentos (SEC-1) ------------------------------------------
# El contador de intentos NO se implementa en I-1: es del incremento I-6.
# Su forma de clave se declara aqui para que cuando llegue no la componga otro
# modulo y se rompa la regla 3. Ver `reservas/puertos.py`.


def pk_identidad(identidad: str) -> str:
    return f"{_IDENTIDAD}{identidad}"


# --- Lo que necesita el guardia --------------------------------------------

PREFIJOS = (_ESPACIO, _UNIDAD, _IDENTIDAD, _DIA, _FRANJA, _AGENDA, _CUPO, _RESERVA)
"""Los prefijos que ningun otro modulo puede escribir. Lo comprueba una prueba."""
