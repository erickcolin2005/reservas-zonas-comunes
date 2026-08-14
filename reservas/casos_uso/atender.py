"""Atender una peticion HTTP: el camino de escritura completo, en su orden.

`reservar.py` orquesta el dominio. Esto orquesta lo que hay **antes** del
dominio, que es donde vive la seguridad. El camino lo fija modelo-datos §5.0 y
en I-1 solo existian los pasos 3 a 5:

    1. identidad PROBADA (token firmado)            SEC-2, ADR-26   <- aqui
    2. CONTADOR DE INTENTOS por identidad           SEC-1, ADR-29   <- aqui
    3. lecturas de estado, consistencia fuerte                      reservar.py
    4. evaluacion pura RR-01..RR-15                                 reservar.py
    5. TRANSACCION CONDICIONAL                                      reservar.py

------------------------------------------------------------------------------
EL ORDEN NO ES UN DETALLE DE IMPLEMENTACION
------------------------------------------------------------------------------
Los dos primeros pasos podrian escribirse en cualquier orden y el sistema
seguiria "funcionando". No es cierto que de igual:

**Autorizar va antes de contar.** El contador cuenta por unidad. Si contara
antes de comprobar la firma, un desconocido podria gastar la cuota de la unidad
que quisiera enviando tokens falsos con esa unidad en el cuerpo: el contador
anotaria el intento y solo despues la firma lo rechazaria. El resultado seria un
control de tasa convertido en arma contra el propio residente — negacion de
servicio por identidad ajena, gratis y sin credenciales.

**Contar va antes de evaluar.** ADR-29 lo exige y su razon esta en el contador:
se cuentan INTENTOS, no confirmaciones. Un intento que la evaluacion rechaza ha
consumido lecturas igual, y no contarlo deja el techo `50 x tope` sin fondo.

Las dos afirmaciones tienen prueba propia en `test_atender.py`, y no como
lectura del codigo: se comprueban por lo que el sistema **hace** cuando cada
paso falla.

------------------------------------------------------------------------------
QUE RUTAS EXISTEN Y CUALES NO
------------------------------------------------------------------------------
arquitectura §10.2 declara ocho rutas. I-6 implementa las cuatro que consume el
instrumento y el frontend minimo. **Las otras cuatro no se declaran como
funciones vacias**, por la misma razon que `puertos.py` no declara los metodos
que le faltan: un manejador que existe y no hace nada se confunde con uno
implementado, y ese es el error que se descubre en produccion.

Una ruta no implementada responde 404, igual que una que no existe. Distinguir
"no implementada todavia" de "no existe" le diria a un desconocido que hay
superficie por venir.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

from ..adaptadores import borde
from ..desenlaces import Cubo, Desenlace
from ..nucleo import tiempo
from ..nucleo.modelo import Solicitud, TipoOcupacion
from ..seguridad import prestamo as seg
from ..seguridad.contador import ContadorIntentos, TasaExcedida
from ..seguridad.prestamo import (
    ROL_ADMINISTRACION,
    ROL_RESIDENTE,
    Dispensador,
    IdentidadNoPrestable,
    Prestamo,
    TokenInvalido,
)

# `verificar` y `exigir_rol` se llaman por su modulo -`seg.verificar(...)`- y no
# se importan por nombre. **Es lo que hace que el mutante de seguridad llegue
# hasta aqui**: `from ... import verificar` copia la funcion a este espacio de
# nombres al importar, y apagarla en `prestamo` despues ya no cambiaria nada de
# lo que este fichero ejecuta. El mutante sobreviviria, M4S saldria en verde, y
# el verde diria que el autorizador esta vigilado cuando lo que estaria vigilado
# es solo su prueba unitaria — no su uso.


@dataclass(frozen=True)
class Dependencias:
    """Lo que el borde necesita para atender. Todo inyectado, nada construido aqui.

    **`ahora` no esta**, y su ausencia es la regla 5 de modelo-datos §4.3: este
    modulo no llama al reloj. El instante entra por parametro desde el
    adaptador, que es quien tiene derecho a saber que hora es.
    """

    clave: bytes
    adaptador: object
    contador: ContadorIntentos
    dispensador: Dispensador
    espacios: tuple[str, ...]
    origen_permitido: str

    # ----------------------------------------------------------------------
    # LO QUE FALTA PARA QUE ESTO SE PUEDA DESPLEGAR, declarado y no disimulado
    # ----------------------------------------------------------------------
    # `ContadorIntentos` y `Dispensador` **cuentan en memoria del proceso**.
    # Encadenados aqui y ejecutados en una Lambda, cada contenedor tendria su
    # propio contador: el techo dejaria de ser `50 x tope` y pasaria a ser
    # `50 x tope x contenedores`, que es un numero que nadie controla. El limite
    # por origen del dispensador se diluye igual.
    #
    # **No es un defecto de estos modulos**: son correctos y estan probados. Es
    # que el modelo de datos ya tiene resuelto donde viven los dos contadores
    # -`IDT#<identidad>/INTENTOS#<ventana>` y `ORG#<origen>/PRESTAMOS#<ventana>`,
    # con `ttl`- y esa mitad todavia no esta escrita. `puertos.py` la tiene
    # anotada como `contar_intento(...) [I-6]` desde I-1.
    #
    # **Hasta que exista, esto corre en pruebas y no se despliega.** Escribirlo
    # aqui es lo unico que impide que un verde de la suite se lea como "listo
    # para desplegar", que es exactamente el error que este proyecto persigue.


@dataclass(frozen=True)
class Ruta:
    """Una ruta declarada: quien puede entrar y si consume cuota."""

    metodo: str
    plantilla: str
    rol: str | None
    """`None` = publica. El calendario se lee sin token a proposito: limitar la
    lectura por identidad dejaria el calendario publico detras de un prestamo, y
    H5 lo necesita fluido. Las lecturas se acotan en el borde, no aqui."""


# Las cuatro de I-6, con su rol. Las de /admin llevan ROL_ADMINISTRACION
# escrito aunque todavia no tengan manejador: el dia que lo tengan, el rol ya
# esta decidido y no se decide con prisa.
RUTAS: dict[tuple[str, str], Ruta] = {
    ("GET", "/espacios"): Ruta("GET", "/espacios", None),
    ("GET", "/espacios/{id}/disponibilidad"): Ruta(
        "GET", "/espacios/{id}/disponibilidad", None
    ),
    ("POST", "/demo/credenciales"): Ruta("POST", "/demo/credenciales", None),
    ("POST", "/reservas"): Ruta("POST", "/reservas", ROL_RESIDENTE),
}

ROL_DE_ADMIN = ROL_ADMINISTRACION
"""Se importa y se nombra para que su ausencia en `RUTAS` sea visible: las rutas
de administracion no estan implementadas en I-6, y no se fingen."""


def atender(
    peticion: borde.PeticionHttp, deps: Dependencias, ahora: datetime
) -> borde.RespuestaHttp:
    """Punto unico de entrada. Ninguna excepcion sale de aqui."""
    origen = deps.origen_permitido
    try:
        clave_ruta = (peticion.metodo, peticion.ruta)
        declarada = RUTAS.get(clave_ruta)
        if declarada is None:
            return borde.respuesta_json(404, {"resultado": "no-existe"}, origen)

        # -- Paso 1 · la identidad se PRUEBA, no se declara (SEC-2, ADR-26) --
        prestamo: Prestamo | None = None
        if declarada.rol is not None:
            try:
                prestamo = seg.verificar(peticion.autorizacion or "", deps.clave, ahora)
                seg.exigir_rol(prestamo, declarada.rol)
            except TokenInvalido:
                # Sin detalle. Distinguir "firma mala" de "caducado" le diria a
                # quien prueba cual de las dos cosas tiene que arreglar.
                return borde.sin_identidad(origen)
            # Pasada la frontera: el token en claro deja de existir aguas abajo.
            peticion = replace(
                peticion, identidad=prestamo.unidad, autorizacion=None
            )

            # -- Paso 2 · el contador, ANTES de evaluar y fuera de la
            #    transaccion (SEC-1, ADR-29) ---------------------------------
            ruta_contada = f"{peticion.metodo} {peticion.ruta}"
            try:
                deps.contador.registrar(prestamo.unidad, ruta_contada, ahora)
            except TasaExcedida:
                return borde.tasa_excedida(origen)

        # -- Pasos 3 a 5 · el dominio ------------------------------------
        if clave_ruta == ("POST", "/reservas"):
            return _reservar(peticion, deps, ahora, prestamo)
        if clave_ruta == ("GET", "/espacios"):
            return _espacios(deps)
        if clave_ruta == ("GET", "/espacios/{id}/disponibilidad"):
            return _disponibilidad(peticion, deps)
        if clave_ruta == ("POST", "/demo/credenciales"):
            return _credenciales(peticion, deps, ahora)

        return borde.respuesta_json(404, {"resultado": "no-existe"}, origen)

    except Exception:  # noqa: BLE001 - es el ultimo dique, y tiene que serlo
        # Un fallo no previsto es 500 y `OTRO`, **sin traza y sin mensaje**.
        # Dejar salir el texto de la excepcion aqui es como se filtra el nombre
        # de una tabla, una clave o un `ConditionalCheckFailedException`
        # (RNF-12, SEC-6). El diagnostico va al registro, nunca al cuerpo.
        return borde.respuesta_json(
            borde.CODIGO_POR_CUBO[Cubo.OTRO], {"resultado": Cubo.OTRO.value}, origen
        )


# ---------------------------------------------------------------------------
# Los manejadores. Cada uno supone que la identidad y la cuota ya se resolvieron.
# ---------------------------------------------------------------------------


def _reservar(
    peticion: borde.PeticionHttp,
    deps: Dependencias,
    ahora: datetime,
    prestamo: Prestamo,
) -> borde.RespuestaHttp:
    """POST /reservas — RF-05..RF-11, RF-15..RF-19.

    **La unidad sale del prestamo verificado y de ningun otro sitio** (S-01,
    ADR-26). `PeticionHttp` ni siquiera tiene donde traer una, asi que esto no
    es una comprobacion que alguien pueda olvidar: es que no hay alternativa.
    """
    from .reservar import reservar  # tardio: evita un ciclo con el paquete

    cuerpo = peticion.cuerpo or {}
    espacio = cuerpo.get("espacio")
    n_franjas = cuerpo.get("n_franjas")

    try:
        inicio = tiempo.canonizar_inicio(cuerpo.get("inicio"))
    except (tiempo.FueraDeRejilla, tiempo.InstanteAmbiguo, TypeError):
        # RR-03 y no un 400. El nucleo declara que **la rejilla la impone la
        # canonizacion, antes de que exista una Solicitud** (reglas.py), asi
        # que este rechazo es de la misma regla que lo seria si llegara al
        # nucleo. Un 400 aqui haria que el mismo error tuviera dos formas
        # segun donde se detectara.
        return borde.respuesta_de(
            Desenlace(cubo=Cubo.RECHAZADA_REGLA, regla="RR-03"), deps.origen_permitido
        )

    if not isinstance(espacio, str) or not isinstance(n_franjas, int):
        return borde.respuesta_json(
            400, {"resultado": "peticion-mal-formada"}, deps.origen_permitido
        )

    try:
        solicitud = Solicitud(
            unidad=prestamo.unidad,
            espacio=espacio,
            inicio=inicio,
            n_franjas=n_franjas,
        )
    except ValueError:
        # `Solicitud` rechaza cero franjas al construirse, y reglas.py declara
        # que por eso RR-04 no comprueba el cero.
        return borde.respuesta_json(
            400, {"resultado": "peticion-mal-formada"}, deps.origen_permitido
        )

    desenlace = reservar(solicitud, deps.adaptador, ahora)
    return borde.respuesta_de(desenlace, deps.origen_permitido)


def _espacios(deps: Dependencias) -> borde.RespuestaHttp:
    """GET /espacios — RF-01. El catalogo, con sus parametros leidos de la tabla.

    Se publican los parametros porque son **lo que explica cada rechazo**: sin
    saber que el salon exige 72 horas de antelacion, un RR-05 es un "no" sin
    causa, y C3 exige causa.
    """
    espacios = deps.adaptador.leer_espacios(deps.espacios)
    return borde.respuesta_json(
        200,
        {
            "espacios": [
                {
                    "id": e.id,
                    "nombre": e.nombre,
                    "apertura": e.apertura,
                    "cierre": e.cierre,
                    "duracion_minima": e.duracion_minima,
                    "duracion_maxima": e.duracion_maxima,
                    "antelacion_minima_horas": e.antelacion_minima_horas,
                    "horizonte_maximo_dias": e.horizonte_maximo_dias,
                    "cupo": e.cupo,
                    "tipo_periodo": e.tipo_periodo.value,
                    "plazo_cancelacion_horas": e.plazo_cancelacion_horas,
                    "habilitado": e.habilitado,
                }
                for e in espacios
            ]
        },
        deps.origen_permitido,
    )


ESTADO_POR_TIPO = {
    TipoOcupacion.RESERVA: "ocupada",
    TipoOcupacion.BLOQUEO: "mantenimiento",
}
"""**Lo que esta tabla NO tiene es la mitad de su trabajo**: no hay ninguna
entrada que produzca la unidad ni el identificador de la reserva. El calendario
publico dice que una franja esta ocupada; **no dice por quien** (S-03). Que la
traduccion sea una tabla cerrada es lo que impide que alguien anada el dato
"para depurar" sin que se note."""


def _disponibilidad(
    peticion: borde.PeticionHttp, deps: Dependencias
) -> borde.RespuestaHttp:
    """GET /espacios/{id}/disponibilidad — RF-02, RF-03, MC-4."""
    identificador = (peticion.parametros_ruta or {}).get("id")
    dia_texto = (peticion.cuerpo or {}).get("dia")

    if identificador not in deps.espacios:
        # Mismo 404 que una ruta inexistente: un espacio que no esta declarado
        # no se distingue de uno que no existe.
        return borde.respuesta_json(
            404, {"resultado": "no-existe"}, deps.origen_permitido
        )

    try:
        dia = date.fromisoformat(str(dia_texto))
    except (TypeError, ValueError):
        return borde.respuesta_json(
            400, {"resultado": "peticion-mal-formada"}, deps.origen_permitido
        )

    parametros = deps.adaptador.leer_espacio(identificador)
    if parametros is None:
        return borde.respuesta_json(
            404, {"resultado": "no-existe"}, deps.origen_permitido
        )

    ocupacion = deps.adaptador.leer_ocupacion_dia(identificador, dia)
    franjas = []
    for hora in range(parametros.apertura, parametros.cierre):
        tomada = next(
            (o for f, o in ocupacion.items() if f.dia == dia and f.hora == hora), None
        )
        franjas.append(
            {
                "hora": hora,
                "estado": "libre" if tomada is None else ESTADO_POR_TIPO[tomada.tipo],
            }
        )

    return borde.respuesta_json(
        200,
        {"espacio": identificador, "dia": dia.isoformat(), "franjas": franjas},
        deps.origen_permitido,
    )


def _credenciales(
    peticion: borde.PeticionHttp, deps: Dependencias, ahora: datetime
) -> borde.RespuestaHttp:
    """POST /demo/credenciales — SEC-2, D-SEC-1..D-SEC-6.

    **La unica ruta con limite por origen**, y vive aqui precisamente porque
    aqui no destruye la carrera: el instrumento pide su lote UNA vez y despues
    lanza sus 50 solicitudes con 50 identidades distintas (D-SEC-6).
    """
    cantidad = (peticion.cuerpo or {}).get("cantidad")
    if not isinstance(cantidad, int):
        return borde.respuesta_json(
            400, {"resultado": "peticion-mal-formada"}, deps.origen_permitido
        )

    origen_solicitante = peticion.origen or "desconocido"
    try:
        lote = deps.dispensador.prestar(cantidad, origen_solicitante, ahora)
    except IdentidadNoPrestable:
        # Cuota de origen agotada o lote mayor que el conjunto cerrado. **Las
        # dos responden igual y sin detalle**: decir cual de las dos fue le
        # diria a quien sondea el tamano del conjunto o su cuota restante.
        return borde.respuesta_json(
            429, {"resultado": "no-prestable"}, deps.origen_permitido
        )
    except ValueError:
        return borde.respuesta_json(
            400, {"resultado": "peticion-mal-formada"}, deps.origen_permitido
        )

    return borde.respuesta_json(
        200,
        {
            "credenciales": lote,
            "aviso": (
                "Identidades sinteticas de un conjunto cerrado. No corresponden "
                "a ninguna persona real."
            ),
        },
        deps.origen_permitido,
    )
