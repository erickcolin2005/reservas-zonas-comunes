"""Pruebas propias de la canonizacion de la clave.

Por que este fichero existe y por que es el mas importante despues de los casos
K: **es donde C1 puede fallar sin que ninguna regla se viole y sin que ninguna
prueba de reglas lo note.**

El motor garantiza que dos escrituras sobre la misma clave colisionan. No
garantiza que dos solicitudes por el mismo hueco produzcan la misma clave. Si
una normaliza en local y otra en UTC, salen dos claves, la condicion no
colisiona, y hay dos reservas del mismo hueco. **Todas las reglas se cumplen. El
banco entero sale en verde. Y el sabado hay dos fiestas en el salon.**

Falso verde de la familia del fallo fatal n.o 1, en el lugar mas caro del
proyecto.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import date, datetime, timedelta, timezone

import pytest

from reservas.nucleo import claves, tiempo
from reservas.nucleo.tiempo import FueraDeRejilla, InstanteAmbiguo

RAIZ_FUENTES = pathlib.Path(__file__).resolve().parent.parent / "reservas"


# ---------------------------------------------------------------------------
# Regla 1 · zona horaria fija, sin horario de verano
# ---------------------------------------------------------------------------


def test_la_zona_no_cambia_de_desplazamiento_en_todo_el_ano():
    """Sin horario de verano. Un salto de hora seria un salto de clave.

    Si la zona tuviera horario de verano, la misma hora de pared se
    corresponderia con dos instantes distintos el dia del cambio, y el hueco
    dejaria de tener un nombre unico.
    """
    desplazamientos = {
        tiempo.instante_local(2026, mes, 15, 12).utcoffset() for mes in range(1, 13)
    }
    assert desplazamientos == {timedelta(hours=-5)}


def test_la_clave_se_construye_en_hora_local_y_no_en_utc():
    """La clave en hora LOCAL. Es la regla 1 y decide todo lo demas.

    A las 22:00 del 7 de septiembre en Bogota son las 03:00 del 8 en UTC. Si la
    clave se construyera en UTC, la reserva de las 22:00 aterrizaria en el dia
    siguiente y a otra hora — y dos implementaciones que difieran en esto no
    colisionan nunca.
    """
    local = tiempo.canonizar_inicio("2026-09-07T22:00")
    assert (local.date(), local.hour) == (date(2026, 9, 7), 22)

    en_utc = local.astimezone(timezone.utc)
    assert (en_utc.date(), en_utc.hour) == (date(2026, 9, 8), 3)

    clave_correcta = (
        claves.pk_hueco("E-SAL", local.date()),
        claves.sk_hueco(local.hour),
    )
    clave_si_alguien_normalizara_en_utc = (
        claves.pk_hueco("E-SAL", en_utc.date()),
        claves.sk_hueco(en_utc.hour),
    )
    # Esta es la desigualdad que hace peligroso el asunto: son dos claves para
    # el mismo hueco. La canonizacion existe para que solo se produzca la
    # primera, siempre, desde cualquier punto de entrada.
    assert clave_correcta != clave_si_alguien_normalizara_en_utc
    assert clave_correcta == ("ESP#E-SAL#DIA#2026-09-07", "FRANJA#22")


@pytest.mark.parametrize(
    "entrada",
    [
        "2026-09-07T10:00",  # local, sin segundos
        "2026-09-07T10:00:00",  # local, con segundos
        "2026-09-07 10:00:00",  # separador de espacio
        "2026-09-07T10:00:00-05:00",  # local, con desplazamiento explicito
        "2026-09-07T15:00:00Z",  # el MISMO instante, expresado en UTC
        "2026-09-07T15:00:00+00:00",  # ídem, otra notacion
        "2026-09-07T17:00:00+02:00",  # ídem, desde otro huso
        datetime(2026, 9, 7, 10, 0, tzinfo=tiempo.ZONA),
        datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 7, 17, 0, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_todas_las_formas_del_mismo_hueco_dan_la_misma_clave(entrada):
    """Siete notaciones, tres husos, dos tipos. Un solo hueco, una sola clave.

    Es la propiedad entera: *dos solicitudes por el mismo hueco real producen la
    misma clave*. Sin ella, el motor no tiene sobre que colisionar.
    """
    momento = tiempo.canonizar_inicio(entrada)
    assert (
        claves.pk_hueco("E-CAN", momento.date()),
        claves.sk_hueco(momento.hour),
    ) == ("ESP#E-CAN#DIA#2026-09-07", "FRANJA#10")


def test_huecos_distintos_dan_claves_distintas():
    """La otra mitad: dos huecos distintos no pueden compartir clave.

    Si la compartieran, dos reservas que no compiten se estorbarian — el sistema
    seria correcto y a la vez inutil.
    """
    generadas = {
        (claves.pk_hueco(espacio, date(2026, 9, dia)), claves.sk_hueco(hora))
        for espacio in ("E-SAL", "E-BBQ", "E-CAN")
        for dia in (7, 8, 17)
        for hora in (9, 10, 19)
    }
    assert len(generadas) == 3 * 3 * 3


# ---------------------------------------------------------------------------
# Regla 2 · formato fijo de ancho fijo
# ---------------------------------------------------------------------------


def test_la_fecha_y_la_hora_van_con_ancho_fijo():
    """`2026-9-7` y `2026-09-07` serian dos claves del mismo dia."""
    assert claves.pk_hueco("E-CAN", date(2026, 9, 7)) == "ESP#E-CAN#DIA#2026-09-07"
    assert claves.sk_hueco(9) == "FRANJA#09"
    assert claves.sk_hueco(19) == "FRANJA#19"
    assert len(claves.sk_hueco(9)) == len(claves.sk_hueco(19))


def test_una_hora_fuera_de_rango_no_produce_clave():
    with pytest.raises(ValueError):
        claves.sk_hueco(24)
    with pytest.raises(ValueError):
        claves.sk_hueco(-1)


# ---------------------------------------------------------------------------
# Regla 3 · la clave se construye en un unico lugar
# ---------------------------------------------------------------------------


def _literales_de_codigo(fuente: str):
    """Cadenas del codigo, EXCLUYENDO documentacion. Los comentarios no llegan.

    Se usa el arbol sintactico y no una busqueda de texto porque una busqueda de
    texto daria falsos positivos en cada docstring que explica el modelo — y una
    prueba que da falsos positivos acaba desactivada, que es como se pierden los
    guardias.
    """
    arbol = ast.parse(fuente)
    documentacion = set()
    for nodo in ast.walk(arbol):
        if isinstance(
            nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            cuerpo = getattr(nodo, "body", [])
            if (
                cuerpo
                and isinstance(cuerpo[0], ast.Expr)
                and isinstance(cuerpo[0].value, ast.Constant)
                and isinstance(cuerpo[0].value.value, str)
            ):
                documentacion.add(id(cuerpo[0].value))
    for nodo in ast.walk(arbol):
        if (
            isinstance(nodo, ast.Constant)
            and isinstance(nodo.value, str)
            and id(nodo) not in documentacion
        ):
            yield nodo.value


def test_ningun_otro_modulo_compone_claves():
    """El guardia de la regla 3. Sin el, la regla es solo un comentario.

    Practica heredada n.o 3: un numero en pantalla necesita un guardia que lo
    compare con la realidad. Aqui lo que necesita guardia es una invariante de
    diseno, y la realidad es el arbol de fuentes.
    """
    infractores = []
    for fichero in sorted(RAIZ_FUENTES.rglob("*.py")):
        if fichero.name == "claves.py":
            continue
        fuente = fichero.read_text(encoding="utf-8")
        for literal in _literales_de_codigo(fuente):
            for prefijo in claves.PREFIJOS:
                if prefijo in literal:
                    infractores.append(f"{fichero.name}: {literal!r} contiene {prefijo!r}")
    assert not infractores, (
        "estos modulos componen claves fuera de claves.py, y dos lugares que "
        "componen la misma clave acaban componiendola distinto:\n  "
        + "\n  ".join(infractores)
    )


# ---------------------------------------------------------------------------
# Regla 4 · fuera de rejilla no produce clave, ni siquiera aproximada
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada",
    [
        "2026-09-07T10:30",
        "2026-09-07T10:01",
        "2026-09-07T10:00:01",
        "2026-09-07T10:00:00.500000",
        datetime(2026, 9, 7, 10, 30, tzinfo=tiempo.ZONA),
        datetime(2026, 9, 7, 10, 0, 0, 1, tzinfo=tiempo.ZONA),
        # El caso que menos se ve venir: en origen esta en punto, y al
        # convertirlo a local cae a y media, porque el desplazamiento tiene
        # media hora. Estar en rejilla en el huso de origen no significa nada.
        "2026-09-07T10:00:00+05:30",
    ],
)
def test_fuera_de_rejilla_no_produce_ninguna_clave(entrada):
    """Una solicitud a las 14:30 no produce una clave aproximada: no produce
    ninguna. Redondear seria inventar un hueco que nadie pidio."""
    with pytest.raises(FueraDeRejilla):
        tiempo.canonizar_inicio(entrada)
    assert tiempo.en_rejilla(entrada) is False


def test_un_desplazamiento_a_media_hora_puede_caer_en_rejilla_local():
    """El caso simetrico del anterior, y por eso esta: la rejilla se comprueba
    DESPUES de convertir, nunca antes.

    `15:30+05:30` esta FUERA de rejilla en su huso de origen y, sin embargo, es
    exactamente las 05:00 locales, que si esta dentro. Comprobar la rejilla
    antes de convertir rechazaria una solicitud legitima; comprobarla despues es
    lo unico correcto.
    """
    momento = tiempo.canonizar_inicio("2026-09-07T15:30:00+05:30")
    assert (momento.date(), momento.hour) == (date(2026, 9, 7), 5)


# ---------------------------------------------------------------------------
# Regla 5 · ninguna clave sale del reloj del entorno
# ---------------------------------------------------------------------------


def test_un_datetime_sin_zona_se_rechaza_en_vez_de_suponer():
    """Un `datetime` ingenuo dentro del sistema es un defecto, no un rechazo de
    dominio. Convertirlo obligaria a suponer en que zona estaba, y suponer es
    exactamente como aparecen dos claves para un hueco."""
    with pytest.raises(InstanteAmbiguo):
        tiempo.canonizar_inicio(datetime(2026, 9, 7, 10, 0))
    with pytest.raises(InstanteAmbiguo):
        tiempo.a_local(datetime(2026, 9, 7, 10, 0))


@pytest.mark.parametrize(
    "referencia",
    [
        datetime(2026, 1, 15, 12, tzinfo=timezone.utc),
        datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
        datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2027, 2, 28, 6, 0, tzinfo=timezone.utc),
    ],
)
def test_t0_siempre_es_lunes_entre_el_1_y_el_7_y_esta_en_el_futuro(referencia):
    """T0 se deriva; no se escribe a mano. Un banco con fechas fijas se pudre en
    silencio: llega un dia en que todos sus casos de antelacion son pasado y el
    verde deja de significar nada."""
    t0 = tiempo.t0_desde(referencia)
    assert t0.weekday() == 0, "D+0 tiene que ser lunes: el cupo semanal depende"
    assert 1 <= t0.day <= 7, "D+0..D+13 tienen que caber en el mismo mes"
    assert (t0.hour, t0.minute) == (9, 0)
    assert t0 > referencia, "T0 tiene que estar en el futuro"
    assert t0.utcoffset() == timedelta(hours=-5)


def test_t0_es_estable_para_la_misma_referencia():
    """Determinismo: la misma referencia da el mismo T0, siempre."""
    referencia = datetime(2026, 8, 6, 16, 41, tzinfo=timezone.utc)
    assert tiempo.t0_desde(referencia) == tiempo.t0_desde(referencia)
    assert tiempo.t0_desde(referencia) == tiempo.instante_local(2026, 9, 7, 9)


# ---------------------------------------------------------------------------
# Periodos de cupo — se derivan de la fecha de inicio, que no puede ser dos
# ---------------------------------------------------------------------------


def test_el_periodo_semanal_va_de_lunes_a_domingo():
    """El domingo cierra la semana; el lunes abre otra. Es lo que hace que L-12
    —la misma unidad, misma hora, semana siguiente— sea confirmable."""
    lunes = date(2026, 9, 7)
    domingo = date(2026, 9, 13)
    lunes_siguiente = date(2026, 9, 14)
    assert tiempo.periodo_semanal(lunes) == tiempo.periodo_semanal(domingo)
    assert tiempo.periodo_semanal(lunes) != tiempo.periodo_semanal(lunes_siguiente)


def test_el_periodo_mensual_es_el_mes_calendario():
    assert tiempo.periodo_mensual(date(2026, 9, 1)) == "2026-09"
    assert tiempo.periodo_mensual(date(2026, 9, 30)) == "2026-09"
    assert tiempo.periodo_mensual(date(2026, 10, 1)) == "2026-10"


def test_la_clave_del_cupo_lleva_el_periodo():
    assert claves.sk_cupo("E-CAN", "2026-W37") == "CUPO#E-CAN#2026-W37"
    assert claves.sk_cupo("E-SAL", "2026-09") == "CUPO#E-SAL#2026-09"
