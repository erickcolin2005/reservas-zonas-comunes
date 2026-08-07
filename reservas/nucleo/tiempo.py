"""Canonizacion del tiempo — la parte que el motor NO cubre.

El motor garantiza que dos escrituras sobre la misma clave colisionan. No
garantiza que dos solicitudes por el mismo hueco produzcan la misma clave.
Si una solicitud normaliza la hora en local y otra en UTC, salen dos claves
distintas, la condicion no colisiona, y hay dos reservas del mismo hueco **sin
que ninguna regla se viole y sin que ninguna prueba de reglas lo note**.

Por eso este modulo es carga estructural y no higiene, y por eso tiene pruebas
propias (modelo-datos.md §4.3).

Las cinco reglas de §4.3, y donde vive cada una:

  1. Zona horaria fija America/Bogota, sin horario de verano. La clave en hora
     LOCAL, nunca en UTC.                                    -> ZONA, a_local()
  2. Fecha y hora con formato fijo de ancho fijo.             -> claves.py
  3. La clave se construye en un unico lugar del nucleo.      -> claves.py
  4. Se rechaza si no cae en la rejilla ANTES de construir
     ninguna clave. Una solicitud a las 14:30 no produce una
     clave "aproximada": no produce ninguna.                  -> canonizar_inicio()
  5. Ninguna clave se deriva del reloj del entorno.           -> este modulo no
     llama a datetime.now() en ningun punto del camino de la clave.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

# ---------------------------------------------------------------------------
# Regla 1 — la zona horaria
# ---------------------------------------------------------------------------

# America/Bogota es UTC-05:00 y **no aplica horario de verano**. Se expresa como
# un desplazamiento fijo a proposito, y no con zoneinfo, por dos motivos:
#
#   (a) El dominio lo exige asi: "America/Bogota, SIN horario de verano"
#       (banco §1). Un desplazamiento fijo no puede saltar una hora nunca.
#   (b) zoneinfo depende de la base de datos de zonas del sistema operativo, que
#       no es la misma en la maquina de desarrollo, en el contenedor del CI y en
#       la funcion desplegada. Tres bases de datos distintas son tres
#       oportunidades de producir dos claves para el mismo hueco.
#
# Lo que se pierde diciendolo en voz alta: si algun dia Colombia adoptara
# horario de verano, este valor deja de ser correcto y hay que cambiarlo aqui.
# Es un unico sitio, y esa es la propiedad que se buscaba.
ZONA = timezone(timedelta(hours=-5), "America/Bogota")

MINUTOS_POR_FRANJA = 60
"""La rejilla. No es un parametro: es carga estructural.

