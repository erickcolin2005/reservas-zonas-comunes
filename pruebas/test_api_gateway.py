"""El traductor. Se prueba que traduce **y que no decide**.

La segunda mitad es la que importa para D-P4-02: un traductor que empieza a
tomar decisiones deja de ser una frontera y pasa a ser una segunda copia de la
logica, en el peor sitio posible.
"""

from __future__ import annotations

import base64
import json

import pytest

from reservas.adaptadores import api_gateway
from reservas.adaptadores.api_gateway import (
    EventoIlegible,
    manejar,
    peticion_de,
    respuesta_a_evento,
)
from reservas.adaptadores.borde import RespuestaHttp

from .test_atender import AHORA, INICIO, ORIGEN, ESPACIO, deps, token_de


def evento(
    clave_ruta: str = "POST /reservas",
    cuerpo: dict | None = None,
    cabeceras: dict | None = None,
    consulta: dict | None = None,
    parametros: dict | None = None,
    ip: str = "203.0.113.7",
) -> dict:
    """Un evento con la estructura del formato 2.0."""
    return {
        "version": "2.0",
        "routeKey": clave_ruta,
        "rawPath": clave_ruta.split(" ", 1)[1],
        "headers": cabeceras or {},
        "queryStringParameters": consulta,
        "pathParameters": parametros,
        "requestContext": {
            "http": {"method": clave_ruta.split(" ", 1)[0], "sourceIp": ip}
        },
        "body": None if cuerpo is None else json.dumps(cuerpo),
        "isBase64Encoded": False,
    }


# ---------------------------------------------------------------------------
# Traducir formas
# ---------------------------------------------------------------------------


def test_la_clave_de_ruta_se_parte_en_metodo_y_plantilla():
    """La PLANTILLA y no el camino concreto: `RUTAS_CONTADAS` del contador ya
    esta escrita con plantillas, y usar el camino concreto haria que cada
    identificador de reserva pareciera una ruta distinta."""
    p = peticion_de(evento("POST /reservas/{id}/cancelacion"))
    assert p.metodo == "POST"
    assert p.ruta == "/reservas/{id}/cancelacion"


@pytest.mark.parametrize("prefijo", ["Bearer ", "bearer ", "BEARER "])
def test_el_esquema_portador_se_quita_sin_mirar_mayusculas(prefijo):
    """RFC 7235: el nombre del esquema es insensible a mayusculas. Un cliente
    que mande `bearer` no puede obtener otra respuesta que uno que mande
    `Bearer`."""
    p = peticion_de(evento(cabeceras={"authorization": prefijo + "abc.def.ghi"}))
    assert p.autorizacion == "abc.def.ghi"


def test_las_cabeceras_se_leen_sin_mirar_mayusculas():
    p = peticion_de(evento(cabeceras={"Authorization": "Bearer xyz"}))
    assert p.autorizacion == "xyz"


def test_el_origen_sale_de_la_ip_de_origen_y_no_de_la_cabecera_Origin():
    """**Es la diferencia entre un control y un adorno.**

    `origen` alimenta la cuota por origen del dispensador (D-SEC-6). La cabecera
    `Origin` la escribe quien llama, asi que usarla como clave de cuota
    convertiria el limite en algo que se salta cambiando una cadena. `sourceIp`
    lo pone el borde.
    """
    p = peticion_de(
        evento(cabeceras={"origin": "https://me-lo-invento.example"}, ip="198.51.100.4")
    )
    assert p.origen == "198.51.100.4"


def test_el_cuerpo_y_la_cadena_de_consulta_acaban_en_el_mismo_sitio():
    """Para `atender` los dos son lo mismo: datos que el cliente controla."""
    e = evento("GET /espacios/{id}/disponibilidad", consulta={"dia": "2026-09-08"})
    p = peticion_de(e)
    assert p.cuerpo["dia"] == "2026-09-08"


def test_los_parametros_de_la_plantilla_van_aparte_del_cuerpo():
    """Vienen del camino, no de lo que el cliente escribio. Mezclarlos dejaria
    que un cuerpo con `{"id": ...}` suplantara al de la ruta."""
    e = evento("GET /espacios/{id}/disponibilidad", parametros={"id": ESPACIO.id})
    e["body"] = json.dumps({"id": "E-SUPLANTADO"})
    p = peticion_de(e)
    assert p.parametros_ruta["id"] == ESPACIO.id


def test_un_cuerpo_en_base64_se_descodifica():
    e = evento(cuerpo={"espacio": ESPACIO.id})
    e["body"] = base64.b64encode(e["body"].encode()).decode()
    e["isBase64Encoded"] = True
    assert peticion_de(e).cuerpo["espacio"] == ESPACIO.id


