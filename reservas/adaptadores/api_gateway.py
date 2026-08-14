"""Traduccion entre API Gateway y el vocabulario de este sistema.

Esto es la otra mitad de D-P4-02: `borde.py` no sabe que existe API Gateway, y
puede no saberlo porque **todo lo que sabe de API Gateway esta aqui**. Si manana
el borde fuera una funcion de otro proveedor, o un servidor propio, se reescribe
este fichero y nada de `borde.py`, `atender.py` ni el nucleo se entera.

Por eso este modulo **no decide nada**. No hay una sola regla de negocio, ni un
codigo de estado elegido aqui, ni una comprobacion de identidad. Traduce formas.
El dia que aparezca un `if` de dominio en este fichero, la frontera se rompio.

------------------------------------------------------------------------------
FORMATO DE CARGA 2.0 (HTTP API)
------------------------------------------------------------------------------
Se traduce el formato **2.0**, que es el de las HTTP API. `[A]` declarado: no se
ha ejecutado todavia contra API Gateway real —eso llega al desplegar—, asi que
lo de aqui esta escrito contra la documentacion del formato y no contra un
evento observado. Lo que si esta ejercitado son las formas: `test_api_gateway.py`
usa eventos con la estructura documentada, incluidos los degenerados.

De ese evento se usan exactamente cinco cosas, y ninguna mas:

    routeKey                       -> metodo + plantilla de ruta
    pathParameters                 -> lo que la plantilla captura
    queryStringParameters / body   -> lo que el cliente escribio
    headers.authorization          -> el token SIN VERIFICAR
    requestContext.http.sourceIp   -> el origen, para la cuota del dispensador
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from ..casos_uso.atender import Dependencias, atender
from ..nucleo.tiempo import ZONA
from . import borde

PREFIJO_PORTADOR = "bearer "
"""Se compara en minusculas: el nombre del esquema es insensible a mayusculas
por RFC 7235, y un cliente que mande `Bearer` o `bearer` no debe obtener
respuestas distintas."""


class EventoIlegible(Exception):
    """El evento no tiene la forma de una peticion. **No es un rechazo de
    dominio**: es que no hubo peticion que atender."""


def peticion_de(evento: dict) -> borde.PeticionHttp:
    """Evento de API Gateway -> `PeticionHttp`. Sin interpretar nada."""
    if not isinstance(evento, dict):
        raise EventoIlegible("el evento no es un objeto")

    clave_ruta = evento.get("routeKey")
    if not isinstance(clave_ruta, str) or " " not in clave_ruta:
        raise EventoIlegible("sin routeKey utilizable")
    metodo, _, plantilla = clave_ruta.partition(" ")

    cabeceras = {
        str(k).lower(): v for k, v in (evento.get("headers") or {}).items()
    }

    # El token, tal como llego. Aqui NO se valida nada: quitar el prefijo del
    # esquema es transporte; comprobar la firma es `atender`.
    autorizacion = cabeceras.get("authorization") or ""
    if autorizacion.lower().startswith(PREFIJO_PORTADOR):
        autorizacion = autorizacion[len(PREFIJO_PORTADOR):].strip()

    # **`origen` es quien pide, para la cuota por origen del dispensador
    # (D-SEC-6). NO es la cabecera `Origin` de CORS**, que es cosa del
    # navegador y la controla quien llama. Se toma de `sourceIp`, que lo pone
    # el borde y el cliente no elige.
    contexto_http = (evento.get("requestContext") or {}).get("http") or {}
    origen = contexto_http.get("sourceIp")

    return borde.PeticionHttp(
        ruta=plantilla,
        metodo=metodo.upper(),
        cuerpo=_cuerpo_de(evento),
        origen=origen,
        autorizacion=autorizacion or None,
        parametros_ruta=dict(evento.get("pathParameters") or {}),
    )


def _cuerpo_de(evento: dict) -> dict:
    """Lo que el cliente escribio, venga por cuerpo o por cadena de consulta.

    Los dos acaban en el mismo sitio a proposito: para `atender` son lo mismo
    —datos que el cliente controla— y separarlos obligaria a cada manejador a
    saber por que canal viajo su parametro, que es justo lo que esta frontera
    existe para ocultar.
    """
    cuerpo: dict = dict(evento.get("queryStringParameters") or {})

    crudo = evento.get("body")
    if crudo in (None, ""):
        return cuerpo

    if evento.get("isBase64Encoded"):
        try:
            crudo = base64.b64decode(crudo).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as error:
            raise EventoIlegible("cuerpo no descodificable") from error

    try:
        analizado = json.loads(crudo)
    except (TypeError, ValueError) as error:
        raise EventoIlegible("cuerpo que no es JSON") from error

    if not isinstance(analizado, dict):
        raise EventoIlegible("el cuerpo no es un objeto")

    cuerpo.update(analizado)
    return cuerpo


def respuesta_a_evento(respuesta: borde.RespuestaHttp) -> dict:
    """`RespuestaHttp` -> lo que la funcion devuelve al borde.

    `body` va serializado a texto porque es lo que el formato 2.0 espera de una
    respuesta estructurada. Es la ultima linea donde este sistema habla en el
    idioma del proveedor.
    """
    return {
        "statusCode": respuesta.codigo,
        "headers": dict(respuesta.cabeceras),
        "body": json.dumps(respuesta.cuerpo, ensure_ascii=False),
        "isBase64Encoded": False,
    }


def manejar(evento: dict, deps: Dependencias, ahora: datetime) -> dict:
    """El camino completo, con `deps` y `ahora` inyectados.

    Existe separado de `lambda_handler` para que las pruebas ejerciten el camino
    entero **sin variables de entorno y sin nube**, que es la propiedad que hace
    que I-6 se pueda comprobar en el CI.
    """
    try:
        peticion = peticion_de(evento)
    except EventoIlegible:
        # Un evento ilegible no llego a ser una peticion. Se responde 400 sin
        # decir que parte fallo: el detalle solo le sirve a quien esta tanteando
        # la forma del evento.
        return respuesta_a_evento(
            borde.respuesta_json(
                400, {"resultado": "peticion-mal-formada"}, deps.origen_permitido
            )
        )
    return respuesta_a_evento(atender(peticion, deps, ahora))


def ahora_local() -> datetime:
    """El unico reloj del sistema, y esta en el adaptador a proposito.

    modelo-datos §4.3 regla 5: ninguna clave se deriva del reloj del entorno, y
    el nucleo no llama a `now()`. Alguien tiene que hacerlo, y le toca a la capa
    que ya habla con el mundo.
    """
    return datetime.now(ZONA)
