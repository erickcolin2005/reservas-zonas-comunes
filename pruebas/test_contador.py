"""SEC-1 · el contador de intentos y la desigualdad que ata los dos controles.

Los criterios de aceptación son los del propio SEC-1, literales:

  - «el instrumento sigue produciendo ≥50 solicitudes simultáneas con el límite
    activo»
  - «una identidad que agota su cuota recibe `SYS-TASA` **y una segunda
    identidad no queda afectada**»
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from reservas.seguridad import contador as c

AHORA = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
VENTANA = timedelta(seconds=60)
RESERVAR = "POST /reservas"


def nuevo(tope=3, ventana=VENTANA):
    return c.ContadorIntentos(ventana=ventana, tope=tope)


# ---------------------------------------------------------------------------
# Los dos criterios de aceptación de SEC-1
# ---------------------------------------------------------------------------


def test_el_instrumento_sigue_produciendo_50_simultaneas_con_el_limite_activo():
    """El criterio que decide si el control es compatible con el proyecto.

    Un límite que impidiera al instrumento lanzar sus 50 solicitudes no estaría
    protegiendo el sistema: estaría **apagando la única prueba de que la carrera
    se cierra**, que es lo que el proyecto existe para demostrar.
    """
    cont = nuevo(tope=3)
    for i in range(50):
        cont.registrar(f"U-{100 + i}", RESERVAR, AHORA)  # ninguna levanta


def test_una_identidad_agotada_no_afecta_a_las_demas():
    cont = nuevo(tope=2)
    cont.registrar("U-101", RESERVAR, AHORA)
    cont.registrar("U-101", RESERVAR, AHORA)
    with pytest.raises(c.TasaExcedida):
        cont.registrar("U-101", RESERVAR, AHORA)
    # La segunda identidad no queda afectada. Si lo estuviera, un solo visitante
    # dejaria al siguiente sin instrumento: T-12, denegacion entre revisores.
    cont.registrar("U-102", RESERVAR, AHORA)


# ---------------------------------------------------------------------------
# Cuenta intentos, no confirmaciones
# ---------------------------------------------------------------------------


def test_cuenta_intentos_aunque_todos_sean_rechazados():
    """Un contador de confirmaciones no limita nada: quien quiera agotar el
    sistema puede hacerlo con solicitudes que se rechazan."""
    cont = nuevo(tope=3)
    for _ in range(3):
        cont.registrar("U-101", RESERVAR, AHORA)  # el desenlace da igual
    assert cont.consumido("U-101", AHORA) == 3
    with pytest.raises(c.TasaExcedida):
        cont.registrar("U-101", RESERVAR, AHORA)


def test_la_cancelacion_tambien_consume_cuota():
    """SEC-1 lo exige: «alcanza tambien la cancelacion». Sin esto, un bucle de
    reservar-cancelar (S-f) rodea el control entero."""
    cont = nuevo(tope=2)
    cont.registrar("U-101", RESERVAR, AHORA)
    cont.registrar("U-101", "POST /reservas/{id}/cancelacion", AHORA)
    with pytest.raises(c.TasaExcedida):
        cont.registrar("U-101", RESERVAR, AHORA)


def test_las_lecturas_no_consumen_cuota():
    """Solo las rutas que ESCRIBEN. Deja el calendario publico fluido, que es lo
    que H5 necesita, y reduce el costo de escritura del propio control."""
    cont = nuevo(tope=1)
    for _ in range(20):
        cont.registrar("U-101", "GET /espacios/{id}/disponibilidad", AHORA)
    cont.registrar("U-101", RESERVAR, AHORA)  # la cuota sigue intacta


# ---------------------------------------------------------------------------
# La ventana expira sola
# ---------------------------------------------------------------------------


def test_la_ventana_expira_sin_que_nadie_la_limpie():
    """El `ttl` del contador ES el fin de la ventana. Un control que necesita
    mantenimiento en un sistema sin proceso de fondo es un control que un dia
    deja de estar."""
    cont = nuevo(tope=1, ventana=timedelta(seconds=60))
    cont.registrar("U-101", RESERVAR, AHORA)
    with pytest.raises(c.TasaExcedida):
        cont.registrar("U-101", RESERVAR, AHORA + timedelta(seconds=59))
    cont.registrar("U-101", RESERVAR, AHORA + timedelta(seconds=61))


def test_una_ventana_no_positiva_se_rechaza_al_construir():
    with pytest.raises(ValueError, match="no expira nunca"):
        c.ContadorIntentos(ventana=timedelta(0), tope=3)


def test_un_tope_menor_que_uno_impide_hasta_el_calentamiento():
    with pytest.raises(ValueError, match="calentamiento"):
        c.ContadorIntentos(ventana=VENTANA, tope=0)


def test_no_hay_valores_por_defecto():
    """El modelo de amenazas se nego a inventar la ventana y el tope. Poner un
    valor por defecto aqui seria inventarlos igualmente, solo que sin que se
    note."""
    import dataclasses

    for nombre in ("ventana", "tope"):
        campo = c.ContadorIntentos.__dataclass_fields__[nombre]
        assert campo.default is dataclasses.MISSING, f"{nombre} tiene defecto"
        assert campo.default_factory is dataclasses.MISSING, f"{nombre} tiene fabrica"

    # Y la comprobacion que de verdad importa: no se puede construir sin darlos.
    with pytest.raises(TypeError):
        c.ContadorIntentos()


# ---------------------------------------------------------------------------
# La desigualdad que ata los dos controles
# ---------------------------------------------------------------------------


def test_la_desigualdad_pasa_cuando_el_borde_da_de_sobra():
    c.comprobar_desigualdad(n_identidades=50, tope_por_identidad=5, capacidad_del_borde=250)


def test_la_desigualdad_corta_una_configuracion_incoherente():
    """Sin ella, subir el tope por identidad por encima de lo que el borde
    admite hace que el borde rechace primero: el instrumento recibe `SYS-TASA`
    del borde y **la medicion se invalida sin que nadie haya tocado el
    contador**."""
    with pytest.raises(c.DesigualdadIncoherente, match="borde"):
        c.comprobar_desigualdad(n_identidades=50, tope_por_identidad=5, capacidad_del_borde=100)


def test_endurecer_un_control_no_puede_anular_el_otro_en_silencio():
    """El caso que la desigualdad existe para impedir, contado como escenario:
    alguien decide 'proteger mas' bajando la capacidad del borde y deja los dos
    controles incoherentes."""
    c.comprobar_desigualdad(50, 3, 150)  # coherente
    with pytest.raises(c.DesigualdadIncoherente):
        c.comprobar_desigualdad(50, 3, 149)  # una unidad menos y ya no lo es


# ---------------------------------------------------------------------------
# El tope se deriva de lo observado, no se inventa
# ---------------------------------------------------------------------------


def test_el_tope_se_deriva_de_las_repeticiones_observadas():
    """Dato de I-3: el CI necesito 3 corridas de K-03 para la medicion de S-2."""
    assert c.sugerencia_de_tope(repeticiones_observadas=3) == 5


def test_sin_observaciones_no_se_deriva_nada():
    with pytest.raises(ValueError, match="se mide primero"):
        c.sugerencia_de_tope(repeticiones_observadas=0)
