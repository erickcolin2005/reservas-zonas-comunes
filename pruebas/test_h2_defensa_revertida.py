"""H2 — la prueba sabe ponerse en rojo, y queda constancia de ese rojo.

`plan-construccion.md` §4.2 lo dice sin rodeos:

    H1 verde, H2 no se puede poner en rojo -> NO CONTINUAR. Es el fallo fatal
    n.o 1 materializado: la prueba no prueba. **Un verde que no sabe ponerse
    rojo es peor que no tener prueba, porque genera confianza injustificada.**

Aqui el criterio esta invertido: se apaga cada defensa y **se exige el rojo**.
La constancia se guarda en `evidencia/h2-defensa-revertida.txt` en cada
ejecucion, para que el rojo no dependa de que alguien se acuerde de haberlo
visto una vez.
"""

from __future__ import annotations

import pytest

from herramientas import sensibilidad

from .conftest import guardar_evidencia

pytestmark = [pytest.mark.motor, pytest.mark.lento]


@pytest.fixture(scope="module")
def mutaciones(request):
    """Corre las mutaciones con el MISMO codigo que la herramienta.

    Si la prueba y la herramienta construyeran su informe por separado, la
    constancia que queda en disco al correr el CI y la que queda al correr la
    herramienta a mano dirian cosas distintas del mismo hecho — y entonces
    ninguna de las dos serviria de constancia.
    """
    endpoint = request.getfixturevalue("endpoint")
    cliente = request.getfixturevalue("cliente_sesion")
    t0 = request.getfixturevalue("t0")
    resultados, texto, _ = sensibilidad.ejecutar_todas(endpoint, cliente, t0)
    guardar_evidencia("h2-defensa-revertida.txt", texto + "\n")
    return resultados


def test_sin_escritura_condicional_la_prueba_se_pone_en_rojo(mutaciones):
    """El patron ingenuo: leo si esta libre y escribo.

    La lectura previa sigue puesta y sigue rechazando lo que ya estaba ocupado
    cuando miro — por eso este fallo es invisible en cualquier demostracion con
    una sola persona. Con 50 a la vez, casi todas confirman el mismo hueco.
    """
    resultado = mutaciones[sensibilidad.MUTACIONES[0].id]
    assert resultado.invariantes.build_en_rojo, (
        "la prueba NO se puso en rojo al quitar la escritura condicional. "
        "Entonces no esta vigilando la escritura condicional, y su verde no "
        "significa nada.\n" + resultado.texto
    )
    assert not resultado.invariantes.correccion_ok
    assert resultado.desglose.confirmadas > 1, (
        "sin condicion tendria que haber varias confirmadas sobre el mismo "
        "hueco\n" + resultado.texto
    )


def test_canonizando_en_utc_la_prueba_se_pone_en_rojo(mutaciones):
    """La mutacion que mas importa, y la que ninguna prueba de reglas ve.

    Aqui **la escritura condicional sigue puesta y ninguna regla se viola**. Lo
    unico que cambia es que la mitad de las solicitudes compone la clave con la
    hora en UTC. Las dos mitades escriben claves distintas, las dos condiciones
    se cumplen, y hay dos reservas del mismo hueco.

    Si esta mutacion no pusiera la prueba en rojo, la canonizacion no estaria
    vigilada por nada y C1 podria caerse sin que el banco entero se enterara.
    """
    resultado = mutaciones[sensibilidad.MUTACIONES[1].id]
    assert resultado.invariantes.build_en_rojo, (
        "la prueba NO se puso en rojo al normalizar la clave en UTC. La "
        "canonizacion no esta vigilada.\n" + resultado.texto
    )
    assert resultado.desglose.confirmadas == 2, (
        "se esperaban exactamente dos confirmadas: una por cada normalizacion. "
        "Un numero distinto significa que la mutacion no reprodujo el fallo que "
        "pretende reproducir\n" + resultado.texto
    )
    assert resultado.desglose.cuenta("RR-11") > 0, (
        "dentro de cada normalizacion la carrera se cerro igual: eso es lo que "
        "hace la mutacion tan enganosa\n" + resultado.texto
    )


def test_queda_declarado_lo_que_no_se_puede_mutar_en_local():
    """Dos defensas que el sustituto local no permite ejercitar.

    Fabricar una mutacion que en local salga en verde y contarla como cubierta
    seria justo lo que H2 existe para evitar. Se declaran, con su motivo y con
    el incremento en el que se pueden probar de verdad.
    """
    identificadores = [i for i, _ in sensibilidad.NO_EJERCITABLES_EN_LOCAL]
    assert any("ADR-04" in i for i in identificadores)
    assert any("SYS-CAPACIDAD" in i for i in identificadores)
