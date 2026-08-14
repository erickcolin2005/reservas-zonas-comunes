"""SEC-1 · el contador de intentos y la desigualdad que ata los dos controles.

Los criterios de aceptación son los del propio SEC-1, literales:

  - «el instrumento sigue produciendo ≥50 solicitudes simultáneas con el límite
    activo»
  - «una identidad que agota su cuota recibe `SYS-TASA` **y una segunda
    identidad no queda afectada**»

**Los casos de comportamiento no están escritos aquí**: viven en
`casos_contador.py` y los ejecutan también las pruebas contra el motor
(`test_contador_motor.py`). Este fichero corre la implementación en memoria y
añade lo que es exclusivamente suyo. Corre **sin Docker**, y tiene que poder:
M4S lo muta en un paso del CI que no levanta ningún contenedor.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from reservas.seguridad import contador as c

from .casos_contador import CASOS, VENTANA


def nuevo(tope=3, ventana=VENTANA):
    return c.ContadorIntentos(ventana=ventana, tope=tope)


# ---------------------------------------------------------------------------
# Los casos compartidos, contra la implementación en memoria
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nombre", sorted(CASOS))
def test_caso_compartido(nombre):
    CASOS[nombre](nuevo)


# ---------------------------------------------------------------------------
# Lo que solo aplica a la versión en memoria
# ---------------------------------------------------------------------------


def test_una_ventana_no_positiva_se_rechaza_al_construir():
    with pytest.raises(ValueError, match="no expira nunca"):
        c.ContadorIntentos(ventana=timedelta(0), tope=3)


def test_un_tope_menor_que_uno_impide_hasta_el_calentamiento():
    with pytest.raises(ValueError, match="calentamiento"):
        c.ContadorIntentos(ventana=VENTANA, tope=0)


def test_no_hay_valores_por_defecto():
    """El modelo de amenazas se nego a inventar la ventana y el tope. Poner un
    valor por defecto aqui seria inventarlos igualmente, solo que sin que se
    note."""
    import dataclasses

    for nombre in ("ventana", "tope"):
        campo = c.ContadorIntentos.__dataclass_fields__[nombre]
        assert campo.default is dataclasses.MISSING, f"{nombre} tiene defecto"
        assert campo.default_factory is dataclasses.MISSING, f"{nombre} tiene fabrica"

    # Y la comprobacion que de verdad importa: no se puede construir sin darlos.
    with pytest.raises(TypeError):
        c.ContadorIntentos()


# ---------------------------------------------------------------------------
# La desigualdad que ata los dos controles
# ---------------------------------------------------------------------------


def test_la_desigualdad_pasa_cuando_el_borde_da_de_sobra():
    c.comprobar_desigualdad(n_identidades=50, tope_por_identidad=5, capacidad_del_borde=250)


def test_la_desigualdad_corta_una_configuracion_incoherente():
    """Sin ella, subir el tope por identidad por encima de lo que el borde
    admite hace que el borde rechace primero: el instrumento recibe `SYS-TASA`
    del borde y **la medicion se invalida sin que nadie haya tocado el
    contador**."""
    with pytest.raises(c.DesigualdadIncoherente, match="borde"):
        c.comprobar_desigualdad(n_identidades=50, tope_por_identidad=5, capacidad_del_borde=100)


def test_endurecer_un_control_no_puede_anular_el_otro_en_silencio():
    """El caso que la desigualdad existe para impedir, contado como escenario:
    alguien decide 'proteger mas' bajando la capacidad del borde y deja los dos
    controles incoherentes."""
    c.comprobar_desigualdad(50, 3, 150)  # coherente
    with pytest.raises(c.DesigualdadIncoherente):
        c.comprobar_desigualdad(50, 3, 149)  # una unidad menos y ya no lo es


# ---------------------------------------------------------------------------
# El tope se deriva de lo observado, no se inventa
# ---------------------------------------------------------------------------


def test_el_tope_se_deriva_de_las_repeticiones_observadas():
    """Dato de I-3: el CI necesito 3 corridas de K-03 para la medicion de S-2."""
    assert c.sugerencia_de_tope(repeticiones_observadas=3) == 5


def test_sin_observaciones_no_se_deriva_nada():
    with pytest.raises(ValueError, match="se mide primero"):
        c.sugerencia_de_tope(repeticiones_observadas=0)
