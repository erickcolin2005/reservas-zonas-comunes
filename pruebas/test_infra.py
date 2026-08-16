"""El IaC del borde, comprobado contra el codigo que despliega.

**Estas son las tres formas de romper el despliegue sin romper ninguna prueba**,
y las tres se descubren normalmente con la pila ya creada:

  - una ruta declarada en el codigo y no expuesta en el API: la pagina la llama,
    API Gateway devuelve su 404, y el sintoma no se parece a la causa;
  - una variable de entorno que el codigo exige y la plantilla no pone: la
    funcion **no arranca**, y el primer visitante ve un 500 sin explicacion;
  - un comodin en el origen de CORS: SEC-6 roto, y roto **donde manda**, porque
    cuando una HTTP API tiene `CorsConfiguration` API Gateway ignora las
    cabeceras que devuelva la integracion.

Se comprueba con expresiones regulares y no con un analizador de YAML a
proposito: `requirements.txt` es corto por decision declarada, y anadir PyYAML
para leer cuatro claves seria pagar una dependencia permanente por una comodidad.
Lo que se quiere atrapar no necesita entender la plantilla entera.

**Lo que esto NO hace:** no valida la plantilla contra CloudFormation. Un error
de sintaxis o un tipo de recurso mal escrito los encuentra `create-stack`, y eso
ocurre en la cuenta. Aqui solo se vigila la costura entre la plantilla y el
codigo, que es la que ningun despliegue de prueba revisa.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from reservas.casos_uso.atender import RUTAS

PLANTILLA = (
    pathlib.Path(__file__).resolve().parent.parent / "infra" / "api-reservas.yaml"
)
FUENTE = PLANTILLA.read_text(encoding="utf-8")

SIN_COMENTARIOS = "\n".join(
    linea for linea in FUENTE.splitlines() if not linea.lstrip().startswith("#")
)
"""La plantilla sin su prosa.

