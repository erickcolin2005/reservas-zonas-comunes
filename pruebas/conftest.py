"""Piezas comunes de las pruebas."""

from __future__ import annotations

import os
import pathlib
from datetime import datetime, timezone

import pytest

from reservas import config, sembrado
from reservas.adaptadores import dynamodb
from reservas.nucleo import tiempo

from .motor_local import SustitutoLocal

RAIZ = pathlib.Path(__file__).resolve().parent.parent
EVIDENCIA = RAIZ / "evidencia"


@pytest.fixture(scope="session")
def endpoint() -> str:
    """Arranca el sustituto local una vez para toda la sesion."""
    sustituto = SustitutoLocal()
    extremo = sustituto.arrancar()
    os.environ["RESERVAS_ENDPOINT"] = extremo
    yield extremo
    sustituto.parar()


@pytest.fixture(scope="session")
def cliente_sesion(endpoint: str):
    return dynamodb.crear_cliente(endpoint)


@pytest.fixture()
def cliente(endpoint: str):
    """Un cliente por prueba. El endpoint ya esta fijado por la sesion."""
    return dynamodb.crear_cliente(endpoint)


@pytest.fixture(scope="session")
def t0() -> datetime:
    """El instante de referencia, derivado del reloj y nunca escrito a mano.

    Es la unica llamada al reloj de todo el arbol de pruebas, y ocurre aqui, en
    la frontera. De aqui para adentro el instante viaja inyectado (RF-07).

    De ambito de SESION, y no es una optimizacion: toda la corrida tiene que
    usar UN SOLO instante de referencia. Si cada prueba derivara el suyo, una
    ejecucion que cruzara la medianoche del ultimo dia del mes tendria dos T0
    distintos y sus resultados no serian comparables entre si.
    """
    return tiempo.t0_desde(datetime.now(timezone.utc))


@pytest.fixture()
def tabla(cliente, t0):
    """Tabla recien creada y sembrada. Los casos no acumulan estado entre si."""
    dynamodb.recrear_tabla(cliente, config.TABLA)
    conjunto = sembrado.sembrar(cliente, config.TABLA, t0)
    yield conjunto
    dynamodb.borrar_tabla(cliente, config.TABLA)


@pytest.fixture()
def adaptador(cliente):
    return dynamodb.AdaptadorDynamoDB(cliente, config.TABLA)


def guardar_evidencia(nombre: str, texto: str) -> pathlib.Path:
    """Deja constancia en disco de lo que se observo.

    Una tabla que solo publica aciertos no es un resultado, es un folleto: aqui
    se guarda lo que salio, incluidos los rojos provocados a proposito.
    """
    EVIDENCIA.mkdir(exist_ok=True)
    destino = EVIDENCIA / nombre
    destino.write_text(texto, encoding="utf-8")
    return destino
