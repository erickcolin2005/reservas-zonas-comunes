"""V-2a — el sustituto local implementa lo que el mecanismo necesita.

Es lo PRIMERO del incremento, y se queda en el CI como prueba permanente. No es
ceremonia: si un dia el sustituto dejara de implementar la escritura condicional
o las transacciones, **todos los casos K seguirian pasando por razones
equivocadas** y nadie se enteraria mirando el verde.

Si esta prueba se pone en rojo, la salida esta escrita por adelantado (plan
§4.2): el CI pierde los casos K, T7a se declara incumplida en el README —no se
disimula— y la puerta de AWS se replantea. **Sube a `architect-agent`.**
"""

from __future__ import annotations

import pytest

from herramientas import v2a_sonda

pytestmark = pytest.mark.motor


@pytest.fixture(scope="module")
def informe(endpoint):
    from reservas.adaptadores import dynamodb

    cliente = dynamodb.crear_cliente(endpoint)
    salida = v2a_sonda.sondear(cliente)
    dynamodb.borrar_tabla(cliente, v2a_sonda.TABLA_SONDA)
    return salida


def test_v2a_sale_positiva(informe):
    """El veredicto entero. Si falla, no hay tramo local que valga."""
    assert informe.veredicto_v2a, informe.texto()


def test_la_escritura_condicional_impide_la_segunda_escritura(informe):
    """G-b: ante dos escrituras condicionales sobre la misma clave, a lo sumo
    una aplica. **Es lo unico que sostiene C1.**"""
    hallazgo = informe.por_id("V2a-1")
    assert hallazgo.ok, hallazgo.respuesta
    assert "ConditionalCheckFailedException" in hallazgo.respuesta


def test_la_transaccion_es_todo_o_nada(informe):
    """G-c. Sin esto, el solapamiento parcial (K-02) no se puede cerrar: cada
    solicitud se queda con parte de las franjas y ninguna confirma."""
    assert informe.por_id("V2a-3").ok
    hallazgo = informe.por_id("V2a-4")
    assert hallazgo.ok, hallazgo.respuesta


def test_las_razones_de_cancelacion_permiten_saber_cual_condicion_fallo(informe):
    """Sin esto no se puede atribuir la regla: solo se podria decir "fallo
    algo", y un rechazo que no nombra su regla no cuenta como rechazo (C3)."""
    hallazgo = informe.por_id("V2a-5")
    assert hallazgo.ok, hallazgo.respuesta


def test_el_contador_condicional_corta_en_el_tope(informe):
    """Es la segunda carrera (K-05) y la forma del contador de intentos (I-6)."""
    hallazgo = informe.por_id("V2a-8")
    assert hallazgo.ok, hallazgo.respuesta


def test_la_transaccion_admite_los_14_items_del_peor_caso(informe):
    """El maximo del modelo es 14 items: E-SAL con 6 franjas."""
    hallazgo = informe.por_id("V2a-7")
    assert hallazgo.ok, hallazgo.respuesta


# ---------------------------------------------------------------------------
# Lo que el sustituto NO hace. Se afirma para que un cambio de comportamiento
# se note, y para que nadie lea el verde del CI como si cubriera esto.
# ---------------------------------------------------------------------------


def test_queda_declarado_lo_que_el_sustituto_no_reproduce(informe):
    """La asimetria que gobierna el tramo local, convertida en prueba.

    Un sustituto local serializa MAS que el servicio real. Por eso:

        dos confirmaciones en local  ==> dos en AWS   (refutacion valida)
        una confirmacion en local    =/=> una en AWS  (confirmacion NO valida)

    Estas dos afirmaciones son las que hacen H1 **provisional** hasta I-3. Si
    algun dia el sustituto empezara a producir conflictos o a estrangular, esta
    prueba se pondria en rojo y habria que revisar que significa el verde de los
    casos K — que es exactamente lo que se quiere que pase.
    """
    conflictos = informe.por_id("V2a-9")
    assert "TransactionConflict" not in conflictos.respuesta, (
        "el sustituto ha empezado a producir conflictos de transaccion. Es una "
        "buena noticia, pero cambia lo que el CI puede afirmar: revisar ADR-04 "
        "y la mutacion M-c de herramientas/sensibilidad.py"
    )
    capacidad = informe.por_id("V2a-10")
    assert "NO." in capacidad.respuesta, (
        "el sustituto ha empezado a estrangular por capacidad. Revisar el cubo "
        "SYS-CAPACIDAD y la mutacion M-d"
    )
