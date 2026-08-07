"""K-01, K-02 y K-03 — el criterio de cierre de I-1.

Cada caso se comprueba en las tres capas del banco §5.0, y en pruebas separadas
a proposito: **saber cual de las tres fallo es la mitad del valor**.

    correccion  ->  rompe el build. Es C1.
    vivacidad   ->  rompe el build. Es el guardia contra rechazarlo todo.
    validez     ->  NO rompe el build por si sola en lo que es indeterminista;
                    si rompe el build en la parte que si es determinista, porque
                    una corrida que no midio lo que dice medir no puede pasar en
                    verde.

Sobre la ultima linea, que es donde se decide si esto vale de algo. El banco
avisa de que exigir "al menos un RR-11" como build en rojo haria la prueba
intermitente, porque la simultaneidad efectiva no es determinista. Se respeta.
**Lo que si se exige en rojo es la parte determinista de la validez**: cero
`SYS-IDENTIDAD`, cero `SYS-TASA` y competidoras efectivas por encima del minimo
del caso. Si compitieron 31 y el caso pide 50, la corrida no midio C1 y no puede
salir en verde: se sube N, no se baja el criterio (D-P4-08 punto 4).
"""

from __future__ import annotations

import pytest

from herramientas import casos_k

from .conftest import guardar_evidencia

pytestmark = [pytest.mark.motor, pytest.mark.lento]


DIA_Y_ESPACIO = {"K-01": ("E-CAN", 4), "K-02": ("E-SAL", 6), "K-03": ("E-CAN", 4)}


def _correr(nombre, cliente, endpoint, t0):
    """Ejecuta el caso y **fotografia la tabla inmediatamente despues**.

    La foto se toma aqui y no en la prueba porque el caso siguiente recrea la
    tabla. Comprobar el estado residual mas tarde mediria la tabla vacia y
    pasaria en verde sin haber mirado nada — medir la cosa parecida en su forma
    mas tonta.
    """
    from reservas.adaptadores import dynamodb

    conjunto = casos_k.preparar(cliente, t0)
    caso = casos_k.CASOS[nombre](t0, conjunto)
    resultado = casos_k.ejecutar(caso, endpoint, t0)
    espacio, dia = DIA_Y_ESPACIO[nombre]
    ocupacion = dynamodb.AdaptadorDynamoDB(cliente).leer_ocupacion_dia(
        espacio, casos_k.tiempo.dia_mas(t0, dia)
    )
    return resultado, ocupacion


@pytest.fixture(scope="module")
def resultados(request):
    """Se corren los tres casos una vez y se reparten entre las pruebas.

    Se cachean porque cada uno levanta 50 hilos: repetirlos por prueba pagaria
    tres veces lo mismo sin anadir informacion. **Cuantas veces hay que repetir
    cada caso K para que el verde sea evidencia y no suerte sigue abierto**
    (banco §9, Q-9) y es de `qa-agent`; aqui se corre una vez por push, y quien
    quiera mas usa `python -m herramientas.casos_k --repeticiones N`.
    """
    endpoint = request.getfixturevalue("endpoint")
    cliente = request.getfixturevalue("cliente_sesion")
    t0 = request.getfixturevalue("t0")
    salida = {n: _correr(n, cliente, endpoint, t0) for n in ("K-01", "K-02", "K-03")}
    guardar_evidencia(
        "casos-k.txt",
        "Casos K contra el sustituto local — ultima ejecucion del CI\n"
        f"T0 derivado: {t0.isoformat()}\n\n"
        + "\n".join(r.texto for r, _ in salida.values()),
    )
    return salida


@pytest.fixture()
def k01(resultados):
    return resultados["K-01"][0]


@pytest.fixture()
def k02(resultados):
    return resultados["K-02"][0]


@pytest.fixture()
def k03(resultados):
    return resultados["K-03"][0]


# ---------------------------------------------------------------------------
# K-01 · 50 unidades distintas por la misma franja
# ---------------------------------------------------------------------------


