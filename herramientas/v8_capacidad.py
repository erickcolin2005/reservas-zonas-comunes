"""V-8 — multiplicador de capacidad, limite de items por transaccion y ráfaga.

Las tres cifras alimentan decisiones que hoy estan tomadas sobre supuestos:

  - El **multiplicador**: una transaccion no cuesta lo mismo que una escritura
    suelta. Si cuesta el doble, el presupuesto de 25 WCU rinde la mitad de lo
    que parece, y el orden de degradacion de RR-08 se dispara antes de lo
    previsto.
  - El **limite de items por transaccion**: el peor caso del modelo son 14
    items (E-SAL con 6 franjas). Saber donde esta el techo real dice cuanto
    margen hay.
  - El **deposito de ráfaga**: DynamoDB acumula capacidad no usada. Es lo que
    explica que 200 escrituras seguidas no estrangulen en una tabla de 5 WCU, y
    lo que hace que una medicion corta diga que hay mas capacidad de la que hay
    de forma sostenida.

POR QUE ESTO NO CUESTA DINERO, que es la pregunta obvia con la cuenta en Plan
de Pago y sin creditos:

    En modo APROVISIONADO se paga por la capacidad reservada, no por peticion.
    Pasarse no cuesta mas: **estrangula**. Asi que forzar el estrangulamiento
    es gratis por construccion, y ese es justamente el motivo por el que el
    proyecto usa modo aprovisionado y por el que pasarlo a bajo demanda es una
    accion prohibida (CE-1, fila A2) - alli si se paga por peticion.

Uso:  RESERVAS_MOTOR_REAL=1 python -m herramientas.v8_capacidad
"""

from __future__ import annotations

import pathlib
import sys
import time

from botocore.exceptions import ClientError

from reservas import config
from reservas.adaptadores.dynamodb import (
    N,
    S,
    borrar_tabla,
    crear_cliente,
    crear_tabla,
)

TABLA = "v8-sonda"
WCU_SONDA = 5
"""Capacidad pequena a proposito: la tabla principal ya consume el free tier
entero (25 WCU). Ademas, cuanto menor es la capacidad antes se agota el
deposito, asi que una tabla pequena hace la medicion MAS barata en tiempo, no
menos fiable: lo que se mide es la relacion entre lo consumido y lo aprovisionado."""

EVIDENCIA = pathlib.Path(__file__).resolve().parent.parent / "evidencia"


def _consumo(respuesta) -> float:
    cc = respuesta.get("ConsumedCapacity")
    if isinstance(cc, list):
        return sum(x.get("CapacityUnits", 0.0) for x in cc)
    return (cc or {}).get("CapacityUnits", 0.0)


def multiplicador(cliente) -> tuple[str, float | None]:
    """¿Cuanto cuesta un item dentro de una transaccion frente a suelto?"""
    suelto = cliente.put_item(
        TableName=TABLA,
        Item={"PK": S("m"), "SK": S("suelto"), "x": N(1)},
        ReturnConsumedCapacity="TOTAL",
    )
    c_suelto = _consumo(suelto)

    tx = cliente.transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": TABLA,
                    "Item": {"PK": S("m"), "SK": S(f"tx{i}"), "x": N(i)},
                }
            }
            for i in range(2)
        ],
        ReturnConsumedCapacity="TOTAL",
    )
    c_tx = _consumo(tx)
    por_item = c_tx / 2 if c_tx else 0.0
    if not c_suelto:
        return ("[NV] el motor no devolvio capacidad consumida", None)
    factor = por_item / c_suelto
    return (
        f"escritura suelta = {c_suelto} WCU · transaccion de 2 items = {c_tx} WCU "
        f"({por_item} por item) → MULTIPLICADOR x{factor:g}",
        factor,
    )


def limite_items(cliente) -> str:
    """Techo real de items por transaccion."""
    aceptados, rechazado = [], None
    for n in (14, 25, 100, 101):
        items = [
            {
                "Put": {
                    "TableName": TABLA,
                    "Item": {"PK": S(f"lim{n}"), "SK": S(f"{i:04d}")},
                }
            }
            for i in range(n)
        ]
        try:
            cliente.transact_write_items(TransactItems=items)
            aceptados.append(n)
        except ClientError as e:
            rechazado = f"{n}:{e.response['Error']['Code']}"
            break
    return (
        f"aceptados {aceptados} · primer rechazo {rechazado}. "
        f"El peor caso del modelo son 14 items: margen holgado."
    )


