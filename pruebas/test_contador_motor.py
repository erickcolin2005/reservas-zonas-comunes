"""SEC-1 contra el motor: **los mismos casos, la otra implementacion.**

Esto es lo que convierte «hay un contador persistente» en «el limite que se
prueba es el limite que actua». Sin este fichero, `ContadorIntentosDynamoDB`
seria codigo que nadie ha visto comportarse, desplegado en el sitio donde el
control tiene que aguantar cincuenta solicitudes a la vez.

Y hay una parte que **solo** se puede comprobar aqui: que el contador aguanta la
concurrencia. La version en memoria no puede fallar por eso; la de la tabla si,
y por eso la ultima prueba de este fichero no tiene equivalente en el otro.
"""

from __future__ import annotations

import concurrent.futures
import threading

import pytest

from reservas import config
from reservas.adaptadores.contadores import ContadorIntentosDynamoDB
from reservas.seguridad.contador import TasaExcedida

from .casos_contador import AHORA, CASOS, RESERVAR, VENTANA


@pytest.fixture()
def fabrica(cliente, tabla):
    """Construye contadores contra el sustituto local, sobre tabla limpia."""

    def crear(tope=3, ventana=VENTANA):
        return ContadorIntentosDynamoDB(
            cliente, ventana=ventana, tope=tope, tabla=config.TABLA
        )

    return crear


@pytest.mark.parametrize("nombre", sorted(CASOS))
def test_caso_compartido(nombre, fabrica):
    """El mismo caso que corre en memoria, ahora contra la tabla.

    Si alguno se comporta distinto, es que local y desplegado cuentan distinto —
    y entonces todo lo que se midio en local sobre el limite de tasa no dice
    nada de lo que pasa desplegado.
    """
    CASOS[nombre](fabrica)


def test_el_tope_aguanta_cincuenta_intentos_a_la_vez(fabrica):
    """**La prueba que solo existe de este lado.**

    Un contador que lee, comprueba y despues escribe pasa todos los casos de
    arriba y falla exactamente aqui: entre la lectura y la escritura caben las
    otras cuarenta y nueve. Y este control existe para el momento en que
    cincuenta llegan a la vez — un limite que se cae bajo carga no es un limite.

    Se exige que confirmen **exactamente** `tope`, ni una mas. Con «como mucho
    tope» pasaria tambien un contador que rechazara todo.
    """
    tope = 5
    cont = fabrica(tope=tope)
    barrera = threading.Barrier(50)
    resultados: list[str] = []
    cerrojo = threading.Lock()

    def intentar(_):
        barrera.wait()  # sin barrera el bucle produce una fila, no una tanda
        try:
            cont.registrar("U-101", RESERVAR, AHORA)
            desenlace = "admitido"
        except TasaExcedida:
            desenlace = "topado"
        with cerrojo:
            resultados.append(desenlace)

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as piscina:
        list(piscina.map(intentar, range(50)))

    admitidos = resultados.count("admitido")
    assert admitidos == tope, (
        f"{admitidos} intentos admitidos con tope {tope}. Si son mas, el "
        "contador tiene una carrera dentro; si son menos, esta rechazando de mas"
    )
    assert cont.consumido("U-101", AHORA) == tope
