"""M2-INS, la parte que se puede comprobar sin motor.

Lo que se prueba aqui es **que el instrumento no miente**, que es su unica
obligacion no negociable: una corrida que no midio concurrencia tiene que
decirlo, y decirlo de forma que no se confunda con «el sistema falla». Las dos
cosas salen en rojo y significan lo contrario.

La corrida entera contra el motor esta en `test_instrumento_motor.py`.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from herramientas import m2_instrumento as ins
from reservas.desenlaces import Cubo, Desglose, Simultaneidad
from reservas.nucleo.modelo import Franja

FRANJA = (Franja(datetime(2026, 9, 8).date(), 10),)


# ---------------------------------------------------------------------------
# No reinterpretar: el instrumento lee la etiqueta que el sistema puso
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "codigo,cuerpo,cubo_esperado",
    [
        (200, {"resultado": "confirmada", "reserva": "abc"}, Cubo.CONFIRMADA),
        (200, {"resultado": "RR-11", "regla": "RR-11"}, Cubo.RECHAZADA_REGLA),
        (200, {"resultado": "RR-10", "regla": "RR-10"}, Cubo.RECHAZADA_REGLA),
        (200, {"resultado": "SYS-CONTENCION"}, Cubo.SYS_CONTENCION),
        (503, {"resultado": "SYS-CAPACIDAD"}, Cubo.SYS_CAPACIDAD),
        (401, {"resultado": "SYS-IDENTIDAD"}, Cubo.SYS_IDENTIDAD),
        (429, {"resultado": "SYS-TASA"}, Cubo.SYS_TASA),
        (500, {"resultado": "otro"}, Cubo.OTRO),
    ],
)
def test_cada_respuesta_cae_en_su_cubo(codigo, cuerpo, cubo_esperado):
    assert ins._desenlace_de(codigo, cuerpo, FRANJA).cubo is cubo_esperado


def test_la_regla_sale_del_cuerpo_y_no_se_deduce():
    """Deducir el cubo de otra cosa que no sea lo que el sistema dijo seria el
    instrumento contando su propia version de los hechos."""
    d = ins._desenlace_de(200, {"resultado": "RR-11", "regla": "RR-11"}, FRANJA)
    assert d.regla == "RR-11"
    assert d.etiqueta() == "RR-11"


# ---------------------------------------------------------------------------
# Negarse a mentir (RF-14) — las tres razones, y ninguna acusa al sistema
# ---------------------------------------------------------------------------


def _desglose(**por_etiqueta):
    from reservas.desenlaces import Desenlace

    desenlaces = []
    for etiqueta, n in por_etiqueta.items():
        etiqueta = etiqueta.replace("_", "-")
        for _ in range(n):
            if etiqueta == "confirmada":
                desenlaces.append(Desenlace(cubo=Cubo.CONFIRMADA, franjas=FRANJA))
            elif etiqueta.startswith("RR"):
                desenlaces.append(
                    Desenlace(cubo=Cubo.RECHAZADA_REGLA, regla=etiqueta, franjas=FRANJA)
                )
            elif etiqueta == "SYS-TASA":
                desenlaces.append(Desenlace(cubo=Cubo.SYS_TASA, franjas=FRANJA))
            elif etiqueta == "SYS-IDENTIDAD":
                desenlaces.append(Desenlace(cubo=Cubo.SYS_IDENTIDAD, franjas=FRANJA))
    return Desglose.de(desenlaces)


def test_sin_ningun_RR11_la_medicion_se_declara_invalida():
    """S-3 es la unica senal inmune al reloj: un RR-11 solo puede existir si una
    condicion fallo sobre una franja que la lectura vio libre. Cero RR-11
    significa que las solicitudes pudieron llegar en fila."""
    motivos = ins._validez(
        _desglose(confirmada=1, RR_10=49), Simultaneidad(s3_rr11=0, lanzadas=50), 50, 50
    )
    assert any("RR-11" in m for m in motivos)


def test_con_un_RR11_la_medicion_vale():
    motivos = ins._validez(
        _desglose(confirmada=1, RR_11=49), Simultaneidad(s3_rr11=49, lanzadas=50), 50, 50
    )
    assert motivos == []


def test_si_no_consiguio_las_identidades_no_se_redondea():
    """D-P4-08: se publica el denominador real. Cuarenta identidades no son
    cincuenta competidoras por mucho que se lancen cincuenta solicitudes."""
    motivos = ins._validez(
        _desglose(confirmada=1, RR_11=39), Simultaneidad(s3_rr11=39, lanzadas=40), 50, 40
    )
    assert any("40" in m and "50" in m for m in motivos)


@pytest.mark.parametrize("cubo", ["SYS-TASA", "SYS-IDENTIDAD"])
def test_un_solo_SYS_TASA_o_SYS_IDENTIDAD_invalida_la_corrida(cubo):
    """La culpa es del instrumento o del prestamo, nunca del sistema de
    reservas. Una corrida asi no se publica como evidencia de C1."""
    motivos = ins._validez(
        _desglose(confirmada=1, RR_11=48, **{cubo.replace("-", "_"): 1}),
        Simultaneidad(s3_rr11=48, lanzadas=50),
        50,
        50,
    )
    assert any(cubo in m for m in motivos)


# ---------------------------------------------------------------------------
# Lo que se ve en pantalla, que es lo unico que un extrano va a leer
# ---------------------------------------------------------------------------


def test_una_medicion_invalida_dice_que_no_afirma_nada_sobre_el_sistema():
    """**Es la frase que evita la conclusion equivocada.** Una corrida invalida
    y un sistema roto se parecen en pantalla, y significan lo contrario."""
    medicion = ins.Medicion(
        desglose=_desglose(confirmada=1, RR_10=49),
        simultaneidad=Simultaneidad(s3_rr11=0, lanzadas=50),
        identidades_pedidas=50,
        identidades_obtenidas=50,
        motivos_invalidez=["cero rechazos RR-11"],
    )
    texto = ins.informe(medicion, "E-CAN", datetime(2026, 9, 8, 10))
    assert "MEDICION INVALIDA" in texto
    assert "NO dice que el sistema falle" in texto
    assert not medicion.valida


def test_una_doble_reserva_se_grita_y_no_se_disimula():
    """Si el instrumento llega a ver dos confirmadas sobre la misma franja, la
    afirmacion central del proyecto es falsa. Tiene que decirlo con esas
    palabras y salir con codigo distinto de cero."""
    medicion = ins.Medicion(
        desglose=_desglose(confirmada=2, RR_11=48),
        simultaneidad=Simultaneidad(s3_rr11=48, lanzadas=50),
        identidades_pedidas=50,
        identidades_obtenidas=50,
    )
    texto = ins.informe(medicion, "E-CAN", datetime(2026, 9, 8, 10))
    assert medicion.doble_reserva
    assert "DOBLE RESERVA" in texto


def test_el_informe_declara_que_S2_no_es_observable_por_HTTP():
    """Lo que no se midio, se calla — pero aqui hay que decir POR QUE falta, o
    alguien lo leera como que la simultaneidad no se comprobo."""
    medicion = ins.Medicion(
        desglose=_desglose(confirmada=1, RR_11=49),
        simultaneidad=Simultaneidad(s3_rr11=49, lanzadas=50),
        identidades_pedidas=50,
        identidades_obtenidas=50,
    )
    texto = ins.informe(medicion, "E-CAN", datetime(2026, 9, 8, 10))
    assert "S-2" in texto and "no observable" in texto


# ---------------------------------------------------------------------------
# El enfriamiento, visto desde el lado del instrumento
# ---------------------------------------------------------------------------


class TransporteQueEnfria:
    def enviar(self, metodo, ruta, cuerpo=None, token=None):
        return 429, {"resultado": "enfriamiento"}


def test_el_enfriamiento_no_se_reporta_como_fallo_del_sistema():
    """D-CE4-1. Es un «vuelve en veinte segundos», y el instrumento tiene que
    saber distinguirlo: informarlo como fallo del sistema de reservas seria
    acusar al sistema de lo que decidio el borde para protegerse."""
    medicion = ins.ejecutar(
        TransporteQueEnfria(), espacio="E-CAN", inicio=datetime(2026, 9, 8, 10)
    )
    assert not medicion.valida
    assert any("enfriando" in m for m in medicion.motivos_invalidez)
    assert not medicion.doble_reserva