def deposito_rafaga(cliente, techo: int = 3000) -> str:
    """Escribe a tope hasta que estrangule, y cuenta cuanto aguanto.

    `techo` es un presupuesto en PETICIONES, no en tiempo -misma regla que M7-.
    Si se agota sin estrangular, se dice que no se agoto: NO se concluye que no
    haya limite.
    """
    inicio = time.monotonic()
    escritas = 0
    for i in range(techo):
        try:
            cliente.put_item(
                TableName=TABLA, Item={"PK": S("raf"), "SK": S(f"{i:06d}")}
            )
            escritas += 1
        except ClientError as e:
            if "Throughput" in e.response["Error"]["Code"]:
                seg = time.monotonic() - inicio
                tasa = escritas / seg if seg else 0
                return (
                    f"ESTRANGULO tras {escritas} escrituras en {seg:.1f}s "
                    f"({tasa:.1f}/s sostenidas sobre {WCU_SONDA} WCU "
                    f"aprovisionadas). El exceso sobre lo aprovisionado es el "
                    f"deposito de rafaga acumulado."
                )
            raise
    seg = time.monotonic() - inicio
    return (
        f"[NV] NO estrangulo en {escritas} escrituras ({seg:.1f}s, "
        f"{escritas / seg if seg else 0:.1f}/s). El presupuesto de peticiones se "
        f"agoto antes que el deposito. NO se concluye que no estrangule: se "
        f"concluye que esta medicion no alcanzo el limite."
    )


def main() -> int:
    if not config.motor_real():
        print(
            f"V-8 mide el MOTOR REAL. El sustituto local ignora la capacidad "
            f"aprovisionada, asi que aqui no medirIa nada.\n"
            f"  {config.VARIABLE_MOTOR_REAL}=1 python -m herramientas.v8_capacidad"
        )
        return 2

    cliente = crear_cliente()
    lineas = [
        "V-8 — capacidad del motor real",
        "=" * 70,
        "",
        f"  tabla de sonda: {TABLA} a {WCU_SONDA} WCU / {WCU_SONDA} RCU",
        "  (pequena a proposito: la tabla principal ya consume el free tier)",
        "",
        "  En modo aprovisionado pasarse NO cuesta dinero: estrangula.",
        "  Forzar el estrangulamiento es gratis por construccion.",
        "",
    ]
    borrar_tabla(cliente, TABLA)
    crear_tabla(cliente, TABLA, rcu=WCU_SONDA, wcu=WCU_SONDA)
    try:
        texto_mult, factor = multiplicador(cliente)
        lineas += ["  V8-1  Multiplicador de capacidad de la transaccion",
                   f"        {texto_mult}", ""]
        if factor and factor >= 2:
            lineas += [
                f"        CONSECUENCIA: el presupuesto de 25 WCU rinde ~{25 / factor:g} "
                "escrituras transaccionales por segundo, no 25. El orden de",
                "        degradacion de RR-08 (arquitectura §14) se calcula sobre",
                "        esta cifra, no sobre la nominal.",
                "",
            ]
        lineas += ["  V8-2  Limite de items por transaccion",
                   f"        {limite_items(cliente)}", ""]
        lineas += ["  V8-3  Deposito de rafaga",
                   f"        {deposito_rafaga(cliente)}", ""]
    finally:
        borrar_tabla(cliente, TABLA)
        lineas.append("  (tabla de sonda borrada)")

    lineas += ["", "=" * 70,
               "Lo que V-8 NO mide: el comportamiento de la tabla principal a 25",
               "WCU bajo la carga de M7. Eso es la prueba de carga, y tiene su",
               "propio presupuesto en solicitudes."]
    texto = "\n".join(lineas)
    print(texto)
    EVIDENCIA.mkdir(exist_ok=True)
    destino = EVIDENCIA / "v8-capacidad-motor-real.txt"
    destino.write_text(texto + "\n", encoding="utf-8")
    print(f"\n[evidencia] {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