def test_k01_correccion_exactamente_una_confirmada(k01):
    """C1. Cincuenta transacciones sobre la misma clave; una aplica.

    No hay estado intermedio seguro: la carrera esta abierta o cerrada.
    """
    assert k01.invariantes.correccion_ok, k01.texto
    assert k01.desglose.confirmadas == 1, k01.texto


def test_k01_vivacidad_alguien_gano(k01):
    assert k01.invariantes.vivacidad_ok, k01.texto


def test_k01_la_medicion_fue_valida(k01):
    """La parte determinista de I-3. Si compitieron menos de 50, la corrida no
    midio C1 y no puede pasar en verde diciendo que si."""
    assert k01.invariantes.validez_ok, k01.texto
    assert k01.desglose.competidoras_efectivas >= 50, k01.texto


def test_k01_hubo_simultaneidad_observada(k01):
    """S-1 y S-2 se publican; **decide S-3**, que es inmune al reloj.

    Un RR-11 solo puede existir si una condicion fallo sobre una franja que la
    lectura vio libre: es evidencia directa de que dos solicitudes estuvieron
    dentro a la vez. Sin el, esto seria un bucle secuencial disfrazado.
    """
    s = k01.simultaneidad
    assert s.s1_max_en_vuelo >= 2, f"S-1 = {s.s1_max_en_vuelo}: no hubo solape\n{k01.texto}"
    assert s.s2_max_ventanas_solapadas >= 2, k01.texto
    if not s.hubo_carrera_observada:
        pytest.fail(
            "S-3 = 0: ningun rechazo fue RR-11. No hay evidencia directa de "
            "carrera, luego esta corrida NO vale como evidencia de C1. El banco "
            "la clasifica como aviso de medicion y no como fallo del sistema; "
            "aqui se falla a proposito porque un verde sin carrera observada "
            "seria el fallo fatal n.o 1 pasando desapercibido.\n" + k01.texto
        )


def test_k01_ningun_rechazo_se_queda_sin_nombrar_su_regla(k01):
    """Un rechazo que no nombra su regla no cuenta como rechazo (C3)."""
    sin_regla = [
        d
        for d in k01.desglose.por_etiqueta
        if d not in ("confirmada",) and not d.startswith(("RR-", "SYS-"))
    ]
    assert not sin_regla, f"desenlaces sin regla: {sin_regla}\n{k01.texto}"


# ---------------------------------------------------------------------------
# K-02 · solapamiento PARCIAL
# ---------------------------------------------------------------------------


def test_k02_correccion_con_solapamiento_parcial(k02):
    """El caso que separa un sistema de un tutorial.

    `10-14` y `12-16` comparten exactamente las franjas de las 12 y las 13. Un
    diseno que solo comparara inicios identicos pasa K-01 y falla aqui. Y uno
    que escribiera franja a franja podria dejar a cada una con la mitad y
    **ninguna confirmar**, ademas de dejar franjas tomadas por reservas que no
    existen — que es lo que la transaccion todo-o-nada impide.
    """
    assert k02.invariantes.correccion_ok, k02.texto
    assert k02.desglose.confirmadas == 1, k02.texto


def test_k02_vivacidad_una_de_las_dos_confirmo_entera(k02):
    assert k02.invariantes.vivacidad_ok, k02.texto


def test_k02_la_perdedora_no_dejo_rastro_en_ninguna_franja(resultados):
    """RF-11. Un rechazo no deja rastro que ocupe la franja.

    Se comprueba contra el MOTOR, no contra el desenlace: el desenlace es lo que
    el sistema dice que hizo, y la tabla es lo que hizo. La ganadora ocupa
    exactamente sus cuatro franjas y **ninguna mas**. Si la perdedora hubiera
    escrito parte de las suyas antes de fallar, aqui apareceria una quinta o
    sexta franja tomada por una reserva que no existe — y el sistema se habria
    comido dos horas de salon sin que nadie las tenga reservadas.
    """
    resultado, ocupadas = resultados["K-02"]
    assert len(ocupadas) == 4, (
        f"quedaron {len(ocupadas)} franjas tomadas y una reserva de E-SAL ocupa "
        f"4: {sorted(str(f) for f in ocupadas)}\n{resultado.texto}"
    )
    duenos = {o.id_reserva for o in ocupadas.values()}
    assert len(duenos) == 1, f"franjas de dos reservas distintas: {duenos}"
    horas = sorted(f.hora for f in ocupadas)
    assert horas in ([10, 11, 12, 13], [12, 13, 14, 15]), horas


