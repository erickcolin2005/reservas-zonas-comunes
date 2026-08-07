"""El puerto de persistencia — la frontera de D-P4-02.

No pretende hacer DynamoDB intercambiable. Eso seria sobreingenieria y ademas
mentira: el modelo esta disenado sobre garantias concretas de ESTE motor
(ADR-07, consecuencia c).

Lo que si hace es dar un punto de ejecucion al nucleo sin pasar por HTTP, que es
lo que permite correr el banco y los casos K sin API y sin nube.

------------------------------------------------------------------------------
SUPERFICIE COMPLETA DEL PUERTO, Y QUE PARTE ES DE I-1
------------------------------------------------------------------------------
arquitectura.md §4 declara siete operaciones. En I-1 existen dos:

    leer_estado(solicitud)                    -> EstadoLeido            [I-1]
    intentar_confirmar(intencion, token)      -> ResultadoEscritura     [I-1]

    contar_intento(identidad, ventana)        -> DentroDeTope|Superado  [I-6]
    cancelar(intencion_cancelacion, token)                              [I-4]
    tomar_franjas_bloqueo(...)                                          [I-4]
    prestar_identidades(cantidad, origen)                               [I-6]
    devolver_identidades(tokens)                                        [I-6]

Las cinco que faltan **no estan declaradas como metodos vacios**, y es
deliberado: un metodo que existe y no hace nada se confunde con uno
implementado. En particular `contar_intento` es el contador de intentos de
SEC-1, que va PRIMERO y FUERA de la transaccion (ADR-29). En I-1 no existe, y
por tanto **el camino de escritura de modelo-datos §5.0 esta incompleto**: falta
su paso 2. Queda escrito aqui para que I-6 no tenga que redescubrirlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .nucleo.modelo import EstadoLeido, Franja, IntencionEscritura, Solicitud


class ClaseItem(str, Enum):
    """Que clase de item de la transaccion incumplio su condicion.

    El mapeo a regla no vive aqui: vive en el caso de uso, porque depende de la
    marca pegajosa y del tipo del item ganador (ADR-04, ADR-17).
    """

    FRANJA = "FRANJA"
    AGENDA = "AGENDA"
    CUPO = "CUPO"
    CABECERA = "CABECERA"


class RazonCancelacion(str, Enum):
    """La razon con la que el motor cancelo una operacion de la transaccion.

    Los valores son los que devuelve el motor. Que el sustituto local los
    produzca con la misma semantica es exactamente lo que V-2a comprueba.
    """

    NINGUNA = "None"
    CONDICION = "ConditionalCheckFailed"
    CONFLICTO = "TransactionConflict"
    CAPACIDAD = "ProvisionedThroughputExceeded"
    ESTRANGULADA = "ThrottlingError"
    OTRA = "OTRA"


@dataclass(frozen=True)
class ItemEnFallo:
    """Un item de la transaccion que no paso, con lo que hace falta para atribuir."""

    clase: ClaseItem
    razon: RazonCancelacion
    franja: Franja | None = None
    item_devuelto: dict | None = None
    """Lo que el motor devuelve del item que incumplio la condicion, si lo
    devuelve (`ReturnValuesOnConditionCheckFailure`). Es lo que permite
    distinguir RR-09 de RR-11 sin una lectura extra, y lo que sostiene la
    idempotencia de ADR-25. **Que el sustituto local lo devuelva es V-2a.**"""


class TipoResultado(str, Enum):
    ACEPTADA = "ACEPTADA"
    CONDICION_INCUMPLIDA = "CONDICION_INCUMPLIDA"
    CONFLICTO = "CONFLICTO"
    CAPACIDAD = "CAPACIDAD"


@dataclass(frozen=True)
class ResultadoEscritura:
    """Lo que devuelve un intento de transaccion. Sin interpretar."""

    tipo: TipoResultado
    items_en_fallo: tuple[ItemEnFallo, ...] = ()
    id_reserva: str | None = None
    detalle: str | None = None


class PuertoPersistencia(Protocol):
    """Lo que el caso de uso necesita del motor, y nada mas."""

    def leer_estado(self, solicitud: Solicitud) -> EstadoLeido:
        """Lee con consistencia fuerte lo que alimenta la evaluacion.

        Consistencia fuerte por ATRIBUCION, nunca por correccion (ADR-23): la
        correccion no depende de ninguna lectura.
        """
        ...

    def intentar_confirmar(
        self, intencion: IntencionEscritura, token_solicitud: str, id_reserva: str
    ) -> ResultadoEscritura:
        """Un unico intento de la transaccion condicional. Sin reintentos.

        Los reintentos y la marca pegajosa son del caso de uso (ADR-04): la
        atribucion pertenece a la SOLICITUD, no al intento interno.
        """
        ...

    def leer_ocupacion(self, franjas) -> dict:
        """Quien ocupa esas franjas ahora mismo. Solo en el camino perdedor.

        Se usa una sola vez, al agotar los reintentos, para decidir entre RR-11
        (la franja esta tomada) y SYS-CONTENCION (sigue libre).
        """
        ...
