"""La frontera HTTP. **No sabe que existe API Gateway.**

Esto es D-P4-02 hecho codigo. La decision se tomo en el pre-F0 y su argumento se
reescribio despues, asi que conviene repetirlo aqui en su version vigente: el
adaptador no esta por longevidad de la cuenta -esa razon caduco- sino por

  (a) **transferencia hacia P1**, donde separar la logica de su transporte es la
      competencia central del proyecto, y
  (b) **senal de portafolio**: un revisor ve una frontera puesta a proposito, no
      una Lambda acoplada al formato de evento de su proveedor.

La forma que toma: este modulo habla de `PeticionHttp` y `RespuestaHttp`, que son
suyas. La traduccion desde el evento de API Gateway vive en `api_gateway.py` y
son unas decenas de lineas. Si manana el borde fuera otro, se cambia esa
traduccion y **nada de aqui se entera**.

------------------------------------------------------------------------------
LA FRONTERA DEL 200 — el invariante que gobierna este modulo (ADR-15, §10.1)
------------------------------------------------------------------------------

    200      -> decidio y nombro la regla
    401      -> SYS-IDENTIDAD: el sistema no sabe quien pregunta
    429      -> SYS-TASA: no llego a evaluarse
    otro !=200 -> infraestructura

**Un rechazo de negocio viaja con 200.** No es laxitud: con codigos semanticos
el propio estado es un canal, y un 409 por "franja ocupada" le diria a un
extrano que esa franja esta ocupada sin que nadie se lo haya preguntado.

**Y una confirmacion producida por idempotencia es indistinguible de una
confirmacion normal, y DEBE serlo** (ADR-32): para el cliente es el mismo hecho
-su reserva existe- y darle un tipo propio expondria una diferencia interna que
no puede usar. La distincion se registra y el instrumento la cuenta aparte,
porque para el revisor si es informativa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..desenlaces import Cubo, Desenlace

# Codigo HTTP por cubo de desenlace. La tabla ES el contrato: si alguien quiere
# cambiar una respuesta, cambia aqui y las pruebas de frontera se lo discuten.
CODIGO_POR_CUBO = {
    Cubo.CONFIRMADA: 200,
    Cubo.RECHAZADA_REGLA: 200,
    Cubo.SYS_CONTENCION: 200,
    Cubo.SYS_IDENTIDAD: 401,
    Cubo.SYS_TASA: 429,
    Cubo.SYS_CAPACIDAD: 503,
    Cubo.OTRO: 500,
}
"""`SYS-CAPACIDAD` -> 503 y `OTRO` -> 500 son **decision del orquestador**, no
cita: §10.1 fija 401 y 429 y dice "otro !=200 => infraestructura", pero no
asigna estos dos. Se eligen asi porque capacidad agotada es exactamente un
"vuelve luego" (503) y lo desconocido no debe disfrazarse de otra cosa (500).
**Corregible por Erick**; lo que no es negociable es que ninguno sea 200: los
dos significan que el sistema NO decidio, y un 200 afirmaria lo contrario."""


@dataclass(frozen=True)
class PeticionHttp:
    """Una peticion, en el vocabulario de este sistema y no en el del proveedor.

    **`unidad` NO esta aqui, y su ausencia es el diseno** (ADR-26): la unidad se
    deriva de la identidad autenticada, nunca del cuerpo. No es que se ignore un
    campo `unidad` que llegue: es que **no hay donde ponerlo**. Por eso S-01 se
    sostiene por construccion y no por una comprobacion que alguien pudiera
    olvidar.
    """

    ruta: str
    metodo: str
    cuerpo: dict = field(default_factory=dict)
    identidad: str | None = None
    origen: str | None = None


@dataclass(frozen=True)
class RespuestaHttp:
    codigo: int
    cuerpo: dict
    cabeceras: dict = field(default_factory=dict)


def cabeceras_cors(origen_permitido: str) -> dict:
    """CORS con origen EXPLICITO. Nunca comodin (SEC-6).

    Un `*` aqui convertiria el instrumento en algo que cualquier pagina podria
    disparar desde el navegador de un tercero.
    """
    if origen_permitido == "*":
        raise ValueError(
            "CORS con comodin esta prohibido por SEC-6. El origen se declara."
        )
    return {
        "Access-Control-Allow-Origin": origen_permitido,
        "Content-Type": "application/json",
    }


def respuesta_de(desenlace: Desenlace, origen_permitido: str) -> RespuestaHttp:
    """Traduce un desenlace del dominio a una respuesta HTTP.

    **Lo que este cuerpo NO lleva, y es la mitad del trabajo:**

      - ningun mensaje del proveedor. Un `ConditionalCheckFailedException` que
        se escapara al cuerpo contaria como fuga (RNF-12, SEC-6).
      - ninguna referencia a datos ajenos. `RR-10` dice que la franja esta
        ocupada y **no dice por quien** (S-03).
    """
    codigo = CODIGO_POR_CUBO[desenlace.cubo]
    cuerpo: dict = {"resultado": desenlace.etiqueta()}

    if desenlace.cubo is Cubo.CONFIRMADA:
        # Sin distinguir la idempotente: para el cliente es el mismo hecho.
        cuerpo["reserva"] = desenlace.id_reserva
    elif desenlace.cubo is Cubo.RECHAZADA_REGLA:
        cuerpo["regla"] = desenlace.regla
        # RR-08 es el UNICO rechazo que puede llevar referencia, porque el dato
        # es de la propia unidad: sale de su agenda, no de una busqueda global
        # (S-03, threat-model §7.4).
        if desenlace.regla == "RR-08" and desenlace.franjas:
            cuerpo["conflicto_propio"] = str(desenlace.franjas[0])

    return RespuestaHttp(codigo, cuerpo, cabeceras_cors(origen_permitido))


def sin_identidad(origen_permitido: str) -> RespuestaHttp:
    """401. El sistema no sabe quien pregunta, y no llego a evaluar nada."""
    return RespuestaHttp(
        401, {"resultado": Cubo.SYS_IDENTIDAD.value}, cabeceras_cors(origen_permitido)
    )


def tasa_excedida(origen_permitido: str) -> RespuestaHttp:
    """429. Es lo que un cliente automatico sabe interpretar, y el instrumento
    lo cuenta aparte: un `SYS-TASA` no es un rechazo del sistema de reservas,
    es una medicion invalida."""
    return RespuestaHttp(
        429, {"resultado": Cubo.SYS_TASA.value}, cabeceras_cors(origen_permitido)
    )
