"""T-UX-17, convertido en algo que se rompe solo.

`sistema-diseno.md` §7 dice de este criterio: *«ningún test automático lo cubre —
es lectura contra el diseño vigente»*, y `P-06` lo dejó asignado a `qa-agent`
para F5. Esto no lo cierra entero, y conviene decirlo antes que después:

  **Lo que SÍ queda automático** — la mitad numérica, que es la que ya falló una
  vez. Un texto solo puede interpolar campos que la API entrega de verdad. El
  día que alguien escriba «faltan 41 horas» sin que el servidor mande esa cifra,
  esto se pone en rojo.

  **Lo que sigue siendo lectura humana** — la prosa. Ninguna prueba sabe si
  «alguien reservó esas horas antes que tú» describe lo que el sistema hace.
  P-06 sigue abierto para esa mitad.

Que la mitad automatizable estuviera sin automatizar era lo que convertía este
criterio en *«el más barato de saltarse»*.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from reservas.casos_uso.atender import Dependencias, _espacios
from reservas.desenlaces import Cubo
from reservas.nucleo import reglas
from reservas.sembrado import ESPACIOS

PAGINA = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
FUENTE = PAGINA.read_text(encoding="utf-8")


def bloque(identificador: str) -> dict:
    """Lee un `<script type="application/json">` sin ejecutar nada."""
    patron = (
        rf'<script type="application/json" id="{identificador}">(.*?)</script>'
    )
    encontrado = re.search(patron, FUENTE, re.S)
    assert encontrado, f"falta el bloque {identificador!r} en la pagina"
    return json.loads(encontrado.group(1))


MENSAJES = bloque("mensajes")


class AdaptadorDeMentira:
    def leer_espacios(self, ids):
        return [e for e in ESPACIOS if e.id in ids]


def campos_que_la_api_entrega() -> set:
    """Los campos de un espacio **tal como los manda `GET /espacios`**.

    Se sacan llamando al manejador de verdad, no de una lista escrita a mano: si
    alguien quita un campo de la respuesta, esta prueba se entera. Una lista
    copiada aqui envejeceria en silencio, que es como empiezan los textos falsos.
    """
    deps = Dependencias(
        clave=b"x",
        adaptador=AdaptadorDeMentira(),
        contador=None,
        dispensador=None,
        espacios=tuple(e.id for e in ESPACIOS),
        origen_permitido="https://x.example",
    )
    respuesta = _espacios(deps)
    return set(respuesta.cuerpo["espacios"][0])


# ---------------------------------------------------------------------------
# La mitad de T-UX-17 que sí se puede automatizar
# ---------------------------------------------------------------------------


def test_ningun_texto_interpola_un_dato_que_la_api_no_entrega():
    """**El criterio, hecho prueba.**

    El catálogo redacta la zona 2 con dos números —lo que pediste y lo que
    cabe—: «se reserva con 72 horas de antelación como mínimo. Para la hora que
    pediste faltan 41». La segunda cifra **no existe**: el servidor responde
    `regla` y nada más, y D-UX-2 dice que la pantalla no calcula. Escribirla
    sería la interfaz afirmando más de lo que sabe.
    """
    permitidos = campos_que_la_api_entrega()
    for regla, mensaje in MENSAJES.items():
        for zona, texto in mensaje.items():
            for campo in re.findall(r"\{(\w+)\}", texto):
                assert campo in permitidos, (
                    f"{regla}/{zona} interpola {{{campo}}}, y `GET /espacios` no "
                    f"lo entrega. Campos disponibles: {sorted(permitidos)}"
                )


def test_ningun_texto_lleva_una_cifra_escrita_a_mano():
    """Los números salen de un parámetro o no salen.

    Un «72 horas» escrito literalmente aquí sería correcto hoy para el salón y
    falso para los otros dos espacios — y quedaría falso del todo el día que
    alguien cambie el parámetro en la tabla, que es exactamente la forma en que
    este criterio se incumplió la primera vez.
    """
    for regla, mensaje in MENSAJES.items():
        for zona, texto in mensaje.items():
            # El hueco se quita CON su sufijo de minutos si lo lleva: en
            # «{apertura}:00» el `:00` es parte del formato de la hora
            # interpolada, no una cifra que el texto afirme por su cuenta.
            sin_huecos = re.sub(r"\{\w+\}(:\d{2})?", "", texto)
            cifras = re.findall(r"\d+", sin_huecos)
            assert not cifras, (
                f"{regla}/{zona} lleva la cifra {cifras} escrita a mano. "
                "Si sale de un parametro, interpolalo; si no, no la afirmes"
            )


# ---------------------------------------------------------------------------
# Que ningún rechazo se quede sin explicación
# ---------------------------------------------------------------------------


REGLAS_DE_CREACION = tuple(r for r in reglas.ORDEN_CREACION)


@pytest.mark.parametrize("regla", REGLAS_DE_CREACION)
def test_toda_regla_que_reservar_puede_devolver_tiene_su_mensaje(regla):
    """C3 y RF-15: **toda** solicitud rechazada lleva mensaje llano.

    Se prueba sobre el orden de evaluación completo y no sobre una lista de
    ejemplos: la regla que alguien añada mañana entra aquí sola y rompe esto
    hasta que tenga texto.
    """
    assert regla in MENSAJES, (
        f"{regla} puede rechazar una reserva y la interfaz no sabe explicarla"
    )


@pytest.mark.parametrize(
    "cubo",
    [c for c in Cubo if c not in (Cubo.CONFIRMADA, Cubo.RECHAZADA_REGLA, Cubo.OTRO)],
)
def test_todo_cubo_que_llega_al_cliente_tiene_su_mensaje(cubo):
    """`SYS-CONTENCION`, `SYS-CAPACIDAD`, `SYS-IDENTIDAD` y `SYS-TASA` también
    llegan a la pantalla, y ninguno es una regla de negocio. Sin texto propio,
    el residente vería un identificador críptico como titular."""
    assert cubo.value in MENSAJES, f"{cubo.value} llega al cliente y no tiene texto"


def test_las_tres_zonas_estan_en_todos_los_mensajes():
    """Titular, por qué y qué hacer. El catálogo §1 es explícito: un
    identificador presentado como titular no le dice a nadie qué hacer."""
    for regla, mensaje in MENSAJES.items():
        assert set(mensaje) == {"titular", "porque", "que_hacer"}, (
            f"{regla} no tiene las tres zonas: {sorted(mensaje)}"
        )
        for zona, texto in mensaje.items():
            assert texto.strip(), f"{regla}/{zona} esta vacio"


# ---------------------------------------------------------------------------
# RF-18 · las dos rutas del mismo hecho se ven igual
# ---------------------------------------------------------------------------


def test_RR10_y_RR11_son_identicos_salvo_el_codigo():
    """Comprobación C-3 del catálogo, carácter a carácter.

    La frase natural para RR-11 —«alguien se te adelantó justo ahora»— es
    **falsa** en RR-10, donde la reserva rival podía llevar tres días
    confirmada. Y no vale escribir la frase cómoda confiando en que casi siempre
    acierte: una interfaz que afirma más de lo que sabe comete, en su propia
    pantalla, el fallo que este proyecto existe para denunciar.
    """
    assert MENSAJES["RR-10"] == MENSAJES["RR-11"]


def test_el_mensaje_comun_no_dice_cuando_ni_quien():
    """Lo cierto en los dos casos, y nada más. Y sin revelar la unidad (RF-17)."""
    texto = MENSAJES["RR-10"]["porque"]
    for palabra in ("justo ahora", "hace un momento", "acaba de"):
        assert palabra not in texto.lower(), (
            f"«{palabra}» es cierto en RR-11 y falso en RR-10"
        )
    assert "no muestra quién" in texto


# ---------------------------------------------------------------------------
# MC-2 · el aviso de datos sintéticos
# ---------------------------------------------------------------------------


def test_el_aviso_de_datos_sinteticos_esta_y_dice_lo_que_tiene_que_decir():
    """MC-2 lo pide **en el formulario**, no en un pie de página.

    Y la condición de reapertura de cumplimiento es tajante: si se cargan datos
    reales de residentes, G1 se reabre entero. El aviso es lo que hace visible
    que no los hay.
    """
    aviso = re.search(r'<div class="aviso">(.*?)</div>', FUENTE, re.S)
    assert aviso, "no hay aviso de datos sinteticos"
    texto = aviso.group(1).lower()
    assert "sintéticos" in texto or "sinteticos" in texto
    assert "no corresponden a ninguna persona" in texto
    # Va antes del formulario de solicitud, no después.
    assert FUENTE.index('class="aviso"') < FUENTE.index('id="reservar"')


def test_la_pagina_no_trae_ninguna_url_de_api_escrita_dentro():
    """La base del API la rellena el IaC. Una URL cocida aquí sobreviviría al
    despliegue que la dejó obsoleta, y CD4 ya obliga a que el enlace de la demo
    nunca se publique sin su caducidad declarada."""
    assert bloque("configuracion")["api"] == ""
    assert "amazonaws.com" not in FUENTE
    assert "execute-api" not in FUENTE


def test_toda_ruta_que_la_pagina_llama_existe_en_la_api():
    """**El desajuste que no sale hasta que alguien abre el navegador.**

    Un frontend que pide `/espacios/disponibilidad` contra una API que declara
    `/espacios/{id}/disponibilidad` compila, pasa toda la suite y falla en la
    primera pantalla. Aquí se comprueban las dos superficies contra la misma
    tabla de rutas, que es la única forma de que no se separen sin avisar.
    """
    from reservas.casos_uso.atender import RUTAS

    llamadas = re.findall(
        r'llamar\(\s*"(GET|POST)",\s*[`"]([^`"]+)[`"]', FUENTE
    )
    assert llamadas, "no se encontro ninguna llamada en la pagina"

    for metodo, ruta in llamadas:
        # `${x}` en una plantilla de JS es un parametro de ruta; la tabla de la
        # API los nombra `{id}`. Y la cadena de consulta no forma parte de la
        # ruta.
        plantilla = re.sub(r"\$\{[^}]+\}", "{id}", ruta).split("?")[0]
        assert (metodo, plantilla) in RUTAS, (
            f"la pagina llama a {metodo} {plantilla} y la API no la declara. "
            f"Rutas declaradas: {sorted(RUTAS)}"
        )


def test_la_pagina_solo_llama_a_rutas_publicas_o_con_credencial():
    """La única ruta con rol es `POST /reservas`, y la página solo la usa con el
    botón habilitado tras pedir credencial. Las demás son públicas a propósito:
    el calendario se lee sin préstamo, que es lo que H5 necesita fluido."""
    from reservas.casos_uso.atender import RUTAS

    assert RUTAS[("POST", "/reservas")].rol is not None
    assert RUTAS[("GET", "/espacios")].rol is None
    # El boton de reservar nace deshabilitado y solo lo abre la credencial.
    assert 'id="reservar" disabled' in FUENTE


def test_no_hay_dependencias_externas():
    """Sin compilación y sin red de terceros: es un fichero que se abre.

    Cada dependencia que haya que descargar antes es una razón más para que el
    revisor no llegue a verlo funcionando.
    """
    for patron in ("<script src=", "cdn.", "unpkg", "jsdelivr", "googleapis"):
        assert patron not in FUENTE, f"la pagina carga algo externo: {patron}"
