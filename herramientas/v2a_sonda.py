"""V-2a — ¿el sustituto local implementa escritura condicional y transacciones,
y con que semantica de error?

Es lo PRIMERO que se ejecuta en I-1 (plan §2.3). El motivo no es ceremonia: si
el sustituto no implementa las dos cosas, **el CI no puede correr los casos K,
T7a se declara incumplida en el README, y hay que replantear la puerta de AWS**.
Construir el modelo antes de saberlo seria construir sobre un motor que no puede
ejecutar el mecanismo que lo sostiene.

Lo que esta sonda NO hace, y hay que decirlo porque es la mitad del asunto:
**no compara con el motor real**. Eso es V-2b y vive en I-3. La asimetria que
gobierna todo el tramo local es contraintuitiva y conviene tenerla escrita:

    un sustituto local serializa MAS que el servicio real, asi que
    dos confirmaciones en local  ==> dos confirmaciones en AWS  (refutacion valida)
    una confirmacion en local    =/=> una confirmacion en AWS   (confirmacion NO valida)

Por eso H1 es provisional hasta I-3.

Uso:  python -m herramientas.v2a_sonda
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from datetime import date

from botocore.exceptions import ClientError

from reservas import config
from reservas.adaptadores.dynamodb import N, S, crear_cliente, recrear_tabla

TABLA_SONDA = "v2a-sonda"


@dataclass
class Hallazgo:
    """Una pregunta, su respuesta observada y por que importa."""

    id: str
    pregunta: str
    respuesta: str
    detalle: str = ""
    bloqueante: bool = False
    ok: bool | None = None

    def linea(self) -> str:
        marca = "??" if self.ok is None else ("OK" if self.ok else "NO")
        return f"  [{marca}] {self.id}  {self.pregunta}\n       -> {self.respuesta}"


@dataclass
class Informe:
    hallazgos: list = field(default_factory=list)

    def anadir(self, *args, **kwargs) -> None:
        self.hallazgos.append(Hallazgo(*args, **kwargs))

    def por_id(self, id_: str) -> Hallazgo:
        for h in self.hallazgos:
            if h.id == id_:
                return h
        raise KeyError(id_)

    @property
    def veredicto_v2a(self) -> bool:
        """V-2a sale positiva si TODO lo bloqueante esta implementado."""
        return all(h.ok for h in self.hallazgos if h.bloqueante)

    def texto(self) -> str:
        # La sonda es la misma para los dos motores, pero el informe TIENE que
        # decir contra cual corrio. Cuando se ejecuto por primera vez contra
        # AWS, el fichero de evidencia salio titulado "capacidades del sustituto
        # local" y firmado "VEREDICTO V-2a" -describiendo como local una medicion
        # del motor real-. Una evidencia mal etiquetada es peor que no tenerla:
        # la primera se publica y se cree.
        real = config.motor_real()
        etiqueta = "V-1 — capacidades del MOTOR REAL (DynamoDB en AWS)" if real \
            else "V-2a — capacidades del sustituto local"
        lineas = [
            etiqueta,
            "=" * 70,
            "",
        ]
        for h in self.hallazgos:
            lineas.append(h.linea())
            if h.detalle:
                for fila in h.detalle.splitlines():
                    lineas.append(f"          {fila}")
            lineas.append("")
        lineas.append("=" * 70)
        if real:
            lineas.append(
                "VEREDICTO V-1: "
                + (
                    "POSITIVA — el motor real implementa escritura condicional "
                    "y transacciones con razones de cancelacion por item. "
                    "G-a…G-d y N-f se sostienen. H1 puede pasar de provisional "
                    "a FIRME."
                    if self.veredicto_v2a
                    else "NEGATIVA — el motor real NO sostiene alguna garantia "
                    "bloqueante. Se activa D-P4-06: se cambia de motor "
                    "documentandolo, o se publica el hallazgo en vez de la "
                    "afirmacion. Lo que NO es opcion es publicar 'cero doble "
                    "reserva' sin haberlo demostrado."
                )
            )
            lineas.append("")
            lineas.append(
                "Esta corrida SI es contra AWS. La asimetria del tramo local "
                "deja de aplicar: aqui una confirmacion vale como confirmacion."
            )
        else:
            lineas.append(
                "VEREDICTO V-2a: "
                + (
                    "POSITIVA — el sustituto implementa escritura condicional y "
                    "transacciones. El CI puede correr los casos K."
                    if self.veredicto_v2a
                    else "NEGATIVA — falta alguna capacidad bloqueante. El CI NO "
                    "puede correr los casos K y T7a se declara incumplida."
                )
            )
            lineas.append("")
            lineas.append(
                "Recordatorio: esto NO compara con el motor real (eso es V-2b, I-3). "
                "Una confirmacion en local no implica una confirmacion en AWS."
            )
        return "\n".join(lineas)


def _clave(pk: str, sk: str = "X") -> dict:
    return {"PK": S(pk), "SK": S(sk)}


def sondear(cliente, tabla: str = TABLA_SONDA) -> Informe:
    informe = Informe()
    # Capacidad pequena SOLO contra el motor real: la tabla principal ya consume
    # el free tier entero de DynamoDB (25 WCU), asi que una segunda tabla a 25
    # se sale y cuesta dinero. 5 unidades sobran para una sonda de correccion
    # -escribe decenas de items, no miles- y no llegan a estrangular.
    # Contra el sustituto local la capacidad es ficcion: se usan los valores de
    # config para no introducir una diferencia gratuita entre los dos motores.
    pequena = 5 if config.motor_real() else None
    recrear_tabla(cliente, tabla, rcu=pequena, wcu=pequena)

    # -- 1 · escritura condicional sobre un item --------------------------
    cliente.put_item(
        TableName=tabla,
        Item={**_clave("cond"), "duena": S("primera")},
        ConditionExpression="attribute_not_exists(PK)",
    )
    try:
        cliente.put_item(
            TableName=tabla,
            Item={**_clave("cond"), "duena": S("segunda")},
            ConditionExpression="attribute_not_exists(PK)",
        )
        informe.anadir(
            "V2a-1",
            "¿La escritura condicional impide la segunda escritura?",
            "NO. La segunda escritura fue ACEPTADA.",
            detalle="Sin esto no hay mecanismo: C1 no se puede sostener.",
            bloqueante=True,
            ok=False,
        )
    except ClientError as error:
        codigo = error.response["Error"]["Code"]
        informe.anadir(
            "V2a-1",
            "¿La escritura condicional impide la segunda escritura?",
            f"SI. Codigo de error: {codigo}",
            detalle="Es la garantia G-b: a lo sumo una escritura condicional "
            "aplica sobre la misma clave.",
            bloqueante=True,
            ok=(codigo == "ConditionalCheckFailedException"),
        )

    # -- 2 · ¿devuelve el item que incumplio la condicion? -----------------
    try:
        cliente.put_item(
            TableName=tabla,
            Item={**_clave("cond"), "duena": S("tercera")},
            ConditionExpression="attribute_not_exists(PK)",
            ReturnValuesOnConditionCheckFailure="ALL_OLD",
        )
        devuelto = None
    except ClientError as error:
        devuelto = error.response.get("Item")
    informe.anadir(
        "V2a-2",
        "¿Devuelve el item ganador cuando la condicion falla (ALL_OLD)?",
        "SI: " + repr(devuelto) if devuelto else "NO devuelve el item.",
        detalle="Si lo devuelve, RR-09 se distingue de RR-11 sin lectura extra "
        "y la idempotencia de ADR-25 sale gratis. Si no, hace falta un GetItem "
        "en el camino perdedor. **El diseno funciona con las dos respuestas.**",
        bloqueante=False,
        ok=bool(devuelto),
    )

    # -- 3 · transacciones ------------------------------------------------
    try:
        cliente.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": tabla,
                        "Item": {**_clave("tx", "A")},
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
                {
                    "Put": {
                        "TableName": tabla,
                        "Item": {**_clave("tx", "B")},
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
            ]
        )
        informe.anadir(
            "V2a-3",
            "¿Implementa TransactWriteItems?",
            "SI. Transaccion de 2 items aceptada.",
            bloqueante=True,
            ok=True,
        )
    except ClientError as error:
        informe.anadir(
            "V2a-3",
            "¿Implementa TransactWriteItems?",
            f"NO. {error.response['Error']['Code']}: "
            f"{error.response['Error'].get('Message', '')}",
            detalle="Sin transaccion, el solapamiento parcial (K-02) no se "
            "puede cerrar: cada solicitud se queda con la mitad de las franjas "
            "y ninguna confirma.",
            bloqueante=True,
            ok=False,
        )

    # -- 4 · todo o nada, y la forma de las razones de cancelacion --------
    razones = None
    try:
        cliente.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": tabla,
                        "Item": {**_clave("tx2", "LIBRE")},
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
                {
                    "Put": {
                        "TableName": tabla,
                        "Item": {**_clave("tx", "A"), "duena": S("intrusa")},
                        "ConditionExpression": "attribute_not_exists(PK)",
                        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
                    }
                },
            ]
        )
        informe.anadir(
            "V2a-4",
            "¿La transaccion es todo-o-nada ante una condicion incumplida?",
            "NO. Se aplico pese a que una condicion no se cumplia.",
            bloqueante=True,
            ok=False,
        )
    except ClientError as error:
        codigo = error.response["Error"]["Code"]
        razones = error.response.get("CancellationReasons")
        sobrevivio = cliente.get_item(
            TableName=tabla, Key=_clave("tx2", "LIBRE"), ConsistentRead=True
        ).get("Item")
        informe.anadir(
            "V2a-4",
            "¿La transaccion es todo-o-nada ante una condicion incumplida?",
            f"SI. {codigo}; el item que SI podia escribirse "
            + ("quedo escrito (MAL)" if sobrevivio else "NO quedo escrito (bien)"),
            detalle=f"CancellationReasons = {razones!r}",
            bloqueante=True,
            ok=(codigo == "TransactionCanceledException" and not sobrevivio),
        )

    codigos = [r.get("Code") for r in (razones or [])]
    informe.anadir(
        "V2a-5",
        "¿Las razones de cancelacion llegan una por item y en orden?",
        f"{'SI' if codigos else 'NO'}. Codigos observados: {codigos}",
        detalle="Es lo unico que permite saber CUAL condicion fallo y, con "
        "ello, atribuir RR-07 / RR-08 / RR-11 en vez de decir 'fallo algo'.",
        bloqueante=True,
        ok=bool(codigos) and codigos[0] == "None" and "ConditionalCheckFailed" in codigos,
    )

    item_en_razon = next(
        (r.get("Item") for r in (razones or []) if r.get("Item")), None
    )
    informe.anadir(
        "V2a-6",
        "¿La razon de cancelacion trae el item ganador?",
        "SI: " + repr(item_en_razon) if item_en_razon else "NO lo trae.",
        detalle="Con el, RR-09 vs RR-11 y la idempotencia de ADR-25 no cuestan "
        "una lectura extra. El diseno funciona con las dos respuestas.",
        bloqueante=False,
        ok=bool(item_en_razon),
    )

    # -- 5 · limite de items por transaccion ------------------------------
    limite_ok, limite_no = [], []
    for cuantos in (14, 25, 100, 101):
        try:
            cliente.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": tabla,
                            "Item": {**_clave(f"lim{cuantos}", f"{i:03d}")},
                        }
                    }
                    for i in range(cuantos)
                ]
            )
            limite_ok.append(cuantos)
        except ClientError as error:
            limite_no.append(f"{cuantos}:{error.response['Error']['Code']}")
    informe.anadir(
        "V2a-7",
        "¿Cuantos items admite una transaccion?",
        f"aceptados {limite_ok} · rechazados {limite_no}",
        detalle="El maximo del modelo es 14 items (E-SAL con 6 franjas). El "
        "diseno queda por debajo del limite a proposito, para no depender de "
        "cual sea el valor exacto.",
        bloqueante=True,
        ok=14 in limite_ok,
    )

    # -- 6 · contador condicional (el cupo, y el contador de intentos) ----
    cliente.put_item(TableName=tabla, Item={**_clave("cnt"), "contador": N(0)})
    aceptados = 0
    ultimo_codigo = ""
    for _ in range(5):
        try:
            cliente.update_item(
                TableName=tabla,
                Key=_clave("cnt"),
                UpdateExpression="ADD contador :uno",
                ConditionExpression=(
                    "attribute_not_exists(contador) OR contador < :tope"
                ),
                ExpressionAttributeValues={":uno": N(1), ":tope": N(3)},
            )
            aceptados += 1
        except ClientError as error:
            ultimo_codigo = error.response["Error"]["Code"]
    informe.anadir(
        "V2a-8",
        "¿Un contador con condicion 'contador < tope' corta en el tope?",
        f"{aceptados} incrementos aceptados de 5 (tope 3). Ultimo error: "
        f"{ultimo_codigo or 'ninguno'}",
        detalle="Es la segunda carrera: dos solicitudes de la misma unidad en "
        "franjas distintas no comparten clave de franja, pero si comparten esta "
        "(K-05). Y es la forma del contador de intentos de SEC-1 (I-6).",
        bloqueante=True,
        ok=(aceptados == 3),
    )

    # -- 7 · ¿aparece TransactionConflict bajo concurrencia real? ---------
    conflictos = _sondear_conflicto(cliente, tabla)
    informe.anadir(
        "V2a-9",
        "¿Produce TransactionConflict bajo transacciones concurrentes?",
        f"codigos observados: {conflictos}",
        detalle="N-f. Si el sustituto NUNCA produce conflicto —porque serializa "
        "por construccion—, el reintento de ADR-04 queda sin ejercitar en local "
        "y su primera prueba real es I-3. Se declara; no se disimula.",
        bloqueante=False,
        ok=None if "TransactionConflict" not in conflictos else True,
    )

    # -- 8 · ¿estrangula por capacidad aprovisionada? ---------------------
    informe.anadir(
        "V2a-10",
        "¿Respeta la capacidad aprovisionada (25 WCU) y estrangula?",
        _sondear_capacidad(cliente, tabla),
        detalle="Si no estrangula, `SYS-CAPACIDAD` no se puede ejercitar en "
        "local y su primera aparicion sera contra el motor real. Es una clase "
        "de fallo que el sustituto esconde por diseno.",
        bloqueante=False,
        ok=None,
    )

    # -- 9 · ¿existe el mecanismo de expiracion? --------------------------
    try:
        cliente.update_time_to_live(
            TableName=tabla,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
        estado = cliente.describe_time_to_live(TableName=tabla)
        respuesta = f"SI, se puede activar. Estado: {estado['TimeToLiveDescription']}"
        ok = True
    except ClientError as error:
        respuesta = f"NO: {error.response['Error']['Code']}"
        ok = False
    informe.anadir(
        "V2a-11",
        "¿Admite activar la expiracion por atributo (ttl)?",
        respuesta,
        detalle="Admitir la llamada no es lo mismo que borrar. El momento del "
        "borrado es [NV] y es de V-8, no de aqui. Ninguna prueba de I-1 depende "
        "de que el sustituto borre nada.",
        bloqueante=False,
        ok=ok,
    )

    return informe


def _sondear_conflicto(cliente, tabla: str, n: int = 16) -> list:
    """Lanza n transacciones a la vez sobre el MISMO item y recoge los codigos."""
    cliente.put_item(TableName=tabla, Item={**_clave("conf"), "contador": N(0)})
    barrera = threading.Barrier(n)
    codigos: list = []
    cerrojo = threading.Lock()

    def intento() -> None:
        propio = crear_cliente()
        try:
            propio.describe_table(TableName=tabla)  # calentar la conexion
        except ClientError:
            pass
        barrera.wait(timeout=60)
        try:
            propio.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": tabla,
                            "Key": _clave("conf"),
                            "UpdateExpression": "ADD contador :uno",
                            "ExpressionAttributeValues": {":uno": N(1)},
                        }
                    }
                ]
            )
            resultado = "OK"
        except ClientError as error:
            razones = error.response.get("CancellationReasons") or []
            resultado = ",".join(r.get("Code", "?") for r in razones) or error.response[
                "Error"
            ]["Code"]
        with cerrojo:
            codigos.append(resultado)

    hilos = [threading.Thread(target=intento) for _ in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    return sorted(set(codigos))


def _sondear_capacidad(cliente, tabla: str, escrituras: int = 200) -> str:
    """Escribe muy por encima de 25 WCU y mira si alguna vez estrangula."""
    estrangulos = 0
    for i in range(escrituras):
        try:
            cliente.put_item(
                TableName=tabla, Item={**_clave("cap", f"{i:04d}"), "x": N(i)}
            )
        except ClientError as error:
            if "Throughput" in error.response["Error"]["Code"]:
                estrangulos += 1
            else:
                raise
    if estrangulos:
        return f"SI. {estrangulos} de {escrituras} escrituras estranguladas."
    if config.motor_real():
        # No concluir "el motor no respeta la capacidad": seria falso y ademas
        # es la conclusion comoda. DynamoDB acumula capacidad no usada como
        # RESERVA DE RAFAGA, asi que una tanda corta cabe entera aunque supere
        # la capacidad sostenida. Lo unico que este dato demuestra es que 200
        # escrituras seguidas no la agotan.
        return (
            f"NO en esta corrida. {escrituras} escrituras seguidas sin "
            "estrangulamiento. NO significa que no estrangule: significa que "
            "la reserva de rafaga absorbio la tanda. Medir la tasa sostenida "
            "real es V-8, con su propio procedimiento. [NV] aqui."
        )
    return (
        f"NO. {escrituras} escrituras seguidas sin un solo estrangulamiento, "
        "muy por encima de 25 WCU. El sustituto ignora la capacidad aprovisionada."
    )


def main() -> int:
    cliente = crear_cliente()
    informe = sondear(cliente)
    texto = informe.texto()
    print(texto)
    import pathlib

    destino = pathlib.Path(__file__).resolve().parent.parent / "evidencia"
    destino.mkdir(exist_ok=True)
    # El nombre del fichero DEPENDE del motor. Antes era fijo
    # ("v2a-sustituto-local.txt") y la primera corrida contra AWS sobrescribio
    # la linea base local con resultados del motor real, dejando un fichero que
    # se llamaba "sustituto local" y contenia otra cosa.
    #
    # Es el mismo defecto que el titulo mal puesto, y aqui era peor: no solo
    # etiquetaba mal, DESTRUIA el termino de comparacion. Y V-2b consiste
    # precisamente en comparar los dos, asi que la corrida que produce la mitad
    # nueva borraba la mitad vieja.
    nombre = "v1-motor-real.txt" if config.motor_real() else "v2a-sustituto-local.txt"
    (destino / nombre).write_text(texto + "\n", encoding="utf-8")
    print(f"\n[evidencia] {destino / nombre}")
    return 0 if informe.veredicto_v2a else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
