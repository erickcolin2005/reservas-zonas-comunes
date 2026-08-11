"""Parametros de ejecucion. Ninguno inventado en silencio.

Los valores que son decision de negocio y NO estan cerrados llevan su marca. No
se les pone un valor por defecto que parezca acordado: se exigen, o se declaran
como valor de prueba alla donde se usan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

REGION = "us-east-1"
"""ADR-06. Region declarada, parametro del IaC, sin ningun recurso multirregion.
En I-1 solo la usa el cliente local: **no se crea nada en AWS**."""

TABLA = "reservas-zonas-comunes"
"""Una sola tabla, clave compuesta (PK, SK), sin indices secundarios (ADR-24)."""

WCU = 25
RCU = 25
"""Modo aprovisionado. No es preferencia: es lo que exige el free tier perpetuo
(ADR-20, H3). Pasar la tabla a bajo demanda es una accion prohibida (CE-1)."""

ENDPOINT_POR_DEFECTO = "http://localhost:8000"
"""El sustituto local. El CI no toca el motor real, nunca (ADR-08)."""

VARIABLE_MOTOR_REAL = "RESERVAS_MOTOR_REAL"
"""Llave explicita para hablar con DynamoDB de verdad. Ver `motor_real()`."""


def motor_real() -> bool:
    """¿Se apunta al motor real de AWS?

    **Abierto en I-3, y a proposito con llave.** En I-1 el adaptador se negaba
    en redondo a conectarse a `amazonaws.com`, y el propio codigo dejo escrito
    que en I-3 habria que abrirlo "a proposito, dejando escrito por que". Esto
    es ese porque:

    V-1 solo se puede ejecutar contra el motor real. La asimetria del tramo
    local lo obliga: un sustituto serializa MAS que el servicio real, asi que
    una confirmacion en local NO implica una confirmacion en AWS. H1 es
    provisional hasta que esto corra contra DynamoDB.

    **Por que sigue siendo una puerta con llave y no una puerta abierta:**
    la cuenta esta en Plan de Pago y con CERO creditos (D-P4-17). Ya no hay
    apagado automatico ni credito que absorba nada: cada peticion al motor real
    es dinero. Que haga falta poner `RESERVAS_MOTOR_REAL=1` a mano significa
    que nadie golpea AWS por tener mal una variable de entorno, ni por
    ejecutar la suite sin pensar.

    El CI **nunca** debe ponerla. Ya tiene ademas un paso que falla si aparecen
    credenciales de AWS en el entorno.
    """
    return os.environ.get(VARIABLE_MOTOR_REAL, "").strip() == "1"


def endpoint() -> str:
    """Extremo del sustituto local.

    Se lee de `RESERVAS_ENDPOINT` para que el CI pueda apuntar a su contenedor
    de servicio. **No se usa cuando `motor_real()` es cierto**: contra AWS no se
    pasa `endpoint_url`, se deja que boto3 resuelva el del servicio.
    """
    return os.environ.get("RESERVAS_ENDPOINT", ENDPOINT_POR_DEFECTO)


@dataclass(frozen=True)
class Reintentos:
    """ADR-04: reintento acotado ante conflicto, con espera aleatoria.

    Los valores concretos NO estan fijados por ningun documento de diseno
    —"reintentos y espera son parametros: no invento sus valores" (ADR-04
    consecuencia c)—. Estos son los que usa I-1, elegidos aqui y declarados:

      maximo = 5      suficiente para absorber una racha de conflictos sin
                      convertir el camino perdedor en algo largo.
      espera_base_ms  el primer reintento espera entre 0 y este valor; despues
                      se duplica. Aleatorio para no re-sincronizar a los
                      perdedores, que es lo que produciria una segunda tanda de
                      conflictos identica a la primera.

    **Se miden en I-3 contra el motor real y se ajustan alli, no aqui.**
    """

    maximo: int = 5
    espera_base_ms: float = 10.0
    espera_maxima_ms: float = 200.0


HORIZONTE_H_DIAS_PRUEBA = 30
"""VALOR DE PRUEBA. NO es la decision de Erick.

`H` —el horizonte de vida de una reserva pasada, RT-2— esta marcado
VALIDAR-ERICK y sigue **abierto** (modelo-datos §10.1). El sistema no puede
inventarlo: es una decision que hay que poder defender en una entrevista.

Aqui hay un numero unicamente para que el atributo `ttl` de los items tenga
forma en las pruebas locales. El sustituto local **no borra por expiracion**, asi
que ninguna prueba de I-1 depende de este valor. El dia que se despliegue, `H`
sale del IaC y se declara en el README.
"""
