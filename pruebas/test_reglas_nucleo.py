"""Pruebas del nucleo puro. Sin motor, sin red, sin reloj.

Aqui se comprueba lo que hace estructural —y no autodeclarada— la distincion
RR-10 / RR-11: **son dos rutas de codigo que no comparten ni una linea**, y una
de ellas es inalcanzable desde la lectura.
"""

from __future__ import annotations

from datetime import date

import pytest

from reservas import sembrado
from reservas.nucleo import reglas
from reservas.nucleo.modelo import (
    EstadoLeido,
    Franja,
    OcupacionLeida,
    Solicitud,
    TipoOcupacion,
    Unidad,
)
from reservas.nucleo.tiempo import instante_local

T0 = instante_local(2026, 9, 7, 9)
E_CAN = sembrado.espacio("E-CAN")
E_SAL = sembrado.espacio("E-SAL")
U101 = Unidad(id="U-101", activa=True, grupo=sembrado.GRUPO_RAFAGA)


def solicitud(espacio=E_CAN, dia=11, hora=10, franjas=1, unidad="U-101") -> Solicitud:
    return Solicitud(
        unidad=unidad,
        espacio=espacio.id,
        inicio=instante_local(2026, 9, dia, hora),
        n_franjas=franjas,
    )


def estado(**kwargs) -> EstadoLeido:
    base = {"parametros": E_CAN, "unidad": U101}
    base.update(kwargs)
    return EstadoLeido(**base)


# ---------------------------------------------------------------------------
# La propiedad estructural que sostiene el argumento entero
# ---------------------------------------------------------------------------


def test_rr11_es_inalcanzable_desde_la_lectura():
    """RR-11 no existe en el nucleo y no puede existir.

    Si `evaluar()` pudiera devolver RR-11, RR-10 y RR-11 serian dos etiquetas
    que el codigo elige entre las dos que tiene a mano — y una implementacion
    ingenua seria indistinguible de una correcta desde fuera. Que sean dos rutas
    distintas es lo que permite que la mutacion mate cada una por separado y
    demuestre que ambas existen.
    """
    fuente = (
        __import__("pathlib")
        .Path(reglas.__file__)
        .read_text(encoding="utf-8")
    )
    # Aparece en la documentacion del modulo y en las tres constantes de orden,
    # pero nunca como veredicto: no hay ninguna llamada que la rechace.
    assert "Veredicto.rechaza(\"RR-11\")" not in fuente
    assert "RR-11" in reglas.ORDEN_CREACION
    assert reglas.SOLO_CONDICION == ("RR-11",)


def test_el_nucleo_no_confirma_nada_solo_devuelve_una_intencion():
    """Si se apagara el nucleo entero, la doble reserva seguiria siendo
    imposible —lo impide la condicion— pero los rechazos dejarian de nombrar su
    regla. Son dos defensas con dos fallos distintos."""
    veredicto = reglas.evaluar(solicitud(), estado(), T0)
    assert veredicto.aceptada
    assert veredicto.intencion is not None
    assert not hasattr(veredicto, "confirmada")
    assert veredicto.intencion.franjas == (Franja(date(2026, 9, 11), 10),)


# ---------------------------------------------------------------------------
# Las cuatro reglas que I-1 implementa
# ---------------------------------------------------------------------------


def test_rr10_por_solapamiento_en_sus_cuatro_formas():
    """Con franjas, el solapamiento total, el parcial por la cabeza, el parcial
    por la cola, la contencion y la continencia son EL MISMO CASO: comparten
    clave. La aritmetica de intervalos —que es donde un tutorial se equivoca—
    desaparece."""
    ocupada = {
        Franja(date(2026, 9, 11), 12): OcupacionLeida(
            TipoOcupacion.RESERVA, "r1", "U-105"
        ),
        Franja(date(2026, 9, 11), 13): OcupacionLeida(
            TipoOcupacion.RESERVA, "r1", "U-105"
        ),
    }
    for hora, franjas, forma in [
        (12, 2, "identico"),
        (12, 1, "contencion"),
        (13, 2, "parcial por la cola"),
        (11, 2, "parcial por la cabeza"),
        (11, 4, "continencia"),
    ]:
        s = Solicitud("U-101", "E-SAL", instante_local(2026, 9, 11, hora), franjas)
        v = reglas.evaluar(s, EstadoLeido(E_SAL, U101, ocupacion=ocupada), T0)
        assert v.regla == "RR-10", forma


