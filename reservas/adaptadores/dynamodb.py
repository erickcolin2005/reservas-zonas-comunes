"""Adaptador de persistencia: lecturas y la transaccion condicional.

Aqui vive el mecanismo que hace imposible la doble reserva, y cabe en una frase:

    reservar no es insertar una reserva; es crear los items de las franjas que
    ocupa, con la condicion de que no existan todavia.

La comprobacion y la escritura son **una sola operacion indivisible**. Como no
son dos, no hay intervalo entre ellas por el que otra solicitud pueda colarse.
Ahi muere la carrera: no se hace improbable, deja de tener donde ocurrir.

Este modulo **no interpreta reglas de negocio**. Devuelve que items fallaron y
por que razon; quien traduce eso a RR-07 / RR-08 / RR-09 / RR-11 es el caso de
uso, porque la traduccion depende de la marca pegajosa de ADR-04, que pertenece
a la solicitud y no al intento interno.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import boto3
from botocore.config import Config as ConfigBotocore
from botocore.exceptions import ClientError

from .. import config
from ..nucleo import claves, tiempo
from ..nucleo.modelo import (
    EstadoLeido,
    Franja,
    IntencionEscritura,
    OcupacionLeida,
    ParametrosEspacio,
    Solicitud,
    TipoOcupacion,
    TipoPeriodo,
    Unidad,
)
from ..puertos import (
    ClaseItem,
    ItemEnFallo,
    RazonCancelacion,
    ResultadoEscritura,
    TipoResultado,
)

# --- atajos para los valores tipados del cliente de bajo nivel -------------


def S(v) -> dict:
    return {"S": str(v)}


def N(v) -> dict:
    return {"N": str(v)}


def BOOL(v) -> dict:
    return {"BOOL": bool(v)}


class ExtremoNoPermitido(Exception):
    """Se intento apuntar al motor real desde un incremento que no puede.

    En I-1 **no se crea nada en AWS**. Cruzar esa puerta arranca el reloj de seis
    meses de la cuenta y es I-2, con su propio disparador. Un fallo de
    configuracion no puede arrancarlo por accidente.
    """


def _comprobar_extremo(endpoint: str) -> None:
    """El motor real solo se alcanza con la llave puesta.

    En I-1 esto era un "no" en redondo. En I-3 pasa a ser un "no, salvo que lo
    pidas explicitamente": `RESERVAS_MOTOR_REAL=1`. Ver `config.motor_real()`
    para el porque, que no es ceremonia -la cuenta es de pago y sin creditos.
    """
    if "amazonaws.com" in endpoint and not config.motor_real():
        raise ExtremoNoPermitido(
            f"{endpoint} es el motor real y {config.VARIABLE_MOTOR_REAL} no "
            "esta puesta. El CI corre entero contra el sustituto local "
            "(ADR-08). Para hablar con AWS a proposito: "
            f"{config.VARIABLE_MOTOR_REAL}=1."
        )


# Parametros compartidos por los dos clientes. Se definen una sola vez para que
# local y real no puedan divergir sin que se note: si los reintentos o el pool
# fueran distintos entre ambos, V-2b estaria comparando dos configuraciones en
# vez de dos motores.
_CONFIG_BOTOCORE = ConfigBotocore(
    # Sin reintentos del cliente: los reintentos son una decision de
    # diseno (ADR-04) y tienen que ser visibles y contables, no un
    # comportamiento oculto de la libreria que falsearia la medicion.
    retries={"max_attempts": 0, "mode": "standard"},
    connect_timeout=5,
    read_timeout=15,
    max_pool_connections=200,
)


def crear_cliente(endpoint: str | None = None):
    """Cliente de DynamoDB: sustituto local por defecto, motor real con llave.

    **Motor real** (`RESERVAS_MOTOR_REAL=1`): no se pasa `endpoint_url` ni
    credencial alguna. Las credenciales salen de la cadena por defecto de boto3
    -perfil, variables de entorno, rol-, nunca del codigo: **este repositorio no
    contiene ningun secreto y no va a contenerlo** (RNF-07).

    **Sustituto local** (por defecto): credenciales de relleno, porque el
    sustituto no valida ninguna.
    """
    if endpoint is None and config.motor_real():
        return boto3.client(
            "dynamodb",
            region_name=config.REGION,
            config=_CONFIG_BOTOCORE,
        )

    destino = endpoint or config.endpoint()
    _comprobar_extremo(destino)
    return boto3.client(
        "dynamodb",
        endpoint_url=destino,
        region_name=config.REGION,
        aws_access_key_id="local",
        aws_secret_access_key="local",
        config=_CONFIG_BOTOCORE,
    )


def crear_tabla(
    cliente,
    tabla: str = config.TABLA,
    rcu: int | None = None,
    wcu: int | None = None,
) -> None:
    """Una tabla, clave compuesta, modo aprovisionado, sin indices (ADR-20/24).

    `rcu`/`wcu` existen por una razon concreta y contraintuitiva, que conviene
    tener escrita porque no se deduce leyendo el codigo:

        **El free tier de DynamoDB no tiene holgura para una segunda tabla.**

    Son 25 WCU y 25 RCU aprovisionadas, que se miden como unidades-hora: unas
    18.250 WCU-hora al mes. La tabla principal, a 25 WCU, consume el 100 % de
    esa asignacion si esta viva el mes entero. Cualquier tabla adicional a 25
    WCU -una sonda, una prueba, un experimento- sale del free tier y, con la
    cuenta en Plan de Pago y CERO creditos (D-P4-17), **cuesta dinero real**.

    Contra el sustituto local da igual y se usan los valores de `config`.
    Contra el motor real, quien cree una tabla auxiliar debe pedir capacidad
    pequena a proposito.
    """
    cliente.create_table(
        TableName=tabla,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={
            "ReadCapacityUnits": config.RCU if rcu is None else rcu,
            "WriteCapacityUnits": config.WCU if wcu is None else wcu,
        },
    )
    # DIFERENCIA REAL ENTRE LOS DOS MOTORES, encontrada al ejecutar V-1:
    # en el sustituto local `create_table` deja la tabla utilizable de
    # inmediato; en DynamoDB de verdad la creacion es ASINCRONA y la tabla pasa
    # por CREATING. Escribir sin esperar produce ResourceNotFoundException, que
    # es un error desconcertante -la tabla existe, solo que aun no.
    #
    # No se detecto en I-1 y no podia detectarse: es exactamente la clase de
    # fallo que el sustituto esconde. Queda anotado como hallazgo de V-2b.
    #
    # Contra el sustituto el espera-a-que-exista devuelve al instante, asi que
    # el codigo es el mismo para los dos y no hay dos caminos que mantener.
    cliente.get_waiter("table_exists").wait(
        TableName=tabla, WaiterConfig={"Delay": 2, "MaxAttempts": 60}
    )


def borrar_tabla(cliente, tabla: str = config.TABLA) -> None:
    # Red de seguridad: la tabla principal del motor real la gestiona
    # CloudFormation y no la borra el codigo de pruebas ni por descuido. Las
    # tablas auxiliares (sondas) si se borran, y por eso el guardia mira el
    # nombre en vez de prohibir el borrado en general.
    if config.motor_real() and tabla == config.TABLA:
        raise ExtremoNoPermitido(
            f"{tabla} en el motor real la gestiona CloudFormation "
            "(infra/tabla-reservas.yaml). Para dejarla limpia usa "
            "vaciar_tabla(); para eliminarla de verdad, borra la pila."
        )
    try:
        cliente.delete_table(TableName=tabla)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        return
    # Ver `crear_tabla`: en el motor real el borrado tampoco es instantaneo, y
    # recrear sobre una tabla que aun se esta borrando falla con
    # ResourceInUseException.
    cliente.get_waiter("table_not_exists").wait(
        TableName=tabla, WaiterConfig={"Delay": 2, "MaxAttempts": 60}
    )


def vaciar_tabla(cliente, tabla: str = config.TABLA) -> int:
    """Borra todos los items dejando la tabla en pie. Devuelve cuantos borro.

    Existe porque contra el motor real NO se puede recrear la tabla: ver
    `recrear_tabla`.
    """
    borrados = 0
    paginador = cliente.get_paginator("scan")
    for pagina in paginador.paginate(
        TableName=tabla, ProjectionExpression="PK,SK"
    ):
        claves = pagina.get("Items", [])
        for i in range(0, len(claves), 25):
            lote = claves[i : i + 25]
            cliente.batch_write_item(
                RequestItems={
                    tabla: [{"DeleteRequest": {"Key": c}} for c in lote]
                }
            )
            borrados += len(lote)
    return borrados


def recrear_tabla(
    cliente,
    tabla: str = config.TABLA,
    rcu: int | None = None,
    wcu: int | None = None,
) -> None:
    """Estado limpio. El banco no acumula estado entre casos (banco §1).

    Ver `crear_tabla` para por que `rcu`/`wcu` son parametros y no constantes.

    **Contra el motor real, la tabla principal NO se recrea: se vacia.** Y la
    razon no es rendimiento:

        Esa tabla la gestiona CloudFormation (`infra/tabla-reservas.yaml`).
        Borrarla y volver a crearla desde el codigo de pruebas dejaria una
        tabla con el mismo nombre pero SIN lo que la plantilla configura -TTL
        activado, clase Standard, politicas de retencion-. CloudFormation
        seguiria creyendo que la gestiona, porque el nombre es el mismo, y la
        diferencia no aparece en ningun error: es deriva silenciosa, que es la
        peor clase.

    Vaciar deja exactamente el mismo estado observable para el banco -ningun
    item- sin tocar la definicion de la tabla.

    Contra el sustituto local se recrea como siempre: alli no hay
    CloudFormation, no hay nada que derivar, y recrear es mas rapido.
    """
    if config.motor_real() and tabla == config.TABLA:
        vaciar_tabla(cliente, tabla)
        return
    borrar_tabla(cliente, tabla)
    crear_tabla(cliente, tabla, rcu=rcu, wcu=wcu)


class AdaptadorDynamoDB:
    """Implementacion del puerto contra el motor (aqui, su sustituto local)."""

    def __init__(
        self,
        cliente,
        tabla: str = config.TABLA,
        horizonte_h_dias: int = config.HORIZONTE_H_DIAS_PRUEBA,
    ):
        self.cliente = cliente
        self.tabla = tabla
        self.horizonte_h_dias = horizonte_h_dias

    # -- lecturas ----------------------------------------------------------

    def leer_estado(self, solicitud: Solicitud) -> EstadoLeido:
        """Lo que se lee antes, y que NO decide nada.

        Consistencia fuerte en las cinco: de ellas depende la ATRIBUCION de la
        regla, nunca la correccion (ADR-02, ADR-23).
        """
        parametros = self._leer_espacio(solicitud.espacio)
        unidad = self._leer_unidad(solicitud.unidad)
        ocupacion = self.leer_ocupacion_dia(solicitud.espacio, solicitud.dia)
        agenda = self._leer_agenda(solicitud.unidad, solicitud.dia)
        cupo = 0
        if parametros is not None:
            cupo = self._leer_cupo(
                solicitud.unidad, solicitud.espacio, parametros.periodo_de(solicitud.dia)
            )
        return EstadoLeido(
            parametros=parametros,
            unidad=unidad,
            ocupacion=ocupacion,
            agenda=agenda,
            cupo_consumido=cupo,
        )

    def _leer_espacio(self, espacio: str) -> ParametrosEspacio | None:
        r = self.cliente.get_item(
            TableName=self.tabla,
            Key={"PK": S(claves.pk_espacio(espacio)), "SK": S(claves.sk_meta())},
            ConsistentRead=True,
        )
        item = r.get("Item")
        if not item:
            return None
        return ParametrosEspacio(
            id=espacio,
            nombre=item["nombre"]["S"],
            apertura=int(item["apertura"]["N"]),
            cierre=int(item["cierre"]["N"]),
            duracion_minima=int(item["duracion_minima"]["N"]),
            duracion_maxima=int(item["duracion_maxima"]["N"]),
            antelacion_minima_horas=int(item["antelacion_minima_horas"]["N"]),
            horizonte_maximo_dias=int(item["horizonte_maximo_dias"]["N"]),
            cupo=int(item["cupo"]["N"]),
            tipo_periodo=TipoPeriodo(item["tipo_periodo"]["S"]),
            plazo_cancelacion_horas=int(item["plazo_cancelacion_horas"]["N"]),
            habilitado=item["habilitado"]["BOOL"],
        )

    def _leer_unidad(self, unidad: str) -> Unidad | None:
        r = self.cliente.get_item(
            TableName=self.tabla,
            Key={"PK": S(claves.pk_unidad(unidad)), "SK": S(claves.sk_meta())},
            ConsistentRead=True,
        )
        item = r.get("Item")
        if not item:
            return None
        return Unidad(
            id=unidad,
            activa=item["activa"]["BOOL"],
            grupo=item["grupo"]["S"],
            bloqueo_fundamento=item.get("bloqueo_fundamento", {}).get("S"),
        )

    def leer_ocupacion_dia(self, espacio: str, dia: date) -> dict[Franja, OcupacionLeida]:
        """Una sola Query por particion: el estado de las franjas de un dia."""
        r = self.cliente.query(
            TableName=self.tabla,
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": S(claves.pk_hueco(espacio, dia))},
            ConsistentRead=True,
        )
        salida: dict[Franja, OcupacionLeida] = {}
        for item in r.get("Items", []):
            hora = int(item["SK"]["S"].rsplit("#", 1)[1])
            salida[Franja(dia, hora)] = OcupacionLeida(
                tipo=TipoOcupacion(item["tipo"]["S"]),
                id_reserva=item.get("id_reserva", {}).get("S"),
                unidad=item.get("unidad", {}).get("S"),
            )
        return salida

    def leer_ocupacion(self, franjas, espacio: str) -> dict[Franja, OcupacionLeida]:
        """Quien ocupa esas franjas ahora. Solo en el camino perdedor."""
        salida: dict[Franja, OcupacionLeida] = {}
        for dia in {f.dia for f in franjas}:
            salida.update(self.leer_ocupacion_dia(espacio, dia))
        return {f: salida[f] for f in franjas if f in salida}

    def _leer_agenda(self, unidad: str, dia: date) -> dict[Franja, str]:
        r = self.cliente.query(
            TableName=self.tabla,
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": S(claves.pk_agenda(unidad, dia))},
            ConsistentRead=True,
        )
        salida: dict[Franja, str] = {}
        for item in r.get("Items", []):
            hora = int(item["SK"]["S"].rsplit("#", 1)[1])
            salida[Franja(dia, hora)] = item.get("id_reserva", {}).get("S", "")
        return salida

    def _leer_cupo(self, unidad: str, espacio: str, periodo: str) -> int:
        r = self.cliente.get_item(
            TableName=self.tabla,
            Key={
                "PK": S(claves.pk_unidad(unidad)),
                "SK": S(claves.sk_cupo(espacio, periodo)),
            },
            ConsistentRead=True,
        )
        item = r.get("Item")
        if not item:
            return 0
        return int(item.get("contador", {"N": "0"})["N"])

    # -- la transaccion de confirmacion ------------------------------------

    def _ttl(self, momento: datetime) -> int:
        """Expiracion propia del sistema, independiente de la cuenta (ADR-21).

        El horizonte se calcula desde el FIN, nunca desde el inicio: asi la
        expiracion no puede alcanzar jamas una franja futura (§10.2 punto 1).
        """
        return tiempo.utc_desde(momento + timedelta(days=self.horizonte_h_dias))

    def construir_items(
        self, intencion: IntencionEscritura, token_solicitud: str, id_reserva: str
    ) -> tuple[list[dict], list[tuple[ClaseItem, Franja | None]]]:
        """Los items de la transaccion, en orden fijo, con su mapa de clases.

        El orden importa: el motor devuelve las razones de cancelacion en el
        mismo orden en que se enviaron los items, y ese es el unico modo de
        saber CUAL condicion fallo.

        Maximo del modelo: 6 franjas + 6 agenda + 1 cupo + 1 cabecera = 14
        items (E-SAL). Queda por debajo de los dos limites por transaccion que
        el diseno recuerda sin afirmar ninguno, asi que no depende de cual sea
        el cierto.
        """
        s: Solicitud = intencion.solicitud
        items: list[dict] = []
        mapa: list[tuple[ClaseItem, Franja | None]] = []

        for franja in intencion.franjas:
            items.append(
                {
                    "Put": {
                        "TableName": self.tabla,
                        "Item": {
                            "PK": S(claves.pk_hueco(s.espacio, franja.dia)),
                            "SK": S(claves.sk_hueco(franja.hora)),
                            "tipo": S(TipoOcupacion.RESERVA.value),
                            "id_reserva": S(id_reserva),
                            "unidad": S(s.unidad),
                            "token_solicitud": S(token_solicitud),
                            "ttl": N(self._ttl(franja.fin)),
                        },
                        # AQUI muere la carrera. Es una sola operacion
                        # indivisible: no hay ventana entre comprobar y
                        # escribir. -> RR-11 si falla.
                        "ConditionExpression": "attribute_not_exists(PK)",
                        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
                    }
                }
            )
            mapa.append((ClaseItem.FRANJA, franja))

        for franja in intencion.franjas:
            items.append(
                {
                    "Put": {
                        "TableName": self.tabla,
                        "Item": {
                            "PK": S(claves.pk_agenda(s.unidad, franja.dia)),
                            "SK": S(claves.sk_agenda(franja.hora)),
                            "id_reserva": S(id_reserva),
                            "ttl": N(self._ttl(franja.fin)),
                        },
                        "ConditionExpression": "attribute_not_exists(PK)",
                        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
                    }
                }
            )
            mapa.append((ClaseItem.AGENDA, franja))

        fin_dia = datetime.combine(
            s.dia, datetime.min.time(), tzinfo=tiempo.ZONA
        ) + timedelta(days=1)
        items.append(
            {
                "Update": {
                    "TableName": self.tabla,
                    "Key": {
                        "PK": S(claves.pk_unidad(s.unidad)),
                        "SK": S(claves.sk_cupo(s.espacio, intencion.periodo_cupo)),
                    },
                    "UpdateExpression": "SET #t = :ttl ADD contador :uno",
                    # La SEGUNDA carrera, y se cierra con el mismo acto: dos
                    # solicitudes de la misma unidad en franjas distintas no
                    # comparten clave de franja, pero si comparten esta.
                    "ConditionExpression": (
                        "attribute_not_exists(contador) OR contador < :tope"
                    ),
                    "ExpressionAttributeNames": {"#t": "ttl"},
                    "ExpressionAttributeValues": {
                        ":uno": N(1),
                        ":tope": N(intencion.tope_cupo),
                        ":ttl": N(self._ttl(fin_dia + timedelta(days=45))),
                    },
                    "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
                }
            }
        )
        mapa.append((ClaseItem.CUPO, None))

        items.append(
            {
                "Put": {
                    "TableName": self.tabla,
                    "Item": {
                        "PK": S(claves.pk_unidad(s.unidad)),
                        "SK": S(claves.sk_reserva(s.dia, id_reserva)),
                        "espacio": S(s.espacio),
                        "inicio": S(s.inicio.isoformat()),
                        "franjas": N(s.n_franjas),
                        "estado": S("confirmada"),
                        "ttl": N(self._ttl(intencion.franjas[-1].fin)),
                    },
                }
            }
        )
        mapa.append((ClaseItem.CABECERA, None))
        return items, mapa

    def intentar_confirmar(
        self,
        intencion: IntencionEscritura,
        token_solicitud: str,
        id_reserva: str | None = None,
    ) -> ResultadoEscritura:
        """Un solo intento. Los reintentos son del caso de uso (ADR-04)."""
        id_reserva = id_reserva or uuid.uuid4().hex
        items, mapa = self.construir_items(intencion, token_solicitud, id_reserva)
        try:
            self.cliente.transact_write_items(TransactItems=items)
            return ResultadoEscritura(TipoResultado.ACEPTADA, id_reserva=id_reserva)
        except ClientError as error:
            return self._traducir(error, mapa, id_reserva)

    def _traducir(self, error: ClientError, mapa, id_reserva) -> ResultadoEscritura:
        """Traduce el fallo del motor a un resultado sin interpretar reglas.

        Prioridad, y esta escrita porque no es obvia:
          1. CAPACIDAD    reintentar no ayuda y no hay constancia de que la
                          solicitud llegara a disputar -> SYS-CAPACIDAD.
          2. CONDICION    definitivo: la condicion no va a volverse cierta.
                          Reintentar solo produciria el mismo fallo.
          3. CONFLICTO    transitorio: es lo unico que se reintenta (N-f).
        """
        codigo = error.response.get("Error", {}).get("Code", "")
        if codigo != "TransactionCanceledException":
            if codigo in (
                "ProvisionedThroughputExceededException",
                "ThrottlingException",
                "RequestLimitExceeded",
            ):
                return ResultadoEscritura(TipoResultado.CAPACIDAD, detalle=codigo)
            raise error

        razones = error.response.get("CancellationReasons", []) or []
        fallos: list[ItemEnFallo] = []
        for indice, razon in enumerate(razones):
            code = razon.get("Code") or "None"
            if code == "None":
                continue
            try:
                clase, franja = mapa[indice]
            except IndexError:  # pragma: no cover - defensivo
                clase, franja = ClaseItem.CABECERA, None
            try:
                razon_enum = RazonCancelacion(code)
            except ValueError:
                razon_enum = RazonCancelacion.OTRA
            fallos.append(
                ItemEnFallo(
                    clase=clase,
                    razon=razon_enum,
                    franja=franja,
                    item_devuelto=razon.get("Item"),
                )
            )

        tupla = tuple(fallos)
        detalle = ", ".join(f"{f.clase.value}:{f.razon.value}" for f in tupla) or codigo

        if any(
            f.razon in (RazonCancelacion.CAPACIDAD, RazonCancelacion.ESTRANGULADA)
            for f in tupla
        ):
            return ResultadoEscritura(TipoResultado.CAPACIDAD, tupla, detalle=detalle)
        if any(f.razon is RazonCancelacion.CONDICION for f in tupla):
            return ResultadoEscritura(
                TipoResultado.CONDICION_INCUMPLIDA, tupla, id_reserva, detalle
            )
        if any(f.razon is RazonCancelacion.CONFLICTO for f in tupla):
            return ResultadoEscritura(TipoResultado.CONFLICTO, tupla, detalle=detalle)
        return ResultadoEscritura(TipoResultado.CONFLICTO, tupla, detalle=detalle)
