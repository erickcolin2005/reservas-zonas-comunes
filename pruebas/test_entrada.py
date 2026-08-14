"""La raiz de composicion: que se niegue a arrancar mal configurada.

Estas pruebas valen justamente por lo que impiden. Un despliegue que arranca con
un parametro a medias **parece configurado**, y el fallo aparece semanas
despues, en forma de un control que no controlaba.
"""

from __future__ import annotations

import pytest

from reservas import entrada
from reservas.adaptadores.contadores import (
    ContadorIntentosDynamoDB,
    CuotaOrigenDynamoDB,
    EnfriamientoInstrumento,
)
from reservas.seguridad.contador import DesigualdadIncoherente

ENTORNO = {
    "RESERVAS_UNIDADES_ACTIVAS": "U-101,U-102,U-103",
    "RESERVAS_ESPACIOS": "E-SAL,E-BBQ,E-CAN",
    "RESERVAS_VENTANA_SEGUNDOS": "60",
    "RESERVAS_TOPE_POR_IDENTIDAD": "5",
    "RESERVAS_TOPE_POR_ORIGEN": "2",
    "RESERVAS_CAPACIDAD_DEL_BORDE": "100",
    "RESERVAS_ENFRIAMIENTO_SEGUNDOS": "20",
    "RESERVAS_ORIGEN_PERMITIDO": "https://reservas-demo.example",
    "RESERVAS_CLAVE_FIRMA": "no-es-un-secreto-real-solo-una-prueba",
}


class ClienteDeMentira:
    """No se llama a nada suyo: construir las dependencias no toca el motor."""


def test_se_construye_entero_con_el_entorno_completo():
    deps = entrada.dependencias(entorno=ENTORNO, cliente=ClienteDeMentira())
    assert deps.espacios == ("E-SAL", "E-BBQ", "E-CAN")
    assert deps.origen_permitido == "https://reservas-demo.example"
    assert deps.dispensador.activas == ("U-101", "U-102", "U-103")


def test_los_dos_contadores_del_despliegue_van_a_la_tabla_y_no_a_la_memoria():
    """**Es la prueba que impide el defecto que motivo todo esto.**

    Si alguien "simplificara" volviendo a los contadores en memoria, el sistema
    seguiria funcionando, la suite seguiria verde, y el techo pasaria de
    `50 x tope` a `50 x tope x contenedores` sin que nada lo dijera.
    """
    deps = entrada.dependencias(entorno=ENTORNO, cliente=ClienteDeMentira())
    assert isinstance(deps.contador, ContadorIntentosDynamoDB)
    assert isinstance(deps.dispensador.cuota, CuotaOrigenDynamoDB)


def test_el_enfriamiento_del_instrumento_queda_puesto():
    """D-CE4-1. Sin el, el despliegue funciona igual de bien hasta que alguien
    ejecuta el instrumento doce veces seguidas, agota el deposito de rafaga y
    la demo deja de demostrar. `None` es valido en pruebas y falso aqui."""
    deps = entrada.dependencias(entorno=ENTORNO, cliente=ClienteDeMentira())
    assert isinstance(deps.enfriamiento, EnfriamientoInstrumento)


@pytest.mark.parametrize("ausente", sorted(ENTORNO))
def test_falta_cualquier_parametro_y_no_arranca(ausente):
    """Ninguno tiene valor por defecto. **Ninguno**, y por eso se prueban todos:
    con una lista de ejemplos, el que se anadiera manana se quedaria fuera."""
    incompleto = {k: v for k, v in ENTORNO.items() if k != ausente}
    with pytest.raises(entrada.ConfiguracionIncompleta, match=ausente):
        entrada.dependencias(entorno=incompleto, cliente=ClienteDeMentira())


@pytest.mark.parametrize("vacio", ["", "   "])
def test_un_parametro_presente_pero_vacio_cuenta_como_ausente(vacio):
    """Una variable de entorno definida a cadena vacia es el error tipico de un
    IaC con una sustitucion que no resolvio. Aceptarla seria arrancar con la
    clave de firma vacia, que es lo que `prestamo.py` ya se niega a hacer."""
    roto = dict(ENTORNO, RESERVAS_CLAVE_FIRMA=vacio)
    with pytest.raises(entrada.ConfiguracionIncompleta):
        entrada.dependencias(entorno=roto, cliente=ClienteDeMentira())


def test_la_desigualdad_se_comprueba_al_arrancar_y_no_en_una_revision():
    """SEC-1: *una desigualdad que hay que acordarse de verificar es una
    desigualdad que un dia no se verifica*.

    Tres identidades por cinco intentos son quince, y el borde solo deja pasar
    diez: el borde rechazaria antes que el contador y la medicion se invalidaria
    **sin que el contador hubiera actuado**. La funcion no arranca.
    """
    incoherente = dict(ENTORNO, RESERVAS_CAPACIDAD_DEL_BORDE="10")
    with pytest.raises(DesigualdadIncoherente):
        entrada.dependencias(entorno=incoherente, cliente=ClienteDeMentira())


def test_el_origen_con_comodin_no_llega_a_desplegarse():
    """SEC-6, comprobado al arrancar.

    `cabeceras_cors` ya rechaza el comodin, pero lo hace en la primera peticion
    — y para entonces hay un despliegue vivo y mal configurado. La diferencia
    entre «falla» y «no arranca» es **quien se entera**: en el segundo caso,
    quien despliega; en el primero, quien ya estaba usandolo.
    """
    with pytest.raises(ValueError, match="comodin"):
        entrada.dependencias(
            entorno=dict(ENTORNO, RESERVAS_ORIGEN_PERMITIDO="*"),
            cliente=ClienteDeMentira(),
        )