@pytest.mark.parametrize(
    "roto",
    [
        {"routeKey": "sin-espacio"},
        {"routeKey": None},
        {},
    ],
)
def test_un_evento_sin_ruta_utilizable_no_llega_a_ser_peticion(roto):
    with pytest.raises(EventoIlegible):
        peticion_de(roto)


def test_un_cuerpo_que_no_es_JSON_no_llega_a_ser_peticion():
    e = evento()
    e["body"] = "{esto no es json"
    with pytest.raises(EventoIlegible):
        peticion_de(e)


def test_un_cuerpo_que_es_JSON_pero_no_un_objeto_tampoco():
    """`[1,2,3]` es JSON valido y no es una peticion. Sin esto, `cuerpo.get`
    reventaria mas adentro, donde el error ya no se puede atribuir."""
    e = evento()
    e["body"] = "[1, 2, 3]"
    with pytest.raises(EventoIlegible):
        peticion_de(e)


def test_la_respuesta_se_serializa_al_formato_que_el_borde_espera():
    r = RespuestaHttp(200, {"resultado": "confirmada"}, {"X": "1"})
    salida = respuesta_a_evento(r)
    assert salida["statusCode"] == 200
    assert salida["headers"] == {"X": "1"}
    assert json.loads(salida["body"]) == {"resultado": "confirmada"}
    assert salida["isBase64Encoded"] is False


def test_los_acentos_no_se_escapan():
    """`ensure_ascii=False`: un mensaje con `\\u00f3` dentro es ilegible para
    quien lea la respuesta a mano, y este proyecto se lee a mano."""
    salida = respuesta_a_evento(RespuestaHttp(200, {"m": "confirmación"}, {}))
    assert "confirmación" in salida["body"]


# ---------------------------------------------------------------------------
# No decidir
# ---------------------------------------------------------------------------


def test_el_traductor_no_verifica_el_token():
    """Un token basura produce una `PeticionHttp` perfectamente valida.

    Traducir y autorizar son dos trabajos, y este modulo hace uno. Si el
    traductor rechazara aqui, la comprobacion de identidad estaria repartida en
    dos ficheros y uno de los dos acabaria quedandose atras.
    """
    p = peticion_de(evento(cabeceras={"authorization": "Bearer no-es-un-token"}))
    assert p.autorizacion == "no-es-un-token"


def test_el_traductor_no_conoce_ninguna_regla_ni_ningun_codigo():
    """Guardia contra la deriva: el dia que aparezca un `RR-` o un `401` en este
    fichero, la frontera de D-P4-02 se rompio y esto se pone en rojo."""
    import inspect

    fuente = inspect.getsource(api_gateway)
    cuerpo = "\n".join(
        linea
        for linea in fuente.splitlines()
        if not linea.lstrip().startswith("#")
    )
    # El docstring del modulo se excluye: puede citar el contrato sin aplicarlo.
    cuerpo = cuerpo.split('"""', 2)[-1]
    for prohibido in ("RR-0", "RR-1", "Cubo.", "401", "429", "respuesta_de("):
        assert prohibido not in cuerpo, (
            f"{prohibido!r} aparece en el traductor: eso es decidir, no traducir"
        )


# ---------------------------------------------------------------------------
# El camino completo, de evento a evento
# ---------------------------------------------------------------------------


def test_de_evento_a_evento_una_reserva_confirmada():
    d = deps()
    e = evento(
        cuerpo={
            "espacio": ESPACIO.id,
            "inicio": INICIO.isoformat(),
            "n_franjas": 1,
        },
        cabeceras={"authorization": f"Bearer {token_de()}"},
    )

    salida = manejar(e, d, AHORA)

    assert salida["statusCode"] == 200
    cuerpo = json.loads(salida["body"])
    assert cuerpo["resultado"] == "confirmada"
    assert cuerpo["reserva"]
    assert salida["headers"]["Access-Control-Allow-Origin"] == ORIGEN


def test_un_evento_ilegible_es_400_y_no_una_traza():
    d = deps()
    salida = manejar({"routeKey": "nada"}, d, AHORA)
    assert salida["statusCode"] == 400
    assert json.loads(salida["body"]) == {"resultado": "peticion-mal-formada"}


def test_el_camino_completo_sin_token_devuelve_401_y_no_toca_el_contador():
    d = deps()
    e = evento(cuerpo={"espacio": ESPACIO.id, "inicio": INICIO.isoformat(),
                       "n_franjas": 1})
    salida = manejar(e, d, AHORA)
    assert salida["statusCode"] == 401
    assert d.contador.consumido("U-101", AHORA) == 0
