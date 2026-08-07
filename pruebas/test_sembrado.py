"""Datos sinteticos: que se siembra, cuanto, y que se niega a sembrar."""

from __future__ import annotations

import pytest

from reservas import config, sembrado
from reservas.nucleo import claves, tiempo

pytestmark = pytest.mark.motor


def test_el_sembrado_se_niega_a_producir_menos_de_50_de_rafaga(cliente, t0):
    """ADR-30 consecuencia d. Se atrapa donde se origina, no en la ejecucion del
    instrumento tres incrementos despues.

    Con menos de 50 unidades, el instrumento no puede lanzar 50 solicitudes
    simultaneas de identidades distintas y D-A deja de ser comprobable.
    """
    with pytest.raises(sembrado.SembradoInvalido):
        sembrado.sembrar(cliente, config.TABLA, t0, n_max_rafaga=49)


def test_hay_50_activas_una_inactiva_una_administracion_y_tres_espacios(tabla):
    conjunto = tabla
    assert len(conjunto.rafaga) == 50
    assert conjunto.inactiva == "U-110"
    assert conjunto.administracion == "ADM-001"
    assert conjunto.espacios == ("E-SAL", "E-BBQ", "E-CAN")


def test_la_unidad_inactiva_no_esta_entre_las_activas(tabla):
    """El banco pide 50 ACTIVAS mas una inactiva. Si U-110 estuviera dentro de
    las 50, serian 49 activas y K-01 no tendria con que competir."""
    assert tabla.inactiva not in tabla.activas
    assert tabla.administracion not in tabla.activas
    assert len(set(tabla.activas)) == len(tabla.activas)


def test_la_administracion_y_la_inactiva_no_pertenecen_a_ningun_grupo_prestable(
    tabla, cliente
):
    """Un extrano con la identidad de administracion podria vaciar el calendario
    y arruinar la demo para el siguiente visitante. El argumento es funcional
    antes que de seguridad."""
    for identificador in (tabla.inactiva, tabla.administracion):
        item = cliente.get_item(
            TableName=config.TABLA,
            Key={
                "PK": {"S": claves.pk_unidad(identificador)},
                "SK": {"S": claves.sk_meta()},
            },
            ConsistentRead=True,
        )["Item"]
        assert item["grupo"]["S"] == sembrado.GRUPO_NINGUNO


def test_los_tres_espacios_difieren_en_todos_sus_parametros():
    """Si compartieran parametros, un sistema con los valores escritos fijos en
    el codigo pasaria el banco entero sin haber implementado una sola regla
    configurable. Los tres espacios son un guardia, no riqueza de dominio."""
    campos = (
        "apertura",
        "cierre",
        "duracion_minima",
        "duracion_maxima",
        "antelacion_minima_horas",
        "horizonte_maximo_dias",
        "cupo",
        "plazo_cancelacion_horas",
    )
    for campo in campos:
        valores = [getattr(e, campo) for e in sembrado.ESPACIOS]
        assert len(set(valores)) == len(valores), (
            f"dos espacios comparten {campo} = {valores}; deja de ser un guardia"
        )
    assert len({e.tipo_periodo for e in sembrado.ESPACIOS}) == 2


def test_los_parametros_llegan_al_nucleo_como_dato_leido_de_la_tabla(
    tabla, adaptador, t0
):
    """No como constante del codigo. Se comprueba leyendolos del motor."""
    from reservas.nucleo.modelo import Solicitud

    peticion = Solicitud("U-101", "E-CAN", tiempo.instante_mas(t0, 4, 10), 1)
    estado = adaptador.leer_estado(peticion)
    assert estado.parametros == sembrado.espacio("E-CAN")
    assert estado.unidad.activa is True
    assert estado.unidad.grupo == sembrado.GRUPO_RAFAGA


def test_el_sembrado_es_determinista(cliente, t0):
    """Mismos parametros, mismo resultado. Sin esto, dos corridas del banco no
    son comparables."""
    primero = sembrado.unidades_rafaga(50)
    segundo = sembrado.unidades_rafaga(50)
    assert primero == segundo
    assert primero[0] == "U-101"
    assert "U-110" not in primero


def test_nada_se_siembra_con_fechas_escritas_a_mano(tabla, t0):
    """Todo relativo a T0. Un banco con fechas fijas se pudre en silencio."""
    assert tabla.t0 == t0
    assert t0.weekday() == 0
    assert 1 <= t0.day <= 7


def test_el_codigo_se_niega_a_apuntar_al_motor_real():
    """El reloj de seis meses de la cuenta no puede arrancar por un error de
    configuracion. Cruzar la puerta de AWS es I-2, y tiene su propio disparador:
    que I-1 este en verde contra el sustituto local."""
    from reservas.adaptadores.dynamodb import ExtremoNoPermitido, crear_cliente

    with pytest.raises(ExtremoNoPermitido):
        crear_cliente("https://dynamodb.us-east-1.amazonaws.com")
