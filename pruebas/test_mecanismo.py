"""El mecanismo contra el motor: escritura condicional y transaccion.

Lo que aqui se comprueba no es la carrera —eso son los casos K— sino las piezas
sueltas del mecanismo, una a una, para que cuando un caso K falle se sepa cual
de ellas se rompio.
"""

from __future__ import annotations

import pytest

from reservas import config, sembrado
from reservas.adaptadores import dynamodb
from reservas.casos_uso.reservar import reservar
from reservas.desenlaces import Cubo
from reservas.nucleo import claves, tiempo
from reservas.nucleo.modelo import Solicitud, TipoOcupacion
from reservas.puertos import TipoResultado

pytestmark = pytest.mark.motor


def solicitud(t0, unidad="U-101", espacio="E-CAN", dia=4, hora=10, franjas=1):
    return Solicitud(unidad, espacio, tiempo.instante_mas(t0, dia, hora), franjas)


# ---------------------------------------------------------------------------
# El hueco ES el item
# ---------------------------------------------------------------------------


def test_una_reserva_confirmada_crea_un_item_por_franja(tabla, adaptador, t0, cliente):
    """Si el item existe, la franja esta tomada; si no existe, esta libre. No
    hay tercer estado, y por eso no puede haber discrepancia entre "lo que dice
    la tabla" y "lo que esta reservado": son la misma cosa."""
    peticion = solicitud(t0, espacio="E-SAL", dia=6, hora=10, franjas=4)
    desenlace = reservar(peticion, adaptador, t0)
    assert desenlace.cubo is Cubo.CONFIRMADA, desenlace

    ocupadas = adaptador.leer_ocupacion_dia("E-SAL", tiempo.dia_mas(t0, 6))
    assert sorted(f.hora for f in ocupadas) == [10, 11, 12, 13]
    assert all(o.tipo is TipoOcupacion.RESERVA for o in ocupadas.values())
    assert {o.unidad for o in ocupadas.values()} == {"U-101"}


def test_la_segunda_reserva_de_la_misma_franja_se_rechaza_con_rr10(tabla, adaptador, t0):
    """Secuencial, no concurrente: la segunda VE la primera al leer, luego es
    RR-10. Es la ruta de codigo que RR-11 no comparte."""
    assert reservar(solicitud(t0), adaptador, t0).cubo is Cubo.CONFIRMADA
    segunda = reservar(solicitud(t0, unidad="U-102"), adaptador, t0)
    assert segunda.cubo is Cubo.RECHAZADA_REGLA
    assert segunda.regla == "RR-10", segunda


def test_la_adyacencia_no_choca(tabla, adaptador, t0):
    """`[10:00,11:00)` y `[11:00,12:00)` conviven: no comparten clave."""
    assert reservar(solicitud(t0), adaptador, t0).cubo is Cubo.CONFIRMADA
    contigua = reservar(solicitud(t0, unidad="U-102", hora=11), adaptador, t0)
    assert contigua.cubo is Cubo.CONFIRMADA, contigua


# ---------------------------------------------------------------------------
# La transaccion: todo o nada
# ---------------------------------------------------------------------------


def test_una_solicitud_que_pierde_una_sola_franja_no_escribe_ninguna(
    tabla, adaptador, t0
):
    """Es lo que hace cierto RF-11 y lo que cierra K-02.

    Si las franjas se escribieran una a una, esta solicitud se quedaria con tres
    de sus cuatro franjas sin confirmar nada, y esas tres quedarian tomadas por
    una reserva que no existe.
    """
    # U-101 toma la franja de las 13 con una reserva de 4 franjas 13-17.
    assert (
        reservar(
            solicitud(t0, espacio="E-SAL", dia=6, hora=13, franjas=4), adaptador, t0
        ).cubo
        is Cubo.CONFIRMADA
    )
    antes = adaptador.leer_ocupacion_dia("E-SAL", tiempo.dia_mas(t0, 6))

    # U-102 pide 10-14: solo choca en la de las 13.
    perdedora = reservar(
        solicitud(t0, unidad="U-102", espacio="E-SAL", dia=6, hora=10, franjas=4),
        adaptador,
        t0,
    )
    assert perdedora.cubo is Cubo.RECHAZADA_REGLA
    despues = adaptador.leer_ocupacion_dia("E-SAL", tiempo.dia_mas(t0, 6))
    assert despues.keys() == antes.keys(), (
        "el rechazo dejo rastro sobre franjas que no llego a ganar: "
        f"{sorted(str(f) for f in despues.keys() - antes.keys())}"
    )


def test_el_cupo_se_cierra_con_el_mismo_acto_que_la_franja(tabla, adaptador, t0):
    """La segunda carrera. E-SAL tiene cupo 1 al mes: la segunda reserva de la
    misma unidad se rechaza aunque su franja este libre."""
    primera = reservar(
        solicitud(t0, espacio="E-SAL", dia=6, hora=10, franjas=4), adaptador, t0
    )
    assert primera.cubo is Cubo.CONFIRMADA
    segunda = reservar(
        solicitud(t0, espacio="E-SAL", dia=7, hora=10, franjas=4), adaptador, t0
    )
    assert segunda.regla == "RR-07", segunda