def test_k01_deja_exactamente_una_franja_tomada(resultados):
    """Las 49 rechazadas no escribieron nada sobre el hueco (RF-11)."""
    resultado, ocupadas = resultados["K-01"]
    assert len(ocupadas) == 1, (
        f"49 rechazos dejaron rastro: {sorted(str(f) for f in ocupadas)}\n"
        + resultado.texto
    )


def test_k03_deja_exactamente_cinco_franjas_tomadas(resultados):
    resultado, ocupadas = resultados["K-03"]
    assert sorted(f.hora for f in ocupadas) == [10, 11, 12, 13, 14], resultado.texto


def test_k02_la_medicion_fue_valida(k02):
    """Con solo dos solicitudes, un solo SYS-CAPACIDAD invalida la corrida
    entera: hay que repetirla, no interpretarla."""
    assert k02.invariantes.validez_ok, k02.texto
    assert k02.desglose.competidoras_efectivas == 2, k02.texto


# ---------------------------------------------------------------------------
# K-03 · el guardia contra el sistema que rechaza todo
# ---------------------------------------------------------------------------


def test_k03_vivacidad_cinco_confirmadas(k03):
    """**Este es el caso que impide que "rechazarlo todo" pase por correcto.**

    Un sistema que devolviera siempre "no" satisface C1 —jamas hay dos
    confirmaciones— y es completamente inutil. Por eso K-03 exige CINCO
    confirmadas y no cero dobles: cinco grupos de claves disjuntos, y rechazar
    de mas seria rechazar claves que nadie disputa.
    """
    assert k03.desglose.confirmadas == 5, k03.texto
    assert k03.invariantes.vivacidad_ok, k03.texto


def test_k03_correccion_una_por_franja(k03):
    assert k03.invariantes.correccion_ok, k03.texto


def test_k03_la_medicion_fue_valida(k03):
    assert k03.invariantes.validez_ok, k03.texto
    assert k03.desglose.competidoras_efectivas >= 50, k03.texto


def test_k03_hubo_simultaneidad_observada(k03):
    s = k03.simultaneidad
    assert s.s1_max_en_vuelo >= 2, k03.texto
    if not s.hubo_carrera_observada:
        pytest.fail("S-3 = 0 en K-03: sin evidencia directa de carrera\n" + k03.texto)


# ---------------------------------------------------------------------------
# Lo que hace honesta a la propia prueba
# ---------------------------------------------------------------------------


def test_las_solicitudes_se_lanzaron_de_verdad_a_la_vez(k01, k03):
    """El guardia de la prueba, no del sistema.

    Cincuenta peticiones en un bucle secuencial dan verde con el patron
    ingenuo. Lo que distingue una prueba de concurrencia de un bucle es que
    **todas las solicitudes estan dentro del sistema al mismo tiempo**, y eso se
    mide, no se supone.
    """
    for resultado in (k01, k03):
        s = resultado.simultaneidad
        assert s.lanzadas == 50
        assert s.s1_max_en_vuelo == 50, (
            f"solo {s.s1_max_en_vuelo} de {s.lanzadas} solicitudes coincidieron "
            "dentro del sistema. Esto no es una prueba de concurrencia\n"
            + resultado.texto
        )
        assert s.s2_max_ventanas_solapadas >= 40, (
            f"S-2 = {s.s2_max_ventanas_solapadas}: las ventanas de escritura "
            "apenas se solaparon\n" + resultado.texto
        )
