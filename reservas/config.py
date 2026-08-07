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


def endpoint() -> str:
    """Extremo del motor. Siempre local en I-1.

    Se lee de `RESERVAS_ENDPOINT` para que el CI pueda apuntar a su contenedor
    de servicio. **Si algun dia apunta a AWS, deja de ser I-1.**
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