Sin rejilla el hueco no puede ser una clave, y sin clave no hay escritura
condicional que valga (arquitectura §16.3). Cambiar este valor no es rehacer el
modelo: es cambiar de mecanismo.
"""


class FueraDeRejilla(Exception):
    """El instante no cae en la rejilla de 60 minutos.

    Se lanza ANTES de construir ninguna clave (regla 4). Quien lo captura lo
    traduce a un rechazo RR-03; este modulo no conoce identificadores de regla.
    """


class InstanteAmbiguo(Exception):
    """Se recibio un `datetime` sin zona horaria.

    No es un rechazo de dominio: es un defecto de programacion. Un `datetime`
    ingenuo dentro del sistema significa que alguien perdio por el camino la
    informacion que decide la clave.
    """


_ISO_SIN_DESPLAZAMIENTO = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$"
)


def a_local(momento: datetime) -> datetime:
    """Lleva un instante con zona a la hora local del dominio.

    Rechaza los `datetime` ingenuos. Es deliberado: convertir un ingenuo
    obligaria a suponer en que zona estaba, y suponer es exactamente como
    aparecen dos claves para un hueco.
    """
    if momento.tzinfo is None or momento.tzinfo.utcoffset(momento) is None:
        raise InstanteAmbiguo(
            "datetime sin zona horaria: no se puede canonizar sin suponer, "
            "y suponer es lo que produce dos claves para el mismo hueco"
        )
    return momento.astimezone(ZONA)


def canonizar_inicio(valor: str | datetime) -> datetime:
    """Unico punto de entrada del tiempo al nucleo.

    Acepta:
      - `str` en ISO-8601. **Sin desplazamiento se interpreta como hora local**,
        porque eso es lo que declara el contrato de API (`inicio`: "fecha y hora
        LOCAL alineada a la rejilla de 60 min"). Con desplazamiento se convierte.
      - `datetime` **con zona**. Se convierte a local.

    Devuelve un `datetime` local, alineado a la rejilla, con segundos y
    microsegundos a cero.

    Lanza `FueraDeRejilla` si no cae en la rejilla — y en ese caso **no se
    construye ninguna clave** (regla 4 de §4.3).
    """
    if isinstance(valor, str):
        texto = valor.strip()
        if _ISO_SIN_DESPLAZAMIENTO.match(texto):
            # Sin desplazamiento: el contrato dice que es hora local.
            momento = datetime.fromisoformat(texto).replace(tzinfo=ZONA)
        else:
            try:
                momento = datetime.fromisoformat(texto.replace("Z", "+00:00"))
            except ValueError as error:
                raise FueraDeRejilla(f"instante no interpretable: {valor!r}") from error
            if momento.tzinfo is None:
                raise FueraDeRejilla(f"instante no interpretable: {valor!r}")
            momento = a_local(momento)
    elif isinstance(valor, datetime):
        momento = a_local(valor)
    else:
        raise TypeError(f"tipo no admitido para un instante: {type(valor).__name__}")

    if (
        momento.minute != 0
        or momento.second != 0
        or momento.microsecond != 0
        or MINUTOS_POR_FRANJA != 60
    ):
        raise FueraDeRejilla(
            f"{momento.isoformat()} no cae en la rejilla de "
            f"{MINUTOS_POR_FRANJA} minutos"
        )
    return momento


def en_rejilla(valor: str | datetime) -> bool:
    """Version sin excepcion de `canonizar_inicio`, para quien solo pregunta."""
    try:
        canonizar_inicio(valor)
    except (FueraDeRejilla, InstanteAmbiguo, TypeError):
        return False
    return True


def instante_local(
    anio: int, mes: int, dia: int, hora: int = 0, minuto: int = 0
) -> datetime:
    """Construye un instante local. Util para pruebas y para el sembrado."""
    return datetime(anio, mes, dia, hora, minuto, tzinfo=ZONA)


# ---------------------------------------------------------------------------
# Regla 5 — ningun instante sale del reloj del entorno por su cuenta
# ---------------------------------------------------------------------------


def t0_desde(referencia: datetime) -> datetime:
    """T0 — el instante de referencia del banco, derivado y nunca escrito a mano.

    T0 = **el primer lunes del mes calendario siguiente al de la referencia, a
    las 09:00 hora local** (banco §1).

    Tres propiedades que una fecha arbitraria no da:
      (a) siempre es lunes, luego los casos de cupo semanal son deterministas;
      (b) cae entre el dia 1 y el 7, luego D+0..D+13 estan garantizados en el
          mismo mes calendario y los de cupo mensual tambien son deterministas;
      (c) siempre esta en el futuro, luego los casos de antelacion son validos.

    `referencia` tiene que venir de fuera. Este modulo no llama al reloj: quien
    quiera "ahora" lo pide a su adaptador y lo inyecta (RF-07, §4.3 regla 5).
    """
    local = a_local(referencia)
    if local.month == 12:
        primero = date(local.year + 1, 1, 1)
    else:
        primero = date(local.year, local.month + 1, 1)
    # weekday(): lunes = 0
    primer_lunes = primero + timedelta(days=(7 - primero.weekday()) % 7)
    return datetime.combine(primer_lunes, time(9, 0), tzinfo=ZONA)


def dia_mas(t0: datetime, n: int) -> date:
    """D+n — el dia T0 + n dias. D+0 es siempre lunes."""
    return (t0 + timedelta(days=n)).date()


def instante_mas(t0: datetime, dias: int, hora: int) -> datetime:
    """El instante local del dia D+`dias` a la hora en punto `hora`."""
    return datetime.combine(dia_mas(t0, dias), time(hora, 0), tzinfo=ZONA)


def periodo_mensual(dia: date) -> str:
    """Periodo de cupo mensual: `AAAA-MM`."""
    return f"{dia.year:04d}-{dia.month:02d}"


def periodo_semanal(dia: date) -> str:
    """Periodo de cupo semanal, lunes a domingo: `AAAA-Wnn`.

    La semana ISO empieza en lunes, que es exactamente lo que el banco pide.
    """
    anio_iso, semana_iso, _ = dia.isocalendar()
    return f"{anio_iso:04d}-W{semana_iso:02d}"


def utc_desde(momento: datetime) -> int:
    """Segundos desde la epoca. Solo para el atributo de expiracion (`ttl`)."""
    return int(a_local(momento).astimezone(timezone.utc).timestamp())