def test_el_maximo_del_modelo_son_catorce_items(tabla, adaptador, t0):
    """6 franjas + 6 de agenda + 1 de cupo + 1 de cabecera. E-SAL al maximo.

    El diseno queda por debajo de los limites por transaccion a proposito, para
    no depender de cual sea el valor exacto.
    """
    from reservas.nucleo import reglas

    peticion = solicitud(t0, espacio="E-SAL", dia=6, hora=10, franjas=6)
    estado = adaptador.leer_estado(peticion)
    veredicto = reglas.evaluar(peticion, estado, t0)
    items, mapa = adaptador.construir_items(veredicto.intencion, "tok", "id")
    assert len(items) == 14
    assert len(mapa) == 14


def test_la_agenda_de_la_unidad_impide_el_choque_consigo_misma(tabla, adaptador, t0):
    """RR-08 entre espacios distintos, cerrada por la condicion de AGENDA#."""
    assert (
        reservar(solicitud(t0, espacio="E-CAN", dia=4, hora=10), adaptador, t0).cubo
        is Cubo.CONFIRMADA
    )
    choque = reservar(
        solicitud(t0, espacio="E-BBQ", dia=4, hora=10, franjas=3), adaptador, t0
    )
    assert choque.regla == "RR-08", choque


# ---------------------------------------------------------------------------
# Idempotencia (ADR-25) y atribucion
# ---------------------------------------------------------------------------


def test_reintentar_la_transaccion_con_el_mismo_token_no_es_un_rechazo(
    tabla, adaptador, t0
):
    """RNF-11 / ADR-25, comprobado donde el mecanismo vive: en la transaccion.

    El item del hueco guarda el token de la solicitud que lo gano. Si la
    condicion falla y el item lleva MI token, la transaccion ya se aplico antes
    y esto es una repeticion, no un rechazo. Idempotencia que no depende de
    ningun mecanismo del motor que no se pueda verificar.
    """
    from reservas.nucleo import reglas

    peticion = solicitud(t0)
    estado = adaptador.leer_estado(peticion)
    intencion = reglas.evaluar(peticion, estado, t0).intencion

    primero = adaptador.intentar_confirmar(intencion, "tok-fijo", "id-fijo")
    assert primero.tipo is TipoResultado.ACEPTADA

    segundo = adaptador.intentar_confirmar(intencion, "tok-fijo", "id-fijo")
    assert segundo.tipo is TipoResultado.CONDICION_INCUMPLIDA
    devuelto = next(
        f.item_devuelto for f in segundo.items_en_fallo if f.item_devuelto
    )
    assert devuelto["token_solicitud"]["S"] == "tok-fijo", (
        "el item ganador no lleva mi token, luego no hay forma de distinguir "
        "'ya lo gane yo' de 'me lo gano otro'"
    )


def test_repetir_la_solicitud_ENTERA_choca_antes_con_rr08_y_eso_es_un_hueco(
    tabla, adaptador, t0
):
    """HALLAZGO. La idempotencia de ADR-25 es INALCANZABLE por el camino normal.

    Una repeticion de la misma solicitud por la misma unidad encuentra su propia
    entrada en `AGENDA#` durante la LECTURA PREVIA, y RR-08 la rechaza antes de
    llegar a la condicion donde vive el token. Es decir: un cliente que reintente
    tras perder la respuesta recibe **RR-08** en vez de la confirmacion que
    RNF-11 promete.

    No es un defecto del codigo: es una interaccion entre ADR-19 (agenda atomica)
    y ADR-25 (idempotencia por token) que ningun documento de F2 contempla. El
    mecanismo del token es correcto y funciona —lo prueba el caso de arriba—,
    pero el orden de evaluacion lo deja fuera de alcance mientras RR-08 sea
    atomica.

    Esta prueba fija el comportamiento observado para que el hueco no se pierda,
    y **no lo tapa**: si alguien decide que RNF-11 debe cumplirse por el camino
    normal, esta prueba se pondra en rojo y sera el sitio correcto para
    enterarse. Sube a `architect-agent`.
    """
    peticion = solicitud(t0)
    primero = reservar(peticion, adaptador, t0, token_solicitud="tok-fijo")
    segundo = reservar(peticion, adaptador, t0, token_solicitud="tok-fijo")
    assert primero.cubo is Cubo.CONFIRMADA
    assert segundo.cubo is Cubo.RECHAZADA_REGLA
    assert segundo.regla == "RR-08", (
        "cambio el comportamiento del reintento: revisar RNF-11 y ADR-25"
    )