def test_la_adyacencia_no_es_solapamiento():
    """`[10:00,12:00)` y `[12:00,13:00)` conviven: no comparten clave, luego no
    chocan. Deja de ser un caso limite delicado y pasa a ser aritmetica que no
    hay que escribir."""
    ocupada = {
        Franja(date(2026, 9, 11), h): OcupacionLeida(TipoOcupacion.RESERVA, "r1", "U-105")
        for h in (10, 11)
    }
    v = reglas.evaluar(
        solicitud(hora=12), estado(ocupacion=ocupada), T0
    )
    assert v.aceptada


def test_rr09_precede_a_rr10_porque_un_bloqueo_no_es_una_reserva_ajena():
    """Una franja bloqueada no debe informarse como «ocupada por otro
    residente»: no lo esta, y decirlo filtraria informacion falsa."""
    ocupada = {
        Franja(date(2026, 9, 11), 10): OcupacionLeida(TipoOcupacion.BLOQUEO, None, None)
    }
    assert reglas.evaluar(solicitud(), estado(ocupacion=ocupada), T0).regla == "RR-09"


def test_rr08_precede_a_rr09_y_a_rr10():
    """Informa al residente de un conflicto SUYO, que puede resolver, y no
    revela nada sobre reservas ajenas."""
    franja = Franja(date(2026, 9, 11), 10)
    v = reglas.evaluar(
        solicitud(),
        estado(
            agenda={franja: "propia"},
            ocupacion={franja: OcupacionLeida(TipoOcupacion.BLOQUEO, None, None)},
        ),
        T0,
    )
    assert v.regla == "RR-08"


def test_rr07_precede_a_todo_lo_demas_de_i1():
    """Una violacion de cupo no se arregla cambiando de hora; una de
    solapamiento, si. Gana la que ahorra el siguiente intento inutil."""
    franja = Franja(date(2026, 9, 11), 10)
    v = reglas.evaluar(
        solicitud(),
        estado(
            cupo_consumido=3,
            agenda={franja: "propia"},
            ocupacion={franja: OcupacionLeida(TipoOcupacion.RESERVA, "r", "U-9")},
        ),
        T0,
    )
    assert v.regla == "RR-07"


def test_el_cupo_se_lee_del_espacio_y_no_de_una_constante():
    """Tres espacios que difieren en todo. Si los valores estuvieran escritos
    fijos en el codigo, el banco entero pasaria sin haber implementado una sola
    regla configurable."""
    s = Solicitud("U-101", "E-SAL", instante_local(2026, 9, 11, 10), 4)
    assert reglas.evaluar(s, EstadoLeido(E_SAL, U101, cupo_consumido=1), T0).regla == "RR-07"
    # El mismo consumo, en un espacio con cupo 3, no rechaza.
    assert reglas.evaluar(solicitud(), estado(cupo_consumido=1), T0).aceptada


def test_menor_regla_gana_entre_condiciones_fallidas():
    """RF-06 tambien dentro de la transaccion: si varias condiciones fallan a la
    vez, se informa la primera del orden."""
    assert reglas.menor_regla("RR-11", "RR-07", "RR-08") == "RR-07"
    assert reglas.menor_regla("RR-11", "RR-09") == "RR-09"
    assert reglas.menor_regla(None, None) is None


# ---------------------------------------------------------------------------
# Lo que I-1 NO implementa, dicho por el codigo y no solo por un comentario
# ---------------------------------------------------------------------------


def test_las_seis_primeras_reglas_estan_registradas_pero_vacias():
    """Registrarlas vacias en su sitio es mas honesto que no registrarlas: el
    hueco se ve, y I-4 rellena el cuerpo sin tocar el orden."""
    assert reglas.PENDIENTES_I4 == ("RR-01", "RR-02", "RR-03", "RR-04", "RR-05", "RR-06")
    assert reglas.ORDEN_CREACION[:6] == reglas.PENDIENTES_I4
    assert set(reglas.IMPLEMENTADAS_I1) == {"RR-07", "RR-08", "RR-09", "RR-10"}
    assert (
        set(reglas.PENDIENTES_I4)
        | set(reglas.IMPLEMENTADAS_I1)
        | set(reglas.SOLO_CONDICION)
    ) == set(reglas.ORDEN_CREACION)


def test_una_precondicion_ausente_no_fabrica_un_veredicto():
    """Sin espacio no hay RR-02 que devolver: RR-02 es de I-4. Se levanta una
    excepcion en vez de inventar un veredicto, porque un veredicto inventado
    aqui pasaria por bueno en el CI."""
    with pytest.raises(reglas.PrecondicionAusente):
        reglas.evaluar(solicitud(), EstadoLeido(None, U101), T0)
    with pytest.raises(reglas.PrecondicionAusente):
        reglas.evaluar(solicitud(), EstadoLeido(E_CAN, None), T0)
