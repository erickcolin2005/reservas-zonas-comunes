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
    # CORREGIDO EN I-4, y el motivo importa mas que la correccion:
    #
    # Las cinco formas se probaban sobre E-SAL con duraciones de 1, 2 y 4
    # franjas. **E-SAL exige un minimo de 4**, asi que tres de las cinco
    # solicitudes eran ilegales por duracion. El test pasaba porque RR-04 no
    # existia todavia; en cuanto se implemento, la primera forma devolvio RR-04.
    #
    # Estaba verde POR LA AUSENCIA de una regla, no por la presencia de la que
    # decia comprobar. El banco no comete ese error: usa E-CAN (min 1, max 2)
    # para las cuatro formas cortas y E-SAL solo para la continencia, que si
    # necesita 4 franjas. Se adopta su eleccion.
    for espacio, params, hora, franjas, forma in [
        ("E-CAN", E_CAN, 12, 2, "identico"),
        ("E-CAN", E_CAN, 12, 1, "contencion"),
        ("E-CAN", E_CAN, 13, 2, "parcial por la cola"),
        ("E-CAN", E_CAN, 11, 2, "parcial por la cabeza"),
        ("E-SAL", E_SAL, 11, 4, "continencia"),
    ]:
        s = Solicitud("U-101", espacio, instante_local(2026, 9, 11, hora), franjas)
        v = reglas.evaluar(s, EstadoLeido(params, U101, ocupacion=ocupada), T0)
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


def test_el_orden_de_creacion_esta_cubierto_entero_y_no_queda_ningun_hueco():
    """En I-1 esta prueba afirmaba que RR-01..RR-06 estaban registradas y VACIAS:
    el hueco se veia, y verlo era el punto. **I-4 lo cierra**, asi que ahora
    afirma lo contrario -no queda ninguna pendiente- y conserva lo que si sigue
    valiendo: que las tres tuplas cubren el orden de creacion ENTERO.

    Esa ultima comprobacion es la que sobrevive a los dos incrementos. Si manana
    se anadiera una regla al orden y nadie la implementara, no haria falta que
    alguien se acordara de escribir una prueba: esta se pondria roja sola."""
    assert reglas.PENDIENTES_I4 == (), "I-4 no dejo ninguna regla sin cuerpo"
    assert reglas.IMPLEMENTADAS_I4 == ("RR-01", "RR-02", "RR-03", "RR-04", "RR-05", "RR-06")
    assert reglas.ORDEN_CREACION[:6] == reglas.IMPLEMENTADAS_I4
    assert set(reglas.IMPLEMENTADAS_I1) == {"RR-07", "RR-08", "RR-09", "RR-10"}
    assert (
        set(reglas.PENDIENTES_I4)
        | set(reglas.IMPLEMENTADAS_I1)
        | set(reglas.IMPLEMENTADAS_I4)
        | set(reglas.SOLO_CONDICION)
    ) == set(reglas.ORDEN_CREACION)


def test_la_ausencia_de_espacio_o_unidad_ya_tiene_regla_en_i4():
    """En I-1 esto levantaba PrecondicionAusente: no habia RR-01 ni RR-02 que
    devolver, y **inventar un veredicto habria pasado por bueno en el CI**.

    I-4 les da cuerpo, y la ausencia deja de ser una precondicion rota para ser
    el desenlace correcto: una unidad que no existe se rechaza igual que una
    inactiva (RR-01), y un espacio que no existe igual que uno deshabilitado
    (RR-02). Que las dos ramas coincidan es el requisito RF-17, no un atajo."""
    assert reglas.evaluar(solicitud(), EstadoLeido(E_CAN, None), T0).regla == "RR-01"
    assert reglas.evaluar(solicitud(), EstadoLeido(None, U101), T0).regla == "RR-02"
