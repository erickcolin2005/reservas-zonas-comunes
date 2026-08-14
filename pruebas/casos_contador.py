"""Los casos de comportamiento del contador, escritos UNA vez.

Existen dos implementaciones de SEC-1 —una en memoria y otra contra el motor— y
la unica forma de que el limite que se prueba sea el limite que actua es que las
dos pasen **los mismos casos**. Es la leccion de V-2b aplicada a un control:
*la clase del fallo tiene que coincidir entre motores*.

Por eso los casos viven aqui, sin depender de ninguna implementacion: cada uno
recibe una `fabrica(tope, ventana)` y no sabe que construye.

**Los dos ficheros que los ejecutan estan separados a proposito**, y no por
gusto: `test_contador.py` corre sin Docker —y tiene que poder, porque M4S lo
muta en un paso del CI que no levanta ningun contenedor— mientras que
`test_contador_motor.py` necesita el sustituto local. Un solo fichero mixto
dejaria el mutante del contador sin poder concluir nada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from reservas.seguridad.contador import TasaExcedida

AHORA = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
VENTANA = timedelta(seconds=60)
RESERVAR = "POST /reservas"
CANCELAR = "POST /reservas/{id}/cancelacion"
LEER = "GET /espacios/{id}/disponibilidad"


def el_instrumento_sigue_produciendo_50_simultaneas(fabrica):
    """El criterio que decide si el control es compatible con el proyecto.

    Un limite que impidiera al instrumento lanzar sus 50 solicitudes no estaria
    protegiendo el sistema: estaria **apagando la unica prueba de que la carrera
    se cierra**, que es lo que el proyecto existe para demostrar.
    """
    cont = fabrica(tope=3)
    for i in range(50):
        cont.registrar(f"U-{100 + i}", RESERVAR, AHORA)  # ninguna levanta


def una_identidad_agotada_no_afecta_a_las_demas(fabrica):
    cont = fabrica(tope=2)
    cont.registrar("U-101", RESERVAR, AHORA)
    cont.registrar("U-101", RESERVAR, AHORA)
    with pytest.raises(TasaExcedida):
        cont.registrar("U-101", RESERVAR, AHORA)
    # Si la segunda quedara afectada, un solo visitante dejaria al siguiente sin
    # instrumento: T-12, denegacion entre revisores.
    cont.registrar("U-102", RESERVAR, AHORA)


def cuenta_intentos_aunque_todos_sean_rechazados(fabrica):
    """Un contador de confirmaciones no limita nada: quien quiera agotar el
    sistema puede hacerlo con solicitudes que se rechazan."""
    cont = fabrica(tope=3)
    for _ in range(3):
        cont.registrar("U-101", RESERVAR, AHORA)  # el desenlace da igual
    assert cont.consumido("U-101", AHORA) == 3
    with pytest.raises(TasaExcedida):
        cont.registrar("U-101", RESERVAR, AHORA)


def la_cancelacion_tambien_consume_cuota(fabrica):
    """SEC-1 lo exige: «alcanza tambien la cancelacion». Sin esto, un bucle de
    reservar-cancelar (S-f) rodea el control entero."""
    cont = fabrica(tope=2)
    cont.registrar("U-101", RESERVAR, AHORA)
    cont.registrar("U-101", CANCELAR, AHORA)
    with pytest.raises(TasaExcedida):
        cont.registrar("U-101", RESERVAR, AHORA)


def las_lecturas_no_consumen_cuota(fabrica):
    """Solo las rutas que ESCRIBEN. Deja el calendario publico fluido, que es lo
    que H5 necesita, y reduce el costo de escritura del propio control."""
    cont = fabrica(tope=1)
    for _ in range(20):
        cont.registrar("U-101", LEER, AHORA)
    cont.registrar("U-101", RESERVAR, AHORA)  # la cuota sigue intacta


def la_ventana_expira_sin_que_nadie_la_limpie(fabrica):
    """El `ttl` del contador ES el fin de la ventana. Un control que necesita
    mantenimiento en un sistema sin proceso de fondo es un control que un dia
    deja de estar."""
    cont = fabrica(tope=1, ventana=timedelta(seconds=60))
    cont.registrar("U-101", RESERVAR, AHORA)
    with pytest.raises(TasaExcedida):
        cont.registrar("U-101", RESERVAR, AHORA + timedelta(seconds=59))
    cont.registrar("U-101", RESERVAR, AHORA + timedelta(seconds=61))


def el_cambio_de_cubeta_admite_hasta_el_doble_del_tope(fabrica):
    """**El precio de la ventana fija, medido en vez de mencionado.**

    Con cubetas alineadas a la epoca, gastar el tope al final de una y volver a
    gastarlo al principio de la siguiente mete `2 x tope` intentos en un
    intervalo de una sola ventana. Se acepta —el control existe para acotar el
    techo, no para regular un caudal exacto— pero se acepta **sabiendo el
    numero**, y esta prueba es la que lo fija.

    Si alguien cambiara a ventana deslizante, esta prueba se pondria roja. Eso
    es lo que se quiere: el cambio de semantica tiene que costar una decision
    explicita, no pasar desapercibido.
    """
    cont = fabrica(tope=2, ventana=timedelta(seconds=60))
    casi_el_final = AHORA + timedelta(seconds=59)
    justo_despues = AHORA + timedelta(seconds=61)

    cont.registrar("U-101", RESERVAR, casi_el_final)
    cont.registrar("U-101", RESERVAR, casi_el_final)
    with pytest.raises(TasaExcedida):
        cont.registrar("U-101", RESERVAR, casi_el_final)

    # Dos segundos despues, cubeta nueva y cuota entera: cuatro intentos en tres
    # segundos con un tope de dos por minuto.
    cont.registrar("U-101", RESERVAR, justo_despues)
    cont.registrar("U-101", RESERVAR, justo_despues)
    with pytest.raises(TasaExcedida):
        cont.registrar("U-101", RESERVAR, justo_despues)


CASOS = {
    f.__name__: f
    for f in (
        el_instrumento_sigue_produciendo_50_simultaneas,
        una_identidad_agotada_no_afecta_a_las_demas,
        cuenta_intentos_aunque_todos_sean_rechazados,
        la_cancelacion_tambien_consume_cuota,
        las_lecturas_no_consumen_cuota,
        la_ventana_expira_sin_que_nadie_la_limpie,
        el_cambio_de_cubeta_admite_hasta_el_doble_del_tope,
    )
}
