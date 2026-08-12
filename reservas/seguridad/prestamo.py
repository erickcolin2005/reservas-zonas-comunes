"""El préstamo de identidades: dispensador y autorizador (SEC-1, SEC-2).

Este modulo resuelve el **hueco central** del modelo de amenazas (T-01): si
cualquiera puede pedir identidades sin limite, el limite por identidad deja de
limitar y el techo de trafico pasa a ser infinito.

La respuesta no es un limite mas grande, es un **conjunto cerrado**:

    D-SEC-1  las identidades son EXACTAMENTE las sembradas. El extremo no puede
             crear ninguna que no exista ya en la tabla.
    D-SEC-2  el solicitante NO elige unidad: el sistema le asigna una.
    D-SEC-3  lo que se entrega es un PRESTAMO, no una cuenta: unidad, rol
             residente, emision y expiracion corta. Nada mas.
    D-SEC-4  la administracion NUNCA se presta, bajo ninguna combinacion de
             parametros.
    D-SEC-5  la unidad de entrega es el LOTE: el instrumento necesita 50
             identidades a la vez, y con un lote una ejecucion del instrumento
             es una sola llamada al dispensador.
    D-SEC-6  el limite por origen vive AQUI, no en /reservas. Vive exactamente
             donde no destruye la carrera.

------------------------------------------------------------------------------
LO QUE ESTE SISTEMA NO TIENE, Y SE DECLARA EN VEZ DE DISIMULARSE
------------------------------------------------------------------------------
**No hay lista de revocacion** (D-SEC-3, T-06). Un token filtrado caduca solo, y
esa es la unica revocacion que este sistema va a tener. Decirlo es parte del
diseno: un sistema sin revocacion que no lo declara invita a confiar en una
propiedad que no tiene.

**No hay ningun secreto en este repositorio** (RNF-07). La clave de firma entra
como parametro; el modulo se niega a funcionar con una vacia en vez de caer en
un valor por defecto que acabaria siendo el de todos.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

ALGORITMO = "HS256"
"""El unico algoritmo aceptado. Se verifica **explicitamente** al validar: un
verificador que se fia del campo `alg` del propio token acepta `none` y acepta
que se le cambie el algoritmo por otro que el atacante controla."""

ROL_RESIDENTE = "residente"
ROL_ADMINISTRACION = "administracion"

VIGENCIA_POR_DEFECTO = timedelta(minutes=15)
"""Corta a proposito (D-SEC-3). Es lo que hace que un token filtrado deje de
servir sin que nadie tenga que hacer nada."""


class TokenInvalido(Exception):
    """El token no se acepta. **Nunca dice por que en la respuesta.**

    El motivo se conserva aqui para el registro y las pruebas, pero el borde
    responde `SYS-IDENTIDAD` sin detalle: distinguir "firma mala" de "caducado"
    le diria a quien prueba cual de las dos cosas tiene que arreglar.
    """


class IdentidadNoPrestable(Exception):
    """Se pidio prestar algo que este extremo no presta."""


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firmar(cuerpo: bytes, clave: bytes) -> str:
    return _b64(hmac.new(clave, cuerpo, hashlib.sha256).digest())


def emitir(
    unidad: str,
    clave: bytes,
    ahora: datetime,
    vigencia: timedelta = VIGENCIA_POR_DEFECTO,
    rol: str = ROL_RESIDENTE,
) -> str:
    """Emite un token de prestamo.

    **`rol` existe como parametro y aun asi la administracion no es emitible.**
    Podria no existir el parametro; se deja para que el rechazo de D-SEC-4 sea
    una comprobacion que se puede PROBAR, en vez de una imposibilidad silenciosa
    que nadie sabria si sigue ahi.
    """
    if not clave:
        raise ValueError(
            "la clave de firma no puede estar vacia. No hay valor por defecto a "
            "proposito: un secreto por defecto acaba siendo el secreto de todos "
            "(RNF-07)"
        )
    if rol != ROL_RESIDENTE:
        # D-SEC-4. "Bajo ninguna combinacion de parametros."
        raise IdentidadNoPrestable(
            f"este extremo solo presta el rol {ROL_RESIDENTE!r}. La "
            "administracion no se presta (D-SEC-4)"
        )

    cabecera = {"alg": ALGORITMO, "typ": "prestamo"}
    cuerpo = {
        "unidad": unidad,
        "rol": rol,
        "emitido": int(ahora.timestamp()),
        "expira": int((ahora + vigencia).timestamp()),
    }
    partes = f"{_b64(json.dumps(cabecera).encode())}.{_b64(json.dumps(cuerpo).encode())}"
    return f"{partes}.{_firmar(partes.encode(), clave)}"


@dataclass(frozen=True)
class Prestamo:
    unidad: str
    rol: str
    expira: int


def verificar(token: str, clave: bytes, ahora: datetime) -> Prestamo:
    """Valida un token y devuelve a quien representa.

    El orden de las comprobaciones importa: **la firma se verifica ANTES de
    creerse nada del cuerpo**. Leer la unidad de un token sin firma valida y
    despues comprobar la firma es como se construyen los sistemas que confian en
    datos que un atacante escribio.
    """
    try:
        cab_b64, cuerpo_b64, firma = token.split(".")
    except (ValueError, AttributeError):
        raise TokenInvalido("el token no tiene tres partes") from None

    # 1. La firma, en tiempo constante. Antes que cualquier otra cosa.
    esperada = _firmar(f"{cab_b64}.{cuerpo_b64}".encode(), clave)
    if not hmac.compare_digest(esperada, firma):
        raise TokenInvalido("firma que no corresponde")

    # 2. El algoritmo, comprobado contra el UNICO aceptado y no contra lo que el
    #    token diga de si mismo. Aqui muere `alg: none`.
    try:
        cabecera = json.loads(_de_b64(cab_b64))
        cuerpo = json.loads(_de_b64(cuerpo_b64))
    except Exception:
        raise TokenInvalido("cabecera o cuerpo ilegibles") from None
    if cabecera.get("alg") != ALGORITMO:
        raise TokenInvalido(f"algoritmo {cabecera.get('alg')!r} no aceptado")

    # 3. La expiracion. Es la unica revocacion que existe (T-06, declarado).
    if int(cuerpo.get("expira", 0)) <= int(ahora.timestamp()):
        raise TokenInvalido("prestamo caducado")

    rol = cuerpo.get("rol")
    if rol not in (ROL_RESIDENTE, ROL_ADMINISTRACION):
        raise TokenInvalido(f"rol {rol!r} desconocido")

    return Prestamo(unidad=cuerpo["unidad"], rol=rol, expira=int(cuerpo["expira"]))


def exigir_rol(prestamo: Prestamo, rol_requerido: str) -> None:
    """El rol se comprueba POR RUTA (SEC-2).

    Un token valido de residente **no abre** una ruta de administracion. Que el
    token sea autentico dice quien eres, no que puedas hacer esto.
    """
    if prestamo.rol != rol_requerido:
        raise TokenInvalido(
            f"el rol {prestamo.rol!r} no alcanza esta ruta, que exige "
            f"{rol_requerido!r}"
        )


# ---------------------------------------------------------------------------
# El dispensador — D-SEC-1, D-SEC-2, D-SEC-5, D-SEC-6
# ---------------------------------------------------------------------------


@dataclass
class Dispensador:
    """Presta identidades de un conjunto CERRADO. No crea ninguna.

    `activas` son exactamente las unidades sembradas y activas. Que llegue como
    dato y no como generador es lo que hace verdadera la frase "el extremo no
    puede crear una identidad que no exista": no tiene con que.
    """

    activas: tuple[str, ...]
    clave: bytes
    tope_por_origen: int = 2
    """D-SEC-6. Cuantos LOTES puede pedir un mismo origen en la ventana. Es
    bajo a proposito: el instrumento necesita **un** lote por ejecucion
    (D-SEC-5), asi que un tope de 2 deja margen para un reintento y no para un
    bucle. **Vive aqui y no en /reservas**, que es lo que impide que el limite
    destruya la carrera que el instrumento existe para producir."""

    _pedidos_por_origen: dict = None

    def __post_init__(self):
        if self._pedidos_por_origen is None:
            self._pedidos_por_origen = {}

    def prestar(self, cantidad: int, origen: str, ahora: datetime) -> list[dict]:
        """Devuelve un LOTE de credenciales distintas (D-SEC-5).

        No admite un parametro de unidad, y esa ausencia es D-SEC-2: el
        solicitante no elige, el sistema asigna y se lo dice.
        """
        if cantidad < 1:
            raise ValueError("un lote de cero credenciales no es un lote")
        if cantidad > len(self.activas):
            # D-SEC-1: el conjunto es cerrado. No se fabrican identidades para
            # cubrir la diferencia; se dice cuantas hay.
            raise IdentidadNoPrestable(
                f"se pidieron {cantidad} y el conjunto cerrado tiene "
                f"{len(self.activas)}. No se crean identidades (D-SEC-1)"
            )

        gastados = self._pedidos_por_origen.get(origen, 0)
        if gastados >= self.tope_por_origen:
            raise IdentidadNoPrestable(
                f"el origen agoto su cuota de {self.tope_por_origen} lotes "
                "(D-SEC-6)"
            )
        self._pedidos_por_origen[origen] = gastados + 1

        # Asignacion sin repeticion dentro del lote. Aleatoria para que dos
        # ejecuciones seguidas no compitan siempre por las mismas unidades, que
        # sesgaria la medicion hacia un subconjunto del conjunto cerrado.
        elegidas = secrets.SystemRandom().sample(list(self.activas), cantidad)
        return [
            {"unidad": u, "token": emitir(u, self.clave, ahora)} for u in elegidas
        ]
