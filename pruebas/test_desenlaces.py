"""Los cubos y los tres invariantes — sin motor.

Aqui se prueba el contador, no el sistema. Si el contador cuenta mal, un sistema
correcto puede salir en rojo y —mucho peor— uno roto puede salir en verde.
"""

from __future__ import annotations

from datetime import date

from reservas.desenlaces import (
    Cubo,
    Desenlace,
    Desglose,
    evaluar_invariantes,
)
from reservas.nucleo.modelo import Franja

F10 = Franja(date(2026, 9, 11), 10)
F11 = Franja(date(2026, 9, 11), 11)


def d(cubo, regla=None, franjas=(F10,)):
    return Desenlace(cubo=cubo, regla=regla, franjas=franjas)


# ---------------------------------------------------------------------------
# El denominador de C1 — D-P4-08
# ---------------------------------------------------------------------------


def test_solo_tres_cubos_cuentan_como_competidora_efectiva():
    """"Se enviaron 50" no es el desenlace. El desenlace es cuantas compitieron
    de verdad, y una que murio por capacidad, identidad o tasa no llego a
    disputar la franja."""
    assert d(Cubo.CONFIRMADA).es_competidora_efectiva
    assert d(Cubo.RECHAZADA_REGLA, "RR-11").es_competidora_efectiva
    assert d(Cubo.SYS_CONTENCION).es_competidora_efectiva
    assert not d(Cubo.SYS_CAPACIDAD).es_competidora_efectiva
    assert not d(Cubo.SYS_IDENTIDAD).es_competidora_efectiva
    assert not d(Cubo.SYS_TASA).es_competidora_efectiva
    assert not d(Cubo.OTRO).es_competidora_efectiva


def test_sys_contencion_cuenta_porque_disputo_aunque_nadie_ganara():
    """Es la unica de las cuatro SYS- que entra en el denominador, y no es un
    detalle: disputo, simplemente nadie gano."""
    desglose = Desglose.de([d(Cubo.SYS_CONTENCION), d(Cubo.SYS_CAPACIDAD)])
    assert desglose.competidoras_efectivas == 1
    assert desglose.total == 2


def test_el_desglose_nombra_cada_rechazo_por_su_regla():
    """RR-10 y RR-11 no se pueden agregar en "rechazada": la distincion entre
    las dos es la mitad de lo que el proyecto afirma."""
    desglose = Desglose.de(
        [d(Cubo.RECHAZADA_REGLA, "RR-10"), d(Cubo.RECHAZADA_REGLA, "RR-11")]
    )
    assert desglose.cuenta("RR-10") == 1
    assert desglose.cuenta("RR-11") == 1


# ---------------------------------------------------------------------------
# I-1 · correccion
# ---------------------------------------------------------------------------


def test_dos_confirmadas_sobre_una_franja_rompen_el_build():
    invariantes = evaluar_invariantes(
        {F10: [d(Cubo.CONFIRMADA), d(Cubo.CONFIRMADA)]},
        minimo_competidoras=2,
        confirmadas_esperadas_total=1,
    )
    assert not invariantes.correccion_ok
    assert invariantes.build_en_rojo
    assert "DOBLE RESERVA" in invariantes.motivos_correccion[0]


# ---------------------------------------------------------------------------
# I-2 · vivacidad — el guardia contra "rechazarlo todo"
# ---------------------------------------------------------------------------


def test_rechazarlo_todo_no_pasa_por_correcto():
    """Un sistema que devuelve siempre "no" satisface C1 y no sirve para nada.
    Es el motivo de que K-03 exija cinco confirmadas y no cero dobles."""
    invariantes = evaluar_invariantes(
        {F10: [d(Cubo.RECHAZADA_REGLA, "RR-11") for _ in range(10)]},
        minimo_competidoras=10,
        confirmadas_esperadas_total=1,
    )
    assert invariantes.correccion_ok, "rechazarlo todo NO viola la correccion"
    assert not invariantes.vivacidad_ok, "y eso es exactamente lo que I-2 atrapa"
    assert invariantes.build_en_rojo


def test_confirmar_de_menos_rompe_la_vivacidad_aunque_cada_franja_este_bien():
    """K-03 con cuatro confirmadas en vez de cinco: ninguna franja tiene dos, y
    aun asi el sistema rechazo una franja que nadie disputaba."""
    por_franja = {
        Franja(date(2026, 9, 11), h): [d(Cubo.CONFIRMADA, franjas=(Franja(date(2026, 9, 11), h),))]
        for h in (10, 11, 12, 13)
    }
    invariantes = evaluar_invariantes(
        por_franja, minimo_competidoras=4, confirmadas_esperadas_total=5
    )
    assert invariantes.correccion_ok
    assert not invariantes.vivacidad_ok


