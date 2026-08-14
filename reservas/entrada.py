"""El punto de entrada del despliegue. Aqui se ata todo, y solo aqui.

Esta separado de `api_gateway.py` a proposito. Aquel modulo afirma de si mismo
que **no decide nada**, y elegir que contador se usa, que conjunto de identidades
existe o que origen se permite son decisiones — las mas consecuentes del
sistema. Mezclarlas con la traduccion habria hecho falsa esa afirmacion, y una
frontera que se describe a si misma mal es peor que no tenerla.

Lo que vive aqui es la **raiz de composicion**: el unico sitio del proyecto que
sabe a la vez de entorno, de motor y de controles.

------------------------------------------------------------------------------
NINGUN PARAMETRO TIENE VALOR POR DEFECTO, Y ESA ES LA REGLA
------------------------------------------------------------------------------
`security-agent` se nego a inventar la ventana y el tope; `architect-agent` se
nego a inventar la tasa sostenida; `prestamo.py` se niega a funcionar con una
clave vacia. Un valor por defecto aqui deshace las tres cosas de golpe, porque
un despliegue que arranca sin que nadie decida nada **parece configurado**.

Falta un parametro -> la funcion no arranca. Es ruidoso, y tiene que serlo.
"""

from __future__ import annotations

import os
from datetime import timedelta

from . import config
from .adaptadores.api_gateway import ahora_local, manejar
from .adaptadores.borde import cabeceras_cors
from .adaptadores.contadores import (
    ContadorIntentosDynamoDB,
    CuotaOrigenDynamoDB,
    EnfriamientoInstrumento,
)
from .adaptadores.dynamodb import AdaptadorDynamoDB, crear_cliente
from .casos_uso.atender import Dependencias
from .seguridad.contador import comprobar_desigualdad
from .seguridad.prestamo import Dispensador


class ConfiguracionIncompleta(Exception):
    """Falta un parametro del despliegue. **Se cae al arrancar, a proposito.**"""


def exigir(nombre: str, entorno=None) -> str:
    entorno = os.environ if entorno is None else entorno
    valor = (entorno.get(nombre) or "").strip()
    if not valor:
        raise ConfiguracionIncompleta(
            f"falta {nombre}. No hay valor por defecto: quien lo fija lo declara "
            "en el README"
        )
    return valor


def _lista(nombre: str, entorno=None) -> tuple[str, ...]:
    return tuple(x.strip() for x in exigir(nombre, entorno).split(",") if x.strip())


def dependencias(entorno=None, cliente=None) -> Dependencias:
    """Construye las dependencias y **comprueba la desigualdad al arrancar**.

    `n x tope <= lo que el borde deja pasar` se comprueba aqui y no en una
    revision manual: *una desigualdad que hay que acordarse de verificar es una
    desigualdad que un dia no se verifica* (SEC-1). Si no se cumple, la funcion
    **no arranca** — es mejor que arrancar con dos controles que se anulan y una
    medicion que se invalidara sin que nadie sepa por que.

    `entorno` y `cliente` entran por parametro para que esto se pueda probar sin
    variables de entorno reales y sin nube.
    """
    activas = _lista("RESERVAS_UNIDADES_ACTIVAS", entorno)
    espacios = _lista("RESERVAS_ESPACIOS", entorno)
    ventana = timedelta(seconds=int(exigir("RESERVAS_VENTANA_SEGUNDOS", entorno)))
    tope_identidad = int(exigir("RESERVAS_TOPE_POR_IDENTIDAD", entorno))
    tope_origen = int(exigir("RESERVAS_TOPE_POR_ORIGEN", entorno))
    capacidad_borde = int(exigir("RESERVAS_CAPACIDAD_DEL_BORDE", entorno))
    origen_permitido = exigir("RESERVAS_ORIGEN_PERMITIDO", entorno)
    clave = exigir("RESERVAS_CLAVE_FIRMA", entorno).encode()
    enfriamiento = timedelta(
        seconds=int(exigir("RESERVAS_ENFRIAMIENTO_SEGUNDOS", entorno))
    )

    comprobar_desigualdad(
        n_identidades=len(activas),
        tope_por_identidad=tope_identidad,
        capacidad_del_borde=capacidad_borde,
    )

    # SEC-6, comprobado **al arrancar y no en la primera peticion**.
    # `cabeceras_cors` ya rechaza el comodin, pero lo hace cuando alguien ya
    # esta llamando: para entonces hay un despliegue vivo y mal configurado.
    # Aqui la diferencia entre "falla" y "no arranca" es quien se entera.
    cabeceras_cors(origen_permitido)

    cliente = cliente if cliente is not None else crear_cliente()
    tabla = config.TABLA

    return Dependencias(
        clave=clave,
        adaptador=AdaptadorDynamoDB(cliente, tabla),
        # **Los dos contadores van a la tabla, no a la memoria del proceso.**
        # Es la diferencia entre un techo de `50 x tope` y uno de
        # `50 x tope x contenedores`, que es un numero que nadie decide.
        contador=ContadorIntentosDynamoDB(cliente, ventana, tope_identidad, tabla),
        dispensador=Dispensador(
            activas=activas,
            clave=clave,
            tope_por_origen=tope_origen,
            ventana=ventana,
            cuota=CuotaOrigenDynamoDB(cliente, ventana, tope_origen, tabla),
        ),
        espacios=espacios,
        origen_permitido=origen_permitido,
        # D-CE4-1. Sin esto el despliegue funciona igual de bien hasta que
        # alguien ejecuta el instrumento doce veces seguidas y la demo deja de
        # demostrar. `test_entrada.py` exige que este puesto.
        enfriamiento=EnfriamientoInstrumento(cliente, enfriamiento, tabla),
    )


_DEPS: Dependencias | None = None


def lambda_handler(evento: dict, contexto=None) -> dict:
    """Lo que invoca API Gateway.

    Las dependencias se construyen **una vez por contenedor**: el cliente del
    motor y la comprobacion de la desigualdad no tienen por que rehacerse en
    cada peticion. Reusar el contenedor **no reusa ninguna cuota**, porque las
    dos viven en la tabla — que es justo el defecto que tendrian las versiones
    en memoria.
    """
    global _DEPS
    if _DEPS is None:
        _DEPS = dependencias()
    return manejar(evento, _DEPS, ahora_local())
