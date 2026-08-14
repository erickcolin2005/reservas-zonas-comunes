"""M2-INS entero: del dispensador a la franja disputada, contra el motor.

**Es la prueba que cierra CD2.** Todo lo demas de I-6 comprueba piezas; esto
comprueba lo que un desconocido va a ejecutar, por el mismo camino que va a
recorrer: pedir el lote, calentar, disparar cincuenta a la vez contra la misma
franja, y leer el resultado.

Y corre con **la configuracion del despliegue**, no con una de pruebas: los
contadores van a la tabla, el enfriamiento esta puesto y la desigualdad de SEC-1
se comprueba al arrancar, porque los construye `entrada.dependencias`. Probar el
instrumento contra un cableado distinto del que se despliega seria medir la cosa
parecida.
"""

from __future__ import annotations

import threading

import pytest

from herramientas import m2_instrumento as ins
from reservas import config, entrada
from reservas.adaptadores import borde, dynamodb
from reservas.casos_uso.atender import atender
from reservas.nucleo import tiempo

ESPACIO = "E-CAN"  # 1 franja, 2 h de antelacion, horizonte 7 dias
N = 50
IP = "203.0.113.7"


class TransporteEnProceso:
    """Habla con `atender` en vez de por red, con un cliente POR HILO.

    El cliente por hilo no es una optimizacion: es la exigencia 2 del
    instrumento. Crear el cliente y abrir la conexion son lo caro, y si
    ocurrieran despues de la barrera producirian una fila justo donde no puede
    haberla. Aqui pasa en el calentamiento, igual que `casos_k.py`.
    """

    def __init__(self, endpoint: str, entorno: dict, ahora):
        self.endpoint = endpoint
        self.entorno = entorno
        self.ahora = ahora
        self._local = threading.local()

    @property
    def deps(self):
        if not hasattr(self._local, "deps"):
            cliente = dynamodb.crear_cliente(self.endpoint)
            cliente.describe_table(TableName=config.TABLA)  # abre la conexion
            self._local.deps = entrada.dependencias(
                entorno=self.entorno, cliente=cliente
            )
        return self._local.deps

    def enviar(self, metodo, ruta, cuerpo=None, token=None):
        respuesta = atender(
            borde.PeticionHttp(
                ruta=ruta,
                metodo=metodo,
                cuerpo=cuerpo or {},
                autorizacion=token,
                origen=IP,
            ),
            self.deps,
            self.ahora,
        )
        return respuesta.codigo, respuesta.cuerpo


@pytest.fixture()
def transporte(endpoint, tabla, t0):
    entorno = {
        "RESERVAS_UNIDADES_ACTIVAS": ",".join(tabla.activas),
        "RESERVAS_ESPACIOS": ",".join(tabla.espacios),
        "RESERVAS_VENTANA_SEGUNDOS": "300",
        "RESERVAS_TOPE_POR_IDENTIDAD": "5",
        "RESERVAS_TOPE_POR_ORIGEN": "2",
        "RESERVAS_CAPACIDAD_DEL_BORDE": str(len(tabla.activas) * 5),
        "RESERVAS_ENFRIAMIENTO_SEGUNDOS": "1",
        "RESERVAS_ORIGEN_PERMITIDO": "https://reservas-demo.example",
        "RESERVAS_CLAVE_FIRMA": "clave-de-prueba-no-es-un-secreto",
    }
    return TransporteEnProceso(endpoint, entorno, t0)


def test_el_instrumento_produce_la_carrera_y_solo_una_confirma(transporte, t0):
    """**C1, comprobado por el camino del desconocido.**

    Cincuenta identidades distintas, una franja, una confirmacion. Y con
    evidencia de que compitieron: al menos un RR-11, que solo puede existir si
    una condicion fallo sobre una franja que la lectura vio libre.
    """
    inicio = tiempo.instante_mas(t0, 1, 10)

    medicion = ins.ejecutar(transporte, espacio=ESPACIO, inicio=inicio, n=N)
    print("\n" + ins.informe(medicion, ESPACIO, inicio))

    assert medicion.identidades_obtenidas == N, "el dispensador no dio las 50"
    assert medicion.desglose.confirmadas == 1, (
        f"{medicion.desglose.confirmadas} confirmadas sobre la misma franja. "
        "Si son 2 o mas, esto ES la doble reserva y la afirmacion central del "
        "proyecto es falsa"
    )
    assert medicion.simultaneidad.s1_max_en_vuelo > 1, (
        "ninguna solicitud coincidio con otra: llegaron en fila y esto no midio "
        "concurrencia"
    )
    assert medicion.valida, (
        "medicion invalida: " + " · ".join(medicion.motivos_invalidez)
    )
    assert medicion.simultaneidad.s3_rr11 >= 1


def test_ninguna_solicitud_muere_por_identidad_ni_por_tasa(transporte, t0):
    """I-3 de los invariantes: **validez de la medicion.**

    Un `SYS-IDENTIDAD` o un `SYS-TASA` significan que el instrumento se monto
    mal —reutilizo identidades, o el tope quedo por debajo de lo que necesita—.
    No refutan el sistema: invalidan la corrida. Que salgan cero es lo que hace
    publicable el resultado anterior.
    """
    inicio = tiempo.instante_mas(t0, 2, 11)
    medicion = ins.ejecutar(transporte, espacio=ESPACIO, inicio=inicio, n=N)

    from reservas.desenlaces import Cubo

    assert medicion.desglose.por_cubo[Cubo.SYS_IDENTIDAD] == 0
    assert medicion.desglose.por_cubo[Cubo.SYS_TASA] == 0


def test_el_enfriamiento_frena_la_segunda_ejecucion_seguida(transporte, t0):
    """D-CE4-1 contra la tabla, no contra un doble.

    Dos ejecuciones seguidas dentro de la misma ventana: la segunda no llega a
    pedir el lote. Y **lo declara como enfriamiento, no como fallo**, que es la
    diferencia entre "vuelve en veinte segundos" y "esto esta roto".
    """
    primera = ins.ejecutar(
        transporte, espacio=ESPACIO, inicio=tiempo.instante_mas(t0, 3, 12), n=N
    )
    assert primera.identidades_obtenidas == N

    segunda = ins.ejecutar(
        transporte, espacio=ESPACIO, inicio=tiempo.instante_mas(t0, 4, 12), n=N
    )

    assert not segunda.valida
    assert any("enfriando" in m for m in segunda.motivos_invalidez)
    assert not segunda.doble_reserva, "un enfriamiento no es una doble reserva"
    assert segunda.simultaneidad.lanzadas == 0, (
        "se lanzaron solicitudes pese al enfriamiento: el freno llego tarde"
    )


def test_sin_carrera_el_instrumento_declara_medicion_invalida(transporte, t0):
    """**RF-14, y es la propiedad que separa esto de un folleto.**

    Con una sola solicitud no hay con quien competir, asi que no puede haber
    RR-11. El sistema responde perfectamente —una confirmada, cero rechazos— y
    aun asi el instrumento se niega a publicarlo como evidencia de C1, porque no
    lo es. Un instrumento que diera verde aqui daria verde tambien el dia que
    las cincuenta llegaran en fila, que es el fallo fatal n.o 1 del proyecto.
    """
    inicio = tiempo.instante_mas(t0, 5, 13)

    medicion = ins.ejecutar(transporte, espacio=ESPACIO, inicio=inicio, n=1)

    assert medicion.desglose.confirmadas == 1  # el sistema hizo lo correcto
    assert not medicion.valida
    assert any("RR-11" in m for m in medicion.motivos_invalidez)
