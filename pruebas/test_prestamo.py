"""SEC-1 y SEC-2: el préstamo de identidades y su verificación.

Incluye **las cuatro pruebas negativas del autorizador** que el modelo de
amenazas exige (SEC-2, §13) y que el banco de reglas declara expresamente fuera
de su alcance: *no son reglas de reserva*.

Una prueba negativa aquí afirma la CLASE del fallo, igual que en el banco: no
basta con que el token sea rechazado, tiene que serlo **por la razón que se está
poniendo a prueba**. Un token caducado rechazado por firma mala no demuestra que
la caducidad funcione.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from reservas.seguridad import prestamo as p

CLAVE = b"clave-de-prueba-no-es-un-secreto-del-repositorio"
AHORA = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
ACTIVAS = tuple(f"U-{100 + i}" for i in range(50))


def _partes(token: str):
    c, b, f = token.split(".")
    return json.loads(p._de_b64(c)), json.loads(p._de_b64(b)), f


# ---------------------------------------------------------------------------
# Las cuatro pruebas negativas del autorizador (SEC-2)
# ---------------------------------------------------------------------------


def test_negativa_1_firma_que_no_corresponde():
    token = p.emitir("U-101", CLAVE, AHORA)
    with pytest.raises(p.TokenInvalido, match="firma"):
        p.verificar(token, b"otra-clave-distinta", AHORA)


def test_negativa_2a_alg_none_sin_firma():
    """El ataque clasico en su forma torpe: `alg: none` y firma vacia.

    **Esta prueba NO demuestra que se compruebe el algoritmo**, y decirlo importa
    porque la primera version de este fichero creia que si. Lo que la caza es la
    FIRMA: sin firma valida el token muere antes de que nadie mire la cabecera.
    La mutacion lo demostro: apagar la comprobacion de algoritmo dejaba esta
    prueba en verde.

    Se conserva porque el caso es real y hay que cubrirlo. Lo que aisla el
    algoritmo es la de abajo.
    """
    _, cuerpo, _ = _partes(p.emitir("U-101", CLAVE, AHORA))
    cab = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    cue = base64.urlsafe_b64encode(json.dumps(cuerpo).encode()).decode().rstrip("=")
    with pytest.raises(p.TokenInvalido, match="firma"):
        p.verificar(f"{cab}.{cue}.", CLAVE, AHORA)


def test_negativa_2b_algoritmo_cambiado_con_firma_VALIDA():
    """Confusion de algoritmo, aislada: la firma es CORRECTA y aun asi se rechaza.

    Este es el caso que la firma no puede atrapar, y por tanto el unico que
    demuestra que la comprobacion de algoritmo existe. Se construye un token
    firmado con la clave buena -asi que `compare_digest` lo acepta- pero
    declarando otro algoritmo en la cabecera.

    Un verificador que se fie del campo `alg` seguiria adelante. Uno que lo
    compare contra el UNICO aceptado, no.
    """
    cab = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS512", "typ": "prestamo"}).encode()
    ).decode().rstrip("=")
    cuerpo = {
        "unidad": "U-101", "rol": p.ROL_RESIDENTE,
        "emitido": int(AHORA.timestamp()),
        "expira": int((AHORA + timedelta(minutes=15)).timestamp()),
    }
    cue = base64.urlsafe_b64encode(json.dumps(cuerpo).encode()).decode().rstrip("=")
    firma = p._firmar(f"{cab}.{cue}".encode(), CLAVE)  # firma VALIDA

    # Control: la firma es realmente buena. Sin esto, un fallo de construccion
    # del token daria un rechazo por firma y la prueba pasaria sin probar nada.
    assert p._firmar(f"{cab}.{cue}".encode(), CLAVE) == firma

    with pytest.raises(p.TokenInvalido, match="algoritmo"):
        p.verificar(f"{cab}.{cue}.{firma}", CLAVE, AHORA)


def test_negativa_3_prestamo_caducado():
    token = p.emitir("U-101", CLAVE, AHORA, vigencia=timedelta(minutes=15))
    p.verificar(token, CLAVE, AHORA + timedelta(minutes=14))  # aun vale
    with pytest.raises(p.TokenInvalido, match="caducado"):
        p.verificar(token, CLAVE, AHORA + timedelta(minutes=16))


def test_negativa_4_el_rol_se_comprueba_por_ruta():
    """Un token AUTENTICO de residente no abre una ruta de administracion.

    Que el token sea valido dice quien eres, no que puedas hacer esto.
    """
    prestamo = p.verificar(p.emitir("U-101", CLAVE, AHORA), CLAVE, AHORA)
    p.exigir_rol(prestamo, p.ROL_RESIDENTE)
    with pytest.raises(p.TokenInvalido, match="no alcanza"):
        p.exigir_rol(prestamo, p.ROL_ADMINISTRACION)


# ---------------------------------------------------------------------------
# D-SEC-3 · el prestamo lleva lo justo, y no hay revocacion
# ---------------------------------------------------------------------------


def test_el_token_lleva_exactamente_cuatro_campos_y_ni_uno_mas():
    """Minimizacion. Cada campo de mas es un dato que viaja sin necesitarlo."""
    _, cuerpo, _ = _partes(p.emitir("U-101", CLAVE, AHORA))
    assert set(cuerpo) == {"unidad", "rol", "emitido", "expira"}


def test_no_existe_lista_de_revocacion_y_es_deliberado():
    """T-06 declarado: un token filtrado caduca solo, y esa es la unica
    revocacion que este sistema tiene. Se comprueba que NO hay una funcion de
    revocar, para que anadirla en silencio rompa esta prueba y obligue a
    actualizar lo que el README promete."""
    assert not hasattr(p, "revocar")
    assert not hasattr(p, "lista_negra")


# ---------------------------------------------------------------------------
# D-SEC-4 · la administracion no se presta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["administracion", "ADMINISTRACION", "admin", ""])
def test_la_administracion_no_es_emitible_bajo_ninguna_combinacion(rol):
    with pytest.raises(p.IdentidadNoPrestable):
        p.emitir("U-101", CLAVE, AHORA, rol=rol)


def test_el_dispensador_solo_emite_rol_residente():
    d = p.Dispensador(ACTIVAS, CLAVE)
    for cred in d.prestar(3, "origen-a", AHORA):
        assert p.verificar(cred["token"], CLAVE, AHORA).rol == p.ROL_RESIDENTE


# ---------------------------------------------------------------------------
# D-SEC-1 · conjunto cerrado · D-SEC-2 · asignacion, no eleccion
# ---------------------------------------------------------------------------


def test_no_se_puede_prestar_una_identidad_que_no_existe():
    """El extremo no crea identidades: si le piden mas de las que hay, lo dice."""
    d = p.Dispensador(ACTIVAS[:5], CLAVE)
    with pytest.raises(p.IdentidadNoPrestable, match="conjunto cerrado"):
        d.prestar(6, "origen-a", AHORA)


def test_todo_lo_prestado_sale_del_conjunto_sembrado():
    d = p.Dispensador(ACTIVAS, CLAVE)
    for cred in d.prestar(50, "origen-a", AHORA):
        assert cred["unidad"] in ACTIVAS


def test_el_solicitante_no_puede_elegir_unidad():
    """D-SEC-2 por construccion: `prestar` no tiene parametro de unidad.

    Igual que en la frontera HTTP, se comprueba la ESTRUCTURA y no el
    comportamiento: una comprobacion que ignore un parametro se puede olvidar;
    un parametro que no existe, no.
    """
    import inspect

    firma = inspect.signature(p.Dispensador.prestar).parameters
    assert "unidad" not in firma
    assert set(firma) == {"self", "cantidad", "origen", "ahora"}


# ---------------------------------------------------------------------------
# D-SEC-5 · el lote · D-SEC-6 · limite por origen
# ---------------------------------------------------------------------------


def test_un_lote_trae_identidades_distintas():
    """El instrumento necesita 50 unidades DISTINTAS: si el lote repitiera, las
    repetidas competirian consigo mismas y la carrera seria menor de lo que
    dice el numero."""
    d = p.Dispensador(ACTIVAS, CLAVE)
    unidades = [c["unidad"] for c in d.prestar(50, "origen-a", AHORA)]
    assert len(set(unidades)) == 50


def test_una_ejecucion_del_instrumento_es_UNA_llamada():
    """D-SEC-5: con entrega por lote, el dispensador se controla como una
    unidad discreta en vez de como un goteo."""
    d = p.Dispensador(ACTIVAS, CLAVE)
    assert len(d.prestar(50, "origen-a", AHORA)) == 50


def test_el_limite_por_origen_corta_el_bucle():
    d = p.Dispensador(ACTIVAS, CLAVE, tope_por_origen=2)
    d.prestar(50, "origen-a", AHORA)
    d.prestar(50, "origen-a", AHORA)
    with pytest.raises(p.IdentidadNoPrestable, match="cuota"):
        d.prestar(50, "origen-a", AHORA)


def test_el_limite_es_por_origen_y_no_global():
    """Si fuera global, el primer visitante dejaria al siguiente sin poder
    ejecutar el instrumento: una denegacion entre revisores (T-12)."""
    d = p.Dispensador(ACTIVAS, CLAVE, tope_por_origen=1)
    d.prestar(50, "origen-a", AHORA)
    with pytest.raises(p.IdentidadNoPrestable):
        d.prestar(50, "origen-a", AHORA)
    assert len(d.prestar(50, "origen-b", AHORA)) == 50, (
        "otro origen no puede quedar afectado por la cuota del primero"
    )


# ---------------------------------------------------------------------------
# RNF-07 · ningun secreto en el repositorio
# ---------------------------------------------------------------------------


def test_sin_clave_no_se_emite_nada():
    """No hay clave por defecto a proposito: un secreto por defecto acaba siendo
    el secreto de todos, y este repositorio es publico."""
    with pytest.raises(ValueError, match="clave de firma"):
        p.emitir("U-101", b"", AHORA)