def test_el_todo_o_nada_no_se_confunde_con_un_fallo_de_vivacidad():
    """La correccion que K-02 obligo a hacer sobre el enunciado del banco.

    La perdedora de un solapamiento parcial disputo tambien franjas que nadie
    mas queria. Esas se quedan sin confirmar, y eso **es el todo-o-nada
    funcionando**, no un fallo. Con el enunciado literal de banco §5.0, K-02
    saldria en rojo con el sistema correcto.
    """
    ganadora = Desenlace(cubo=Cubo.CONFIRMADA, franjas=(F11,))
    perdedora = Desenlace(cubo=Cubo.RECHAZADA_REGLA, regla="RR-11", franjas=(F10, F11))
    invariantes = evaluar_invariantes(
        {F10: [perdedora], F11: [ganadora, perdedora]},
        minimo_competidoras=2,
        confirmadas_esperadas_total=1,
    )
    assert invariantes.vivacidad_ok, invariantes.motivos_vivacidad


def test_una_franja_pedida_por_una_sola_solicitud_que_no_pedia_nada_mas_si_es_rojo():
    """El otro lado de la excepcion anterior, para que no se coma casos reales.

    Si la unica competidora de una franja pedia solo esa franja y no confirmo,
    no hay todo-o-nada que lo explique: es una franja libre que nadie gano.
    """
    sola = Desenlace(cubo=Cubo.RECHAZADA_REGLA, regla="RR-11", franjas=(F10,))
    invariantes = evaluar_invariantes(
        {F10: [sola]}, minimo_competidoras=1, confirmadas_esperadas_total=0
    )
    assert not invariantes.vivacidad_ok


# ---------------------------------------------------------------------------
# I-3 · validez de la medicion
# ---------------------------------------------------------------------------


def test_sys_tasa_invalida_la_medicion_y_no_rompe_el_build():
    """La culpa es del instrumento o del prestamo de identidades, nunca del
    sistema de reservas. Confundir "el sistema fallo" con "la medicion fallo" es
    lo que la practica n.o 6 heredada existe para evitar."""
    invariantes = evaluar_invariantes(
        {F10: [d(Cubo.CONFIRMADA), d(Cubo.SYS_TASA)]},
        minimo_competidoras=1,
        confirmadas_esperadas_total=1,
    )
    assert invariantes.correccion_ok and invariantes.vivacidad_ok
    assert not invariantes.validez_ok
    assert not invariantes.build_en_rojo


def test_quedarse_corto_de_competidoras_invalida_la_medicion():
    """"Cero sobre 50" habiendo competido 31 seria medir la cosa parecida en vez
    de la cosa, en el unico criterio que el proyecto no puede negociar. Se
    publica el denominador real; no se redondea hacia arriba."""
    invariantes = evaluar_invariantes(
        {
            F10: [d(Cubo.CONFIRMADA)]
            + [d(Cubo.RECHAZADA_REGLA, "RR-11") for _ in range(30)]
        },
        minimo_competidoras=50,
        confirmadas_esperadas_total=1,
    )
    assert not invariantes.validez_ok
    assert "31" in invariantes.motivos_validez[0]
    assert "no se redondea" in invariantes.motivos_validez[0].lower()


def test_la_ausencia_de_rr11_es_aviso_y_no_fallo():
    """Exigirlo como build en rojo haria la prueba intermitente: la
    simultaneidad efectiva no es determinista. El build cae por mas de una
    confirmacion, que si lo es."""
    invariantes = evaluar_invariantes(
        {F10: [d(Cubo.CONFIRMADA), d(Cubo.RECHAZADA_REGLA, "RR-10")]},
        minimo_competidoras=2,
        confirmadas_esperadas_total=1,
    )
    assert not invariantes.build_en_rojo
    assert any("RR-11 = 0" in a for a in invariantes.avisos)


def test_sys_capacidad_se_publica_con_su_numero_y_se_descuenta():
    invariantes = evaluar_invariantes(
        {F10: [d(Cubo.CONFIRMADA), d(Cubo.SYS_CAPACIDAD)]},
        minimo_competidoras=1,
        confirmadas_esperadas_total=1,
    )
    assert invariantes.validez_ok
    assert any("SYS-CAPACIDAD" in a for a in invariantes.avisos)


# ---------------------------------------------------------------------------
# La medida de solapamiento
# ---------------------------------------------------------------------------


def test_el_solapamiento_no_cuenta_intervalos_que_solo_se_tocan():
    """Si un intervalo empieza justo cuando otro acaba, no coincidieron. La
    misma convencion de intervalo semiabierto que usa el dominio."""
    from reservas.concurrencia import max_solapamiento

    assert max_solapamiento([(0.0, 1.0), (1.0, 2.0)]) == 1
    assert max_solapamiento([(0.0, 1.0), (0.5, 2.0)]) == 2
    assert max_solapamiento([(0.0, 3.0), (1.0, 2.0), (1.5, 2.5)]) == 3
    assert max_solapamiento([]) == 0


def test_un_bucle_secuencial_da_solapamiento_uno():
    """Es la prueba de la prueba: 50 peticiones en fila producen S-2 = 1. Si
    algun dia los casos K midieran esto, la medicion estaria rota aunque el
    resultado saliera en verde."""
    from reservas.concurrencia import max_solapamiento

    secuencial = [(float(i), float(i) + 0.9) for i in range(50)]
    assert max_solapamiento(secuencial) == 1
