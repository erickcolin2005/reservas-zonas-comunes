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

# ---------------------------------------------------------------------------
# LA EVIDENCIA SE ESCRIBE SOLO CUANDO SE PIDE
# ---------------------------------------------------------------------------
# Los ficheros de `evidencia/` estan en el repositorio a proposito: son lo que
# lee quien no va a ejecutar nada. Pero se regeneran en cada corrida, y las
# cifras de tiempo -dispersion de la barrera, duracion de cada pytest- cambian
# siempre. Sin esta puerta, correr la suite en local deja un diff de
# milisegundos que **parece un cambio de resultado y no lo es**; y un arbol
# sucio despues de cada corrida acaba con alguien haciendo `git add -A` y
# publicando como constancia lo que salio en su portatil.
#
# Lo que se protege no es el disco: es que el dia que un veredicto SI cambie,
# el diff lo diga en vez de esconderlo entre decimas de segundo.
#
# El CI la pide -`RESERVAS_EVIDENCIA=1` en el flujo- porque alli la constancia
# es el producto: se sube como artefacto en cada push, tambien cuando falla.
#
# Solo ese valor exacto, igual que la llave del motor real (D-P4-19): asi la
# puerta no se abre por una variable heredada del entorno con cualquier valor.
ESCRIBIR_EVIDENCIA = os.environ.get("RESERVAS_EVIDENCIA") == "1"

# Para que la constancia diga donde corrio y no lo suponga. La sonda V-2a ya
# cometio este error una vez: etiquetaba su informe como "sustituto local"
# corriera donde corriera.
EN_EL_CI = os.environ.get("GITHUB_ACTIONS") == "true"


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


def guardar_evidencia(nombre: str, texto: str) -> pathlib.Path | None:
    """Deja constancia en disco de lo que se observo, si se pidio escribirla.

    Una tabla que solo publica aciertos no es un resultado, es un folleto: aqui
    se guarda lo que salio, incluidos los rojos provocados a proposito.

    Devuelve `None` cuando no se pidio. El texto se compone igual —la puerta no
    ahorra trabajo, evita pisar el fichero del repositorio— y las pruebas que
    lo usan no dependen del retorno.
    """
    if not ESCRIBIR_EVIDENCIA:
        return None
    EVIDENCIA.mkdir(exist_ok=True)
    destino = EVIDENCIA / nombre
    destino.write_text(texto, encoding="utf-8")
    return destino
