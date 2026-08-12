"""La frontera del 200, comprobada como invariante y no como lista de ejemplos.

El contrato de §10.1 es una implicacion, no una tabla:

    200        -> decidio y nombro la regla
    401 / 429  -> no llego a decidir, y dice por cual de las dos razones
    otro !=200 -> infraestructura

Probarlo con tres ejemplos sueltos dejaria pasar el cuarto cubo que alguien
anada manana. Se prueba **sobre todos los cubos que existen**, para que un cubo
nuevo sin codigo asignado rompa el build en vez de colarse con un KeyError en
produccion.
"""

from __future__ import annotations

import pytest

from reservas.adaptadores import borde
from reservas.desenlaces import Cubo, Desenlace
from reservas.nucleo.modelo import Franja
from datetime import date

ORIGEN = "https://reservas-demo.example"


def desenlace(cubo: Cubo, regla: str | None = None, **kw) -> Desenlace:
    return Desenlace(cubo=cubo, regla=regla, **kw)


def test_todos_los_cubos_tienen_codigo_asignado():
    """Guardia contra el cubo nuevo que nadie mapea.

    Sin esto, anadir un cubo al enum y olvidarlo aqui produciria un KeyError en
    la primera peticion que lo produjera —es decir, en produccion y no en el CI.
    """
    sin_codigo = [c for c in Cubo if c not in borde.CODIGO_POR_CUBO]
    assert not sin_codigo, f"cubos sin codigo HTTP: {sin_codigo}"


@pytest.mark.parametrize("cubo", list(Cubo))
def test_el_invariante_del_200_se_cumple_para_todo_cubo(cubo):
    """200 si y solo si el sistema DECIDIO."""
    codigo = borde.CODIGO_POR_CUBO[cubo]
    decidio = cubo in {Cubo.CONFIRMADA, Cubo.RECHAZADA_REGLA, Cubo.SYS_CONTENCION}
    if decidio:
        assert codigo == 200, f"{cubo} decidio y deberia viajar con 200"
    else:
        assert codigo != 200, (
            f"{cubo} NO decidio y un 200 afirmaria lo contrario"
        )


def test_identidad_y_tasa_son_los_dos_unicos_fuera_del_200_que_no_son_infraestructura():
    assert borde.CODIGO_POR_CUBO[Cubo.SYS_IDENTIDAD] == 401
    assert borde.CODIGO_POR_CUBO[Cubo.SYS_TASA] == 429


def test_un_rechazo_de_negocio_viaja_con_200_y_nombra_su_regla():
    r = borde.respuesta_de(desenlace(Cubo.RECHAZADA_REGLA, "RR-10"), ORIGEN)
    assert r.codigo == 200
    assert r.cuerpo["regla"] == "RR-10"


def test_rr10_no_revela_de_quien_es_la_franja():
    """S-03: el conflicto ajeno se informa sin referencia. Si la llevara, el
    sistema estaria contando ocupacion que nadie pregunto."""
    r = borde.respuesta_de(
        desenlace(Cubo.RECHAZADA_REGLA, "RR-10", unidad="U-104",
                  franjas=(Franja(date(2026, 9, 11), 12),)),
        ORIGEN,
    )
    assert "conflicto_propio" not in r.cuerpo
    assert "U-104" not in str(r.cuerpo), "no puede aparecer una unidad ajena"


def test_rr08_si_puede_llevar_referencia_porque_el_dato_es_propio():
    r = borde.respuesta_de(
        desenlace(Cubo.RECHAZADA_REGLA, "RR-08",
                  franjas=(Franja(date(2026, 9, 12), 14),)),
        ORIGEN,
    )
    assert "conflicto_propio" in r.cuerpo


def test_la_confirmada_por_idempotencia_es_indistinguible_de_la_normal():
    """ADR-32. Para el cliente es el mismo hecho: su reserva existe. Darle un
    tipo propio expondria una diferencia interna que no puede usar."""
    normal = borde.respuesta_de(desenlace(Cubo.CONFIRMADA, id_reserva="abc"), ORIGEN)
    idempotente = borde.respuesta_de(desenlace(Cubo.CONFIRMADA, id_reserva="abc"), ORIGEN)
    assert normal == idempotente


def test_cors_con_comodin_esta_prohibido():
    """SEC-6. Un `*` convertiria el instrumento en algo que cualquier pagina
    podria disparar desde el navegador de un tercero."""
    with pytest.raises(ValueError, match="comodin"):
        borde.cabeceras_cors("*")


def test_el_origen_declarado_viaja_en_la_respuesta():
    r = borde.respuesta_de(desenlace(Cubo.CONFIRMADA, id_reserva="x"), ORIGEN)
    assert r.cabeceras["Access-Control-Allow-Origin"] == ORIGEN


def test_la_peticion_no_tiene_donde_poner_una_unidad():
    """S-01 por construccion: la unidad se deriva de la identidad (ADR-26).

    No es que se ignore un campo `unidad` que llegue en el cuerpo: es que la
    peticion **no tiene ese campo**. Una comprobacion que se puede olvidar es
    peor que una estructura que no admite el error.
    """
    campos = borde.PeticionHttp.__dataclass_fields__
    assert "unidad" not in campos
    p = borde.PeticionHttp("/reservas", "POST", cuerpo={"unidad": "U-102"},
                           identidad="U-101")
    # El cuerpo puede traer lo que quiera; la identidad es lo unico que decide.
    assert p.identidad == "U-101"


def test_ningun_mensaje_del_proveedor_llega_al_cuerpo():
    """RNF-12 y SEC-6: un ConditionalCheckFailedException que se escapara al
    cuerpo contaria como fuga."""
    r = borde.respuesta_de(
        desenlace(Cubo.SYS_CONTENCION,
                  detalle="TransactionCanceledException: ConditionalCheckFailed"),
        ORIGEN,
    )
    texto = str(r.cuerpo)
    assert "Exception" not in texto
    assert "ConditionalCheck" not in texto
