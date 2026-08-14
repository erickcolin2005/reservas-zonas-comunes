"""El camino de escritura completo, y sobre todo SU ORDEN.

Estas pruebas no comprueban que los tres controles existan —eso ya lo hacen
`test_prestamo.py` y `test_contador.py`—. Comprueban que estan **encadenados en
el orden correcto**, que es una propiedad distinta y que ninguna de las dos
suites anteriores puede ver.

Corren **sin motor, sin red y sin nube**: el adaptador es un falso en memoria.
Es deliberado, y por la misma razon que el banco de I-4 corre asi: el orden de
los controles es una propiedad del codigo, no del despliegue, y una prueba que
necesitara Docker para comprobarla acabaria corriendose menos.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from reservas.adaptadores import borde
from reservas.casos_uso.atender import Dependencias, atender
from reservas.desenlaces import Cubo
from reservas.nucleo import tiempo
from reservas.nucleo.modelo import (
    EstadoLeido,
    Franja,
    OcupacionLeida,
    TipoOcupacion,
    Unidad,
)
from reservas.puertos import ResultadoEscritura, TipoResultado
from reservas.sembrado import ESPACIOS
from reservas.seguridad import prestamo as p
from reservas.seguridad.contador import ContadorIntentos, EnfriamientoActivo
from reservas.seguridad.prestamo import Dispensador, emitir

ORIGEN = "https://reservas-demo.example"
CLAVE = b"clave-de-prueba-que-no-es-ningun-secreto-real"
ESPACIO = ESPACIOS[2]  # E-CAN: 1-2 franjas, 2 h de antelacion, horizonte 7 dias

AHORA = tiempo.instante_local(2026, 9, 7, 8, 0)
INICIO = tiempo.instante_local(2026, 9, 8, 10, 0)  # 26 h despues: valido


class FalsoAdaptador:
    """Un motor de mentira que ANOTA lo que le piden.

    Lo que hace falta para estas pruebas no es un motor: es un testigo. Si
    `atender` llega a tocarlo cuando no debia, `llamadas` lo delata.
    """

    def __init__(self, unidad_activa=True, ocupacion=None, cupo_consumido=0):
        self.llamadas: list[str] = []
        self.unidad_activa = unidad_activa
        self.ocupacion = ocupacion or {}
        self.cupo_consumido = cupo_consumido
        self.confirmadas: list[str] = []

    def leer_estado(self, solicitud) -> EstadoLeido:
        self.llamadas.append("leer_estado")
        unidad = (
            Unidad(id=solicitud.unidad, activa=True, grupo="RAFAGA")
            if self.unidad_activa
            else None
        )
        return EstadoLeido(
            parametros=ESPACIO,
            unidad=unidad,
            ocupacion=self.ocupacion,
            agenda={},
            cupo_consumido=self.cupo_consumido,
        )

    def intentar_confirmar(self, intencion, token, id_reserva) -> ResultadoEscritura:
        self.llamadas.append("intentar_confirmar")
        self.confirmadas.append(intencion.solicitud.unidad)
        return ResultadoEscritura(tipo=TipoResultado.ACEPTADA, id_reserva=id_reserva)

    def leer_ocupacion(self, franjas, espacio):
        self.llamadas.append("leer_ocupacion")
        return {}

    def leer_ocupacion_dia(self, espacio, dia):
        self.llamadas.append("leer_ocupacion_dia")
        return self.ocupacion

    def leer_espacio(self, identificador):
        self.llamadas.append("leer_espacio")
        return ESPACIO if identificador == ESPACIO.id else None

    def leer_espacios(self, ids):
        self.llamadas.append("leer_espacios")
        return [ESPACIO for i in ids if i == ESPACIO.id]


def deps(
    adaptador=None, tope=10, tope_por_origen=2, enfriamiento=None
) -> Dependencias:
    return Dependencias(
        clave=CLAVE,
        adaptador=adaptador or FalsoAdaptador(),
        contador=ContadorIntentos(ventana=timedelta(minutes=5), tope=tope),
        dispensador=Dispensador(
            activas=("U-101", "U-102", "U-103"),
            clave=CLAVE,
            tope_por_origen=tope_por_origen,
        ),
        espacios=(ESPACIO.id,),
        origen_permitido=ORIGEN,
        enfriamiento=enfriamiento,
    )


def peticion_reserva(token: str | None, **cuerpo) -> borde.PeticionHttp:
    base = {"espacio": ESPACIO.id, "inicio": INICIO.isoformat(), "n_franjas": 1}
    base.update(cuerpo)
    return borde.PeticionHttp(
        ruta="/reservas", metodo="POST", cuerpo=base, autorizacion=token
    )


def token_de(unidad: str = "U-101") -> str:
    return emitir(unidad, CLAVE, AHORA)


# ---------------------------------------------------------------------------
# EL ORDEN. Las dos pruebas que justifican que este fichero exista.
# ---------------------------------------------------------------------------


def test_un_token_falso_no_gasta_la_cuota_de_la_unidad_que_dice_ser():
    """**Autorizar va ANTES de contar**, y esto es lo que pasa si no.

    Un desconocido firma un token con una clave que no es la buena, poniendo
    dentro `U-101`. Si el contador corriera primero, el intento quedaria anotado
    contra `U-101` y solo despues la firma lo rechazaria: un desconocido podria
    agotar la cuota de cualquier residente, gratis y sin credenciales. Es
    negacion de servicio por identidad ajena.
    """
    d = deps()
    falsificado = emitir("U-101", b"otra-clave-distinta-de-la-buena", AHORA)

    respuesta = atender(peticion_reserva(falsificado), d, AHORA)

    assert respuesta.codigo == 401
    assert respuesta.cuerpo["resultado"] == Cubo.SYS_IDENTIDAD.value
    assert d.contador.consumido("U-101", AHORA) == 0, (
        "el token no era valido y aun asi consumio cuota de U-101: el contador "
        "corrio antes que el autorizador"
    )


def test_un_rechazo_por_regla_consume_cuota_igual_que_una_confirmacion():
    """**Contar va ANTES de evaluar** (ADR-29).

    Se cuentan INTENTOS, no confirmaciones. Si el contador corriera despues de
    la evaluacion, quien quisiera agotar el sistema lo haria con solicitudes que
    se rechazan —que no costarian cuota y si costarian lecturas— y el techo
    `50 x tope` se quedaria sin fondo.
    """
    d = deps(FalsoAdaptador(unidad_activa=False))

    respuesta = atender(peticion_reserva(token_de()), d, AHORA)

    assert respuesta.codigo == 200
    assert respuesta.cuerpo["regla"] == "RR-01"
    assert d.contador.consumido("U-101", AHORA) == 1, (
        "un intento rechazado por regla no quedo contado"
    )


def test_cuando_el_contador_topa_el_motor_no_se_toca():
    """El contador va **fuera** de la transaccion y antes de las lecturas.

    Una solicitud que topa no debe costar ni una lectura: si costara, el limite
    de tasa seria mas caro de aplicar que de saltarse.
    """
    adaptador = FalsoAdaptador()
    d = deps(adaptador, tope=1)

    primera = atender(peticion_reserva(token_de()), d, AHORA)
    adaptador.llamadas.clear()
    segunda = atender(peticion_reserva(token_de()), d, AHORA)

    assert primera.codigo == 200
    assert segunda.codigo == 429
    assert segunda.cuerpo["resultado"] == Cubo.SYS_TASA.value
    assert adaptador.llamadas == [], (
        f"el motor se toco pese a topar la cuota: {adaptador.llamadas}"
    )


# ---------------------------------------------------------------------------
# SEC-2 · la identidad se prueba, y el rol se comprueba POR RUTA
# ---------------------------------------------------------------------------


def test_un_token_de_administracion_bien_firmado_no_abre_la_ruta_de_residente():
    """Que el token sea autentico dice quien eres, no que puedas hacer esto.

    `emitir` se niega a producir rol de administracion (D-SEC-4), asi que este
    token se fabrica firmando a mano —que es exactamente lo que haria quien se
    hiciera con la clave—. La firma es buena. El rol, no.
    """
    cabecera = p._b64(json.dumps({"alg": p.ALGORITMO, "typ": "prestamo"}).encode())
    cuerpo = p._b64(
        json.dumps(
            {
                "unidad": "U-101",
                "rol": p.ROL_ADMINISTRACION,
                "emitido": int(AHORA.timestamp()),
                "expira": int((AHORA + timedelta(minutes=15)).timestamp()),
            }
        ).encode()
    )
    partes = f"{cabecera}.{cuerpo}"
    forjado = f"{partes}.{p._firmar(partes.encode(), CLAVE)}"

    # El token es verificable: el problema no es la firma.
    assert p.verificar(forjado, CLAVE, AHORA).rol == p.ROL_ADMINISTRACION

    d = deps()
    respuesta = atender(peticion_reserva(forjado), d, AHORA)

    assert respuesta.codigo == 401
    assert d.contador.consumido("U-101", AHORA) == 0


def test_sin_token_no_se_llega_a_ninguna_parte():
    d = deps()
    respuesta = atender(peticion_reserva(None), d, AHORA)
    assert respuesta.codigo == 401
    assert respuesta.cuerpo["resultado"] == Cubo.SYS_IDENTIDAD.value


def test_un_token_caducado_se_rechaza_sin_decir_que_caduco():
    """El motivo no viaja: distinguir "firma mala" de "caducado" le diria a
    quien prueba cual de las dos cosas tiene que arreglar."""
    d = deps()
    viejo = emitir("U-101", CLAVE, AHORA - timedelta(hours=2))

    respuesta = atender(peticion_reserva(viejo), d, AHORA)

    assert respuesta.codigo == 401
    assert set(respuesta.cuerpo) == {"resultado"}
    assert "caduc" not in json.dumps(respuesta.cuerpo).lower()


def test_la_unidad_del_cuerpo_no_decide_nada():
    """S-01. La unidad sale del prestamo verificado (ADR-26).

    El cuerpo puede traer `unidad` —nadie lo impide, es JSON— y aun asi la
    reserva se hace a nombre de quien firma el token.
    """
    adaptador = FalsoAdaptador()
    d = deps(adaptador)

    respuesta = atender(
        peticion_reserva(token_de("U-102"), unidad="U-999"), d, AHORA
    )

    assert respuesta.codigo == 200
    assert adaptador.confirmadas == ["U-102"], (
        "la reserva se hizo a nombre de la unidad del cuerpo"
    )


def test_el_token_en_claro_nunca_aparece_en_la_respuesta():
    d = deps()
    token = token_de()
    respuesta = atender(peticion_reserva(token), d, AHORA)
    assert token not in json.dumps(respuesta.cuerpo)


# ---------------------------------------------------------------------------
# La frontera del 200, ya sobre el camino completo
# ---------------------------------------------------------------------------


def test_una_hora_fuera_de_rejilla_se_informa_como_RR03_y_no_como_error():
    """La rejilla la impone la canonizacion, antes de que exista una Solicitud.

    Se informa RR-03 porque es la misma regla que lo rechazaria si llegara al
    nucleo. Un 400 aqui haria que el mismo error tuviera dos formas segun donde
    se detectara, y un cliente no puede tratar eso.
    """
    d = deps()
    respuesta = atender(
        peticion_reserva(token_de(), inicio="2026-09-08T10:30"), d, AHORA
    )
    assert respuesta.codigo == 200
    assert respuesta.cuerpo["regla"] == "RR-03"


def test_un_fallo_no_previsto_es_500_sin_traza_ni_mensaje():
    """El ultimo dique. Lo que no puede pasar es que el texto de una excepcion
    del motor acabe en el cuerpo (RNF-12, SEC-6)."""

    class AdaptadorQueRevienta(FalsoAdaptador):
        def leer_estado(self, solicitud):
            raise RuntimeError(
                "ConditionalCheckFailedException sobre la tabla reservas-zonas-comunes"
            )

    d = deps(AdaptadorQueRevienta())
    respuesta = atender(peticion_reserva(token_de()), d, AHORA)

    texto = json.dumps(respuesta.cuerpo)
    assert respuesta.codigo == 500
    assert respuesta.cuerpo["resultado"] == Cubo.OTRO.value
    assert "ConditionalCheck" not in texto
    assert "reservas-zonas-comunes" not in texto


@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("POST", "/admin/bloqueos"),
        ("POST", "/admin/reservas/{id}/cancelacion"),
        ("POST", "/reservas/{id}/cancelacion"),
        ("GET", "/reservas"),
        ("GET", "/no/existe"),
    ],
)
def test_una_ruta_no_implementada_responde_igual_que_una_inexistente(metodo, ruta):
    """404 las dos. Distinguir "todavia no" de "no existe" le diria a un
    desconocido que hay superficie por venir."""
    d = deps()
    respuesta = atender(
        borde.PeticionHttp(ruta=ruta, metodo=metodo, autorizacion=token_de()), d, AHORA
    )
    assert respuesta.codigo == 404
    assert respuesta.cuerpo == {"resultado": "no-existe"}


def test_el_origen_declarado_viaja_en_toda_respuesta():
    d = deps()
    for peticion in (
        peticion_reserva(token_de()),
        peticion_reserva(None),
        borde.PeticionHttp(ruta="/no/existe", metodo="GET"),
    ):
        respuesta = atender(peticion, d, AHORA)
        assert respuesta.cabeceras["Access-Control-Allow-Origin"] == ORIGEN


# ---------------------------------------------------------------------------
# Las rutas de lectura: publicas, y sin decir de quien es cada franja
# ---------------------------------------------------------------------------


def test_el_calendario_se_lee_sin_token():
    """H5 lo necesita fluido. Limitar la lectura por identidad dejaria el
    calendario publico detras de un prestamo."""
    d = deps()
    respuesta = atender(borde.PeticionHttp(ruta="/espacios", metodo="GET"), d, AHORA)
    assert respuesta.codigo == 200
    assert [e["id"] for e in respuesta.cuerpo["espacios"]] == [ESPACIO.id]


def test_el_catalogo_publica_los_parametros_porque_son_la_causa_de_cada_rechazo():
    """C3: un RR-05 sin saber la antelacion exigida es un "no" sin causa."""
    d = deps()
    respuesta = atender(borde.PeticionHttp(ruta="/espacios", metodo="GET"), d, AHORA)
    espacio = respuesta.cuerpo["espacios"][0]
    assert espacio["antelacion_minima_horas"] == ESPACIO.antelacion_minima_horas
    assert espacio["duracion_minima"] == ESPACIO.duracion_minima
    assert espacio["cupo"] == ESPACIO.cupo


def test_la_disponibilidad_dice_que_esta_ocupado_y_nunca_por_quien():
    """S-03 en el camino de lectura.

    Es el mismo requisito que `test_borde.py` comprueba sobre RR-10, y hay que
    comprobarlo tambien aqui: el rechazo y el calendario son dos sitios
    distintos por donde podria escaparse la misma informacion.
    """
    dia = INICIO.date()
    ocupacion = {
        Franja(dia, 10): OcupacionLeida(
            tipo=TipoOcupacion.RESERVA, id_reserva="r-abc123", unidad="U-104"
        ),
        Franja(dia, 12): OcupacionLeida(
            tipo=TipoOcupacion.BLOQUEO, id_reserva=None, unidad=None
        ),
    }
    d = deps(FalsoAdaptador(ocupacion=ocupacion))

    respuesta = atender(
        borde.PeticionHttp(
            ruta="/espacios/{id}/disponibilidad",
            metodo="GET",
            cuerpo={"dia": dia.isoformat()},
            parametros_ruta={"id": ESPACIO.id},
        ),
        d,
        AHORA,
    )

    assert respuesta.codigo == 200
    por_hora = {f["hora"]: f["estado"] for f in respuesta.cuerpo["franjas"]}
    assert por_hora[10] == "ocupada"
    assert por_hora[12] == "mantenimiento"
    assert por_hora[11] == "libre"

    texto = json.dumps(respuesta.cuerpo)
    assert "U-104" not in texto, "el calendario publico revelo la unidad ocupante"
    assert "r-abc123" not in texto


def test_un_espacio_no_declarado_no_se_distingue_de_uno_inexistente():
    d = deps()
    respuesta = atender(
        borde.PeticionHttp(
            ruta="/espacios/{id}/disponibilidad",
            metodo="GET",
            cuerpo={"dia": INICIO.date().isoformat()},
            parametros_ruta={"id": "E-NO-EXISTE"},
        ),
        d,
        AHORA,
    )
    assert respuesta.codigo == 404
    assert respuesta.cuerpo == {"resultado": "no-existe"}


# ---------------------------------------------------------------------------
# El dispensador — la unica ruta con limite por origen (D-SEC-6)
# ---------------------------------------------------------------------------


def test_el_dispensador_presta_un_lote_y_avisa_de_que_los_datos_son_sinteticos():
    d = deps()
    respuesta = atender(
        borde.PeticionHttp(
            ruta="/demo/credenciales",
            metodo="POST",
            cuerpo={"cantidad": 3},
            origen="203.0.113.7",
        ),
        d,
        AHORA,
    )
    assert respuesta.codigo == 200
    assert len(respuesta.cuerpo["credenciales"]) == 3
    assert len({c["unidad"] for c in respuesta.cuerpo["credenciales"]}) == 3
    assert "sinteticas" in respuesta.cuerpo["aviso"]


def test_la_cuota_por_origen_y_el_lote_imposible_responden_lo_mismo():
    """Las dos causas de `IdentidadNoPrestable` dan la misma respuesta.

    Distinguirlas le diria a quien sondea el tamano del conjunto cerrado o
    cuanta cuota le queda.
    """
    d = deps(tope_por_origen=1)
    peticion = borde.PeticionHttp(
        ruta="/demo/credenciales",
        metodo="POST",
        cuerpo={"cantidad": 2},
        origen="203.0.113.7",
    )
    assert atender(peticion, d, AHORA).codigo == 200

    agotada = atender(peticion, d, AHORA)  # cuota de origen gastada
    imposible = atender(
        borde.PeticionHttp(
            ruta="/demo/credenciales",
            metodo="POST",
            cuerpo={"cantidad": 999},
            origen="198.51.100.4",
        ),
        d,
        AHORA,
    )

    assert agotada.codigo == imposible.codigo == 429
    assert agotada.cuerpo == imposible.cuerpo


class EnfriamientoFalso:
    """Deja pasar `admitidas` ejecuciones y despues se niega."""

    def __init__(self, admitidas=1):
        self.restantes = admitidas
        self.llamadas = 0

    def consumir(self, ahora):
        self.llamadas += 1
        if self.restantes <= 0:
            raise EnfriamientoActivo("todavia no toca")
        self.restantes -= 1


def peticion_lote(cantidad=2, origen="203.0.113.7") -> borde.PeticionHttp:
    return borde.PeticionHttp(
        ruta="/demo/credenciales",
        metodo="POST",
        cuerpo={"cantidad": cantidad},
        origen=origen,
    )


def test_el_enfriamiento_corta_la_segunda_ejecucion_seguida():
    """D-CE4-1. Una ejecucion son ~400 WCU de golpe sobre 25 sostenidos:
    funciona por el deposito de rafaga, y el deposito se agota."""
    d = deps(enfriamiento=EnfriamientoFalso(admitidas=1))

    assert atender(peticion_lote(), d, AHORA).codigo == 200
    segunda = atender(peticion_lote(), d, AHORA)

    assert segunda.codigo == 429
    assert segunda.cuerpo["resultado"] == "enfriamiento"


def test_el_enfriamiento_se_distingue_de_las_demas_negativas():
    """A diferencia de las dos causas de `IdentidadNoPrestable`, esta SI se
    nombra: no hay nada que sondear —el enfriamiento va en el README— y el
    instrumento necesita distinguirlo para no informar como fallo del sistema
    lo que es un «vuelve en veinte segundos»."""
    frenada = atender(
        peticion_lote(), deps(enfriamiento=EnfriamientoFalso(admitidas=0)), AHORA
    )

    sin_enfriamiento = deps(tope_por_origen=1)
    atender(peticion_lote(), sin_enfriamiento, AHORA)  # gasta la cuota
    agotada = atender(peticion_lote(), sin_enfriamiento, AHORA)

    assert frenada.codigo == agotada.codigo == 429
    assert frenada.cuerpo["resultado"] == "enfriamiento"
    assert agotada.cuerpo["resultado"] == "no-prestable"


def test_el_enfriamiento_va_antes_de_gastar_la_cuota_de_origen():
    """Si fuera despues, una ejecucion frenada habria gastado igual la cuota del
    solicitante: le cobrariamos un lote que nunca recibio."""
    frenado = EnfriamientoFalso(admitidas=0)
    d = deps(tope_por_origen=2, enfriamiento=frenado)

    for _ in range(3):
        assert atender(peticion_lote(), d, AHORA).codigo == 429

    # Cuota intacta: pasado el enfriamiento, los dos lotes siguen disponibles.
    frenado.restantes = 2
    assert atender(peticion_lote(), d, AHORA).codigo == 200
    assert atender(peticion_lote(), d, AHORA).codigo == 200


def test_sin_enfriamiento_configurado_el_dispensador_funciona_igual():
    """`None` es valido y es lo que usan las pruebas. Que sea falso en un
    despliegue lo vigila `test_entrada.py`, no esto."""
    d = deps()
    assert d.enfriamiento is None
    assert atender(peticion_lote(), d, AHORA).codigo == 200


def test_el_dispensador_no_exige_token_pero_tampoco_lo_usa_para_nada():
    """Es la puerta de entrada: pedir credenciales para poder pedir credenciales
    dejaria al instrumento sin forma de arrancar."""
    d = deps()
    respuesta = atender(
        borde.PeticionHttp(
            ruta="/demo/credenciales",
            metodo="POST",
            cuerpo={"cantidad": 1},
            origen="203.0.113.9",
        ),
        d,
        AHORA,
    )
    assert respuesta.codigo == 200