Hace falta porque los comentarios **nombran a proposito lo que no se concede** —
«una politica con `dynamodb:*` impediria…»— y un guardia que buscara sobre el
texto entero se dispararia con la explicacion de por que la cosa no esta. Que la
primera version de esta prueba cayera justo ahi es la mejor senal de que el
comentario dice algo util."""
ENTRADA = (
    pathlib.Path(__file__).resolve().parent.parent / "reservas" / "entrada.py"
)

RENDER = pathlib.Path(__file__).resolve().parent.parent / "render.yaml"
RENDER_FUENTE = RENDER.read_text(encoding="utf-8")
RENDER_SIN_COMENTARIOS = "\n".join(
    linea
    for linea in RENDER_FUENTE.splitlines()
    if not linea.lstrip().startswith("#")
)

SERVIDOR = (
    pathlib.Path(__file__).resolve().parent.parent / "herramientas" / "servidor.py"
)

# La unica que el contenedor NO saca del entorno: `servidor.py --sembrar` la
# compone con las unidades que acaba de sembrar. En Lambda no hay sembrador y por
# eso la plantilla de AWS si la declara. La diferencia es real y esta vigilada
# por su propia prueba, para que no se lea como un olvido.
DEL_SEMBRADOR = {"RESERVAS_UNIDADES_ACTIVAS"}


def rutas_de_la_plantilla() -> set:
    return {
        (m, r)
        for m, r in re.findall(r'RouteKey:\s*"(GET|POST)\s+([^"]+)"', FUENTE)
    }


def variables_que_el_codigo_exige() -> set:
    """Los nombres que `entrada.py` pasa a `exigir` y `_lista`.

    Se sacan del arbol sintactico y no de una lista escrita aqui: una lista
    copiada se queda atras el dia que alguien anada un parametro, y el fallo
    aparece en el despliegue en vez de en el CI.
    """
    arbol = ast.parse(ENTRADA.read_text(encoding="utf-8"))
    nombres = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Name):
            continue
        if nodo.func.id not in ("exigir", "_lista") or not nodo.args:
            continue
        if isinstance(nodo.args[0], ast.Constant) and isinstance(
            nodo.args[0].value, str
        ):
            nombres.add(nodo.args[0].value)
    return nombres


# ---------------------------------------------------------------------------
# Las rutas: las dos superficies contra la misma tabla
# ---------------------------------------------------------------------------


def test_toda_ruta_del_api_la_atiende_el_codigo():
    """Una ruta expuesta y no implementada invoca la funcion para nada: cuesta
    una ejecucion y responde el 404 generico de `atender`."""
    for metodo, ruta in rutas_de_la_plantilla():
        assert (metodo, ruta) in RUTAS, (
            f"el API expone {metodo} {ruta} y el codigo no la declara"
        )


def test_toda_ruta_del_codigo_esta_expuesta_en_el_api():
    """Y al reves, que es el que se nota tarde: la ruta existe, esta probada,
    pasa la suite, y desde el navegador no responde nadie."""
    expuestas = rutas_de_la_plantilla()
    for clave in RUTAS:
        assert clave in expuestas, (
            f"el codigo atiende {clave[0]} {clave[1]} y el API no la expone"
        )


# ---------------------------------------------------------------------------
# Las variables: si falta una, la funcion no arranca
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variable", sorted(variables_que_el_codigo_exige()))
def test_la_plantilla_pone_toda_variable_que_el_codigo_exige(variable):
    """`entrada.py` no tiene valores por defecto **a proposito**: un despliegue
    que arranca sin que nadie decida nada parece configurado. El precio de esa
    decision es que la plantilla tiene que ponerlas todas, y esto lo vigila."""
    assert re.search(rf"^\s*{variable}:\s*!", FUENTE, re.M), (
        f"{variable} la exige el codigo y la plantilla no la pone: la funcion "
        "no arrancaria y el primer visitante veria un 500 sin explicacion"
    )


def test_la_plantilla_no_pone_la_llave_del_motor_real():
    """D-P4-19. La llave existe para que nadie golpee AWS desde una maquina de
    desarrollo; dentro de la cuenta boto3 resuelve el extremo solo. Ponerla aqui
    no haria dano, pero sugeriria que hace falta — y el dia que alguien la
    copiara a otro sitio, haria exactamente el dano que evita."""
    assert "RESERVAS_MOTOR_REAL:" not in SIN_COMENTARIOS


# ---------------------------------------------------------------------------
# SEC-6 · el comodin, rechazado donde manda
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# La demo publica: la misma costura, en el otro despliegue
# ---------------------------------------------------------------------------
#
# `render.yaml` levanta el contenedor de la demo publica. Es un despliegue
# distinto del de AWS y tiene los mismos modos de fallo silencioso, asi que lleva
# los mismos guardias. Se comprueba con expresiones regulares por la misma razon
# que la plantilla de arriba: no se anade PyYAML para leer cuatro claves.


@pytest.mark.parametrize(
    "variable", sorted(variables_que_el_codigo_exige() - DEL_SEMBRADOR)
)
def test_render_declara_toda_variable_que_el_codigo_exige(variable):
    """Si falta una, el contenedor **no arranca** — y en un alojamiento eso se ve
    como reinicios en bucle, que no se parece a su causa."""
    assert re.search(rf"^\s*-\s*key:\s*{variable}\s*$", RENDER_FUENTE, re.M), (
        f"{variable} la exige el codigo y `render.yaml` no la declara"
    )


def test_render_no_declara_las_unidades_activas():
    """Y esta al reves, porque declararla romperia algo que hoy funciona.

    En el contenedor las unidades las compone `--sembrar` con lo que acaba de
    sembrar. Ponerla en `render.yaml` la fijaria a mano, y el dia que el sembrado
    cambiara de tamano **la desigualdad de SEC-1 se comprobaria contra un numero
    que ya no es el real**.
    """
    for variable in DEL_SEMBRADOR:
        assert f"key: {variable}" not in RENDER_SIN_COMENTARIOS, (
            f"{variable} la pone el sembrador, no el entorno"
        )


def test_render_se_queda_en_el_plan_gratuito():
    """El guardia economico de este despliegue, y es todo el que hay.

    Aqui no existe nada parecido al guardarrail de AWS: un `plan:` distinto de
    `free` empieza a cobrar sin avisar a nadie. Cambiarlo tiene que costar tocar
    esta prueba, que es la diferencia entre una decision y un descuido.
    """
    assert re.search(r"^\s*plan:\s*free\s*$", RENDER_FUENTE, re.M), (
        "el plan dejo de ser `free`: esto ya cuesta dinero"
    )


def test_render_no_pone_la_llave_del_motor_real():
    """D-P4-19, y aqui es mas grave que en AWS: `servidor.py` **se niega a
    arrancar** si la encuentra, porque es un servidor de demostracion y no debe
    hablar con el motor real. Ponerla aqui dejaria la demo muerta."""
    assert "RESERVAS_MOTOR_REAL" not in RENDER_SIN_COMENTARIOS


def test_el_health_check_apunta_a_una_ruta_que_el_servidor_sirve():
    """La costura que nadie revisa hasta que el despliegue no levanta.

    Si la ruta del health check y la que sirve el servidor dejan de coincidir, el
    alojamiento declara el servicio enfermo y lo reinicia para siempre. El
    sintoma es «se reinicia solo» y la causa es una cadena de texto.
    """
    declarada = re.search(r"^\s*healthCheckPath:\s*(\S+)\s*$", RENDER_FUENTE, re.M)
    assert declarada, "`render.yaml` no declara healthCheckPath"
    ruta = declarada.group(1)
    fuente = SERVIDOR.read_text(encoding="utf-8")
    assert f'camino == "{ruta}"' in fuente, (
        f"el health check apunta a {ruta} y `servidor.py` no la sirve"
    )


def patron_del_origen() -> str:
    """El patron **de `OrigenPermitido`**, no el primero que aparezca.

    La primera version buscaba el primer `AllowedPattern` del fichero y paso a
    verde hasta que otro parametro estreno el suyo — momento en el que empezo a
    validar el patron equivocado. Anclarlo al nombre del parametro es lo que
    impide que esta prueba se quede comprobando otra cosa sin avisar.
    """
    encontrado = re.search(
        r"^  OrigenPermitido:.*?AllowedPattern:\s*\"([^\"]+)\"", FUENTE, re.S | re.M
    )
    assert encontrado, "OrigenPermitido no tiene AllowedPattern"
    return encontrado.group(1)


@pytest.mark.parametrize(
    "origen", ["*", "https://*", "http://*.example", "https://a.example/*"]
)
def test_el_patron_del_origen_rechaza_cualquier_comodin(origen):
    """**Es donde de verdad se decide.** Cuando una HTTP API tiene
    `CorsConfiguration`, API Gateway **ignora** las cabeceras CORS que devuelva
    la integracion — asi que la negativa al comodin que `borde.cabeceras_cors`
    sostiene, y que sus pruebas vigilan, quedaria sin efecto si aqui entrara un
    `*`. La comprobacion del codigo pasa a ser segunda linea, no la unica."""
    assert not re.match(patron_del_origen(), origen), (
        f"el patron admite {origen!r}, y con eso SEC-6 queda roto en el sitio "
        "que manda"
    )


def test_el_patron_admite_un_origen_normal():
    """Un guardia que no deja pasar nada es un guardia que alguien va a quitar."""
    assert re.match(patron_del_origen(), "https://reservas-demo.example")


# ---------------------------------------------------------------------------
# Lo que la funcion puede hacer, y lo que no
# ---------------------------------------------------------------------------


def test_la_politica_no_lleva_comodines_sobre_dynamodb():
    """`dynamodb:*` haria que la plantilla no tuviera que enterarse de que el
    codigo empieza a usar una accion nueva, que es justo lo contrario de lo que
    se quiere."""
    assert "dynamodb:*" not in SIN_COMENTARIOS


@pytest.mark.parametrize(
    "accion",
    ["dynamodb:Scan", "dynamodb:DeleteTable", "dynamodb:CreateTable",
     "dynamodb:BatchWriteItem", "dynamodb:DeleteItem"],
)
def test_la_funcion_no_puede_hacer_lo_que_su_camino_no_usa(accion):
    """Sembrar y recrear la tabla son mantenimiento, y los hace Erick con su
    usuario. El borde publico no tiene por que poder rehacer el modelo de datos
    ni vaciarlo, y no puede.

    **`PutItem` no esta en esta lista y antes si lo estaba**, que es como se
    descubrio el error: la transaccion hace `Put`, asi que la funcion necesita
    poder hacerlo. Prohibirlo habria dejado la politica coherente con una idea
    equivocada de como se autorizan las transacciones.
    """
    assert accion not in SIN_COMENTARIOS, f"la politica concede {accion}"


def test_la_politica_no_pide_una_accion_de_transaccion_que_no_existe():
    """**El error que solo aparece con la pila creada.**

    `dynamodb:TransactWriteItems` no es una accion de IAM. Una transaccion se
    autoriza con las acciones de ITEM de lo que hace dentro — la prueba es que
    el catalogo de DynamoDB incluye `ConditionCheckItem`, que solo tiene sentido
    dentro de una transaccion y que no haria falta si existiera una accion de
    transaccion.

    Escribirla en la politica es legal para CloudFormation: la pila se crea sin
    quejarse y **la primera reserva muere con AccessDenied**. Lo encontro
    cfn-lint, no una prueba nuestra; esta existe para que no vuelva.
    """
    for inventada in ("dynamodb:TransactWriteItems", "dynamodb:TransactGetItems"):
        assert inventada not in SIN_COMENTARIOS, (
            f"{inventada} no es una accion de IAM: la pila se crearia y la "
            "primera transaccion fallaria con AccessDenied"
        )


@pytest.mark.parametrize("accion", ["dynamodb:PutItem", "dynamodb:UpdateItem"])
def test_la_politica_concede_las_acciones_de_item_que_la_transaccion_necesita(accion):
    """La otra mitad: sin estas dos, la transaccion no puede ejecutarse. Y el
    fallo no se veria hasta que alguien intentara reservar de verdad."""
    assert accion in SIN_COMENTARIOS, (
        f"falta {accion}: la transaccion hace Put y Update (modelo-datos §5.1)"
    )


def test_la_concurrencia_reservada_no_baja_de_lo_que_el_instrumento_necesita():
    """**Un tope demasiado bajo rompe M2-INS en silencio.**

    Con menos de 50 ejecuciones simultaneas el instrumento no consigue lanzar su
    tanda, y el resultado no es un error: es una medicion invalida. El sistema
    no habria fallado y aun asi la demostracion dejaria de demostrar — el mismo
    modo de fallo que D-CE4-1 evita por el otro lado.
    """
    bloque = re.search(
        r"ConcurrenciaReservada:.*?MinValue:\s*(\d+)", FUENTE, re.S
    )
    assert bloque, "ConcurrenciaReservada no declara MinValue"
    assert int(bloque.group(1)) >= 50


def test_los_registros_caducan():
    """Sin `RetentionInDays` CloudWatch guarda para siempre, y el volumen es
    proporcional a lo que M2-INS esta disenado para disparar. Con cero creditos,
    "para siempre" es una factura que crece sola."""
    assert re.search(r"RetentionInDays:\s*!Ref", FUENTE)


def test_lo_que_no_se_debe_perder_al_borrar_la_pila_esta_retenido():
    """CD4: el enlace de la demo se publica con su caducidad declarada. Borrar
    la pila por accidente no puede llevarse por delante lo que ese enlace sirve
    mientras siga vivo."""
    assert FUENTE.count("DeletionPolicy: Retain") >= 1