def test_un_token_distinto_sobre_la_misma_franja_si_es_un_rechazo(
    tabla, adaptador, t0
):
    """La otra mitad: el token responde "¿quien tiene la franja?", no "¿entre yo
    en la carrera?". Confundirlas es el error que ADR-04 previene."""
    peticion = solicitud(t0)
    assert reservar(peticion, adaptador, t0, token_solicitud="tok-a").cubo is Cubo.CONFIRMADA
    otra = reservar(
        solicitud(t0, unidad="U-102"), adaptador, t0, token_solicitud="tok-b"
    )
    assert otra.cubo is Cubo.RECHAZADA_REGLA
    assert otra.regla == "RR-10"


def test_una_franja_bloqueada_se_informa_como_rr09_y_no_como_rr11(
    tabla, adaptador, t0, cliente
):
    """Reserva y bloqueo comparten primitivo (ADR-17), pero no clase de rechazo.

    Una franja bloqueada no esta "ocupada por otro residente", y decirlo
    filtraria informacion falsa.
    """
    franja = tiempo.instante_mas(t0, 4, 10)
    cliente.put_item(
        TableName=config.TABLA,
        Item={
            "PK": dynamodb.S(claves.pk_hueco("E-CAN", franja.date())),
            "SK": dynamodb.S(claves.sk_hueco(franja.hour)),
            "tipo": dynamodb.S(TipoOcupacion.BLOQUEO.value),
        },
    )
    desenlace = reservar(solicitud(t0), adaptador, t0)
    assert desenlace.regla == "RR-09", desenlace


# ---------------------------------------------------------------------------
# La canonizacion, contra el motor y no solo en memoria
# ---------------------------------------------------------------------------


def test_dos_normalizaciones_distintas_producirian_dos_reservas_del_mismo_hueco(
    tabla, adaptador, t0, cliente
):
    """La demostracion contra el motor de que el peligro es real.

    Se escriben a mano las dos claves que producirian dos implementaciones que
    normalizan distinto —una en local, otra en UTC— para el MISMO hueco. Las dos
    escrituras condicionales se aceptan, porque el motor solo garantiza unicidad
    **sobre la clave**, no sobre el hueco.

    Esto no prueba un defecto del sistema: prueba que la canonizacion es carga
    estructural. Es la razon de que tenga pruebas propias y de que exista la
    mutacion M-b.
    """
    inicio = tiempo.instante_mas(t0, 4, 10)
    en_utc = inicio.astimezone(tiempo.timezone.utc)

    clave_local = {
        "PK": dynamodb.S(claves.pk_hueco("E-CAN", inicio.date())),
        "SK": dynamodb.S(claves.sk_hueco(inicio.hour)),
    }
    clave_utc = {
        "PK": dynamodb.S(claves.pk_hueco("E-CAN", en_utc.date())),
        "SK": dynamodb.S(claves.sk_hueco(en_utc.hour)),
    }
    assert clave_local != clave_utc

    cliente.put_item(
        TableName=config.TABLA,
        Item=clave_local,
        ConditionExpression="attribute_not_exists(PK)",
    )
    # La segunda pasa. El motor hizo su trabajo; el hueco tiene dos nombres.
    cliente.put_item(
        TableName=config.TABLA,
        Item=clave_utc,
        ConditionExpression="attribute_not_exists(PK)",
    )

    # Y la unica defensa contra esto es que el sistema entero componga la clave
    # por un solo camino: el de `canonizar_inicio` + `claves`.
    for representacion in (
        inicio.isoformat(),
        en_utc.isoformat().replace("+00:00", "Z"),
        inicio.strftime("%Y-%m-%dT%H:%M"),
    ):
        momento = tiempo.canonizar_inicio(representacion)
        assert {
            "PK": dynamodb.S(claves.pk_hueco("E-CAN", momento.date())),
            "SK": dynamodb.S(claves.sk_hueco(momento.hour)),
        } == clave_local


# ---------------------------------------------------------------------------
# El adaptador devuelve lo que hace falta para atribuir
# ---------------------------------------------------------------------------


def test_el_adaptador_dice_que_item_incumplio_su_condicion(tabla, adaptador, t0):
    """Sin esto solo se podria decir "fallo algo", y un rechazo que no nombra su
    regla no cuenta como rechazo."""
    from reservas.nucleo import reglas

    peticion = solicitud(t0)
    assert reservar(peticion, adaptador, t0).cubo is Cubo.CONFIRMADA

    otra = solicitud(t0, unidad="U-102")
    estado = adaptador.leer_estado(otra)
    # Se salta la lectura a proposito: se quiere el fallo de la CONDICION.
    intencion = reglas.evaluar(
        otra, estado.__class__(estado.parametros, estado.unidad), t0
    ).intencion
    resultado = adaptador.intentar_confirmar(intencion, "tok", "id")
    assert resultado.tipo is TipoResultado.CONDICION_INCUMPLIDA
    fallos = [f for f in resultado.items_en_fallo]
    assert fallos, resultado
    assert fallos[0].franja is not None
    assert fallos[0].item_devuelto is not None, (
        "el motor no devolvio el item ganador; sin el hay que leer en el camino "
        "perdedor. Revisar V-2a hallazgo V2a-6"
    )
