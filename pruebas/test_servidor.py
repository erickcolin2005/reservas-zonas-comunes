"""El emparejado de rutas del servidor de desarrollo.

`servidor.py` es un punto de entrada delgado, y aun asi esta pieza necesita prueba: **calca
lo que en produccion hace API Gateway**. Si empareja distinto, todo lo que se
mida en local describe un sistema que no es el que se despliega — y lo hara en
verde, que es la peor forma de equivocarse.

Lo que NO se prueba aqui es el servidor entero. Levantar un socket en el CI para
comprobar un andamio seria pagar fragilidad por poca cosa; lo que puede
divergir de verdad es esta funcion.
"""

from __future__ import annotations

import pytest

from herramientas.servidor import casar_ruta
from reservas.casos_uso.atender import RUTAS


@pytest.mark.parametrize("metodo,plantilla", sorted(RUTAS))
def test_toda_ruta_declarada_se_empareja_con_un_camino_concreto(metodo, plantilla):
    """Se recorren **todas** las rutas de la tabla, no una lista de ejemplos: la
    que alguien anada manana entra aqui sola."""
    concreto = plantilla.replace("{id}", "E-CAN")
    casada, parametros = casar_ruta(metodo, concreto)
    assert casada == plantilla
    if "{id}" in plantilla:
        assert parametros == {"id": "E-CAN"}


def test_el_parametro_de_ruta_se_extrae_y_se_desescapa():
    """API Gateway entrega `pathParameters` ya desescapados. Si aqui llegaran
    escapados, un identificador con caracteres especiales se buscaria en la
    tabla con la forma equivocada."""
    _, parametros = casar_ruta("GET", "/espacios/E%2DCAN/disponibilidad")
    assert parametros == {"id": "E-CAN"}


@pytest.mark.parametrize(
    "metodo,camino",
    [
        ("GET", "/espacios/E-CAN"),            # falta un segmento
        ("GET", "/espacios/E-CAN/otra/cosa"),  # sobra uno
        ("POST", "/espacios"),                 # metodo que no es
        ("GET", "/reservas"),                  # declarada en §10.2, no implementada
        ("POST", "/admin/bloqueos"),           # idem
        ("GET", "/"),                          # la pagina, no el API
    ],
)
def test_lo_que_no_esta_declarado_no_empareja(metodo, camino):
    """**Y no emparejar significa no invocar la funcion.** Es lo mismo que hace
    API Gateway: lo que no esta en su tabla de rutas no llega a la integracion,
    asi que un escaneo automatico no se convierte en consumo."""
    casada, _ = casar_ruta(metodo, camino)
    assert casada is None


def test_una_ruta_con_barra_final_empareja_igual():
    """Un `/espacios/` escrito a mano no puede comportarse distinto de
    `/espacios`: seria una diferencia entre local y desplegado por un caracter
    que nadie ve."""
    assert casar_ruta("GET", "/espacios/")[0] == "/espacios"
    assert casar_ruta("GET", "/espacios")[0] == "/espacios"
