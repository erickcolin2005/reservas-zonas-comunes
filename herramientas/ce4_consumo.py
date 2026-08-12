"""CE-4 — cuanto consume UNA solicitud, y de ahi cuantas caben.

La condicion economica CE-4 pide una cosa concreta y no otra:

    "No hace falta optimizar el consumo -esta excluido del alcance con razon-
     hace falta saber si esta ACOTADO."

Y desde D-P4-17 dejo de ser prudencia: la cuenta esta en Plan de Pago y con cero
creditos, asi que **CE-4 es la unica defensa economica del proyecto**. Lo que
desborde el free tier ya no lo paga un credito.

COMO SE MIDE, Y POR QUE NO SE ESTIMA

  El cliente de DynamoDB se envuelve en un proxy que anade
  `ReturnConsumedCapacity` a cada llamada y **suma lo que el motor dice que
  consumio**. No se cuenta items ni se multiplica por el factor de V-8: se lee
  la cifra del propio motor.

  La diferencia importa. Estimar el consumo a partir del modelo seria *medir la
  cosa parecida*: el numero de items que yo creo que escribe una reserva no es
  el numero de unidades de capacidad que el motor cobra por ella.

  El sembrado se mide aparte y NO se suma: ocurre una vez por corrida, no por
  solicitud, y mezclarlo inflaria el coste unitario.

Uso:  RESERVAS_MOTOR_REAL=1 python -m herramientas.ce4_consumo
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from reservas import config, sembrado
from reservas.adaptadores import dynamodb
from reservas.casos_uso.reservar import reservar
from reservas.nucleo import tiempo
from reservas.nucleo.modelo import Solicitud

EVIDENCIA = pathlib.Path(__file__).resolve().parent.parent / "evidencia"

# Limites Always Free / free tier, de la documentacion oficial (pre-F0 §2).
WCU_LIBRES = 25
RCU_LIBRES = 25
HORAS_MES = 730
LAMBDA_PETICIONES_MES = 1_000_000
APIGW_LLAMADAS_MES = 1_000_000


@dataclass
class Contador:
    """Suma lo que el motor dice que consumio. No lo deduce."""

    rcu: float = 0.0
    wcu: float = 0.0
    llamadas: dict = field(default_factory=dict)

    def anotar(self, operacion: str, respuesta) -> None:
        self.llamadas[operacion] = self.llamadas.get(operacion, 0) + 1
        cc = respuesta.get("ConsumedCapacity") if isinstance(respuesta, dict) else None
        if cc is None:
            return
        entradas = cc if isinstance(cc, list) else [cc]
        for e in entradas:
            unidades = e.get("CapacityUnits", 0.0)
            # DynamoDB separa lectura y escritura cuando puede; si no, se
            # atribuye por el tipo de operacion. Se declara la heuristica en vez
            # de presentarla como dato del motor.
            if "Write" in operacion or operacion in {"transact_write_items", "put_item", "batch_write_item"}:
                self.wcu += e.get("WriteCapacityUnits", unidades)
            else:
                self.rcu += e.get("ReadCapacityUnits", unidades)


class ClienteMedido:
    """Proxy que anade ReturnConsumedCapacity y acumula. No cambia la semantica."""

    _SIN_CAPACIDAD = {"describe_table", "create_table", "delete_table",
                      "get_waiter", "describe_time_to_live", "update_time_to_live",
                      "get_paginator", "meta", "exceptions"}

    def __init__(self, cliente, contador: Contador):
        self._c = cliente
        self._n = contador

    def __getattr__(self, nombre):
        atributo = getattr(self._c, nombre)
        if nombre in self._SIN_CAPACIDAD or not callable(atributo):
            return atributo

        def envuelto(**kw):
            kw.setdefault("ReturnConsumedCapacity", "TOTAL")
            try:
                respuesta = atributo(**kw)
            except TypeError:
                kw.pop("ReturnConsumedCapacity", None)
                respuesta = atributo(**kw)
            self._n.anotar(nombre, respuesta)
            return respuesta

        return envuelto


def _medir_una_reserva(cliente, t0, conjunto, indice: int) -> Contador:
    contador = Contador()
    medido = ClienteMedido(cliente, contador)
    adaptador = dynamodb.AdaptadorDynamoDB(medido, config.TABLA)
    solicitud = Solicitud(
        unidad=conjunto.rafaga[indice],
        espacio="E-CAN",
        inicio=tiempo.instante_mas(t0, 4, 10 + (indice % 5)),
        n_franjas=1,
    )
    reservar(solicitud, adaptador, t0)
    return contador


def main() -> int:
    if not config.motor_real():
        print(f"CE-4 mide el motor real.\n  {config.VARIABLE_MOTOR_REAL}=1 "
              "python -m herramientas.ce4_consumo")
        return 2

    cliente = dynamodb.crear_cliente()
    t0 = tiempo.t0_desde(datetime.now(timezone.utc))
    dynamodb.recrear_tabla(cliente, config.TABLA)
    conjunto = sembrado.sembrar(cliente, config.TABLA, t0)

    # Se miden varias y se toma la MAYOR, no la media: para acotar hace falta el
    # peor caso observado, no el tipico.
    medidas = [_medir_una_reserva(cliente, t0, conjunto, i) for i in range(5)]
    peor = max(medidas, key=lambda c: c.wcu)
    wcu, rcu = peor.wcu, peor.rcu

    # De WCU por solicitud a solicitudes por mes que caben en la asignacion.
    # La asignacion es 25 WCU sostenidas -unas 18.250 WCU-hora al mes-, y la
    # tabla las consume enteras solo por existir aprovisionada. Lo que acota el
    # NUMERO de solicitudes no es el mes: es la tasa instantanea.
    sol_por_segundo = (WCU_LIBRES / wcu) if wcu else float("inf")

    L = [
        "CE-4 — consumo por solicitud, medido contra el motor real",
        "=" * 70,
        f"Fecha: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "  Medido, no estimado: las cifras las devuelve el motor en",
        "  ReturnConsumedCapacity. Se toma el PEOR caso de 5 reservas, no la",
        "  media: para acotar hace falta el peor observado.",
        "",
        f"  UNA reserva confirmada consume:",
        f"    escritura ....... {wcu} WCU",
        f"    lectura ......... {rcu} RCU",
        f"    llamadas ........ {dict(sorted(peor.llamadas.items()))}",
        "",
        "-" * 70,
        "LO QUE ESO ACOTA",
        "-" * 70,
        "",
        f"  Capacidad aprovisionada: {WCU_LIBRES} WCU / {RCU_LIBRES} RCU (free tier).",
        f"  Tasa sostenida sin estrangular: ~{sol_por_segundo:.1f} reservas/segundo.",
        "",
        "  M2-INS — el instrumento (>=50 solicitudes por ejecucion):",
        f"    una ejecucion consume ~{50 * wcu:.0f} WCU de golpe, muy por encima de",
        f"    los {WCU_LIBRES} sostenidos. **Cabe por el deposito de rafaga, no por la",
        "    capacidad**, y V-8 midio que el deposito se agota: sobre 5 WCU",
        "    estrangulo tras 2.176 escrituras.",
        "",
        "  M7 — la prueba de carga: su presupuesto va en SOLICITUDES TOTALES y",
        "  no en duracion, que es lo que la hace acotable por adelantado.",
        "",
        "-" * 70,
        "EL LIMITE QUE NO ES DYNAMODB",
        "-" * 70,
        "",
        f"  Lambda: {LAMBDA_PETICIONES_MES:,} peticiones/mes gratis (perpetuo).",
        f"  API Gateway: {APIGW_LLAMADAS_MES:,} llamadas/mes (oferta de 12 meses,",
        "  activa en Plan de Pago). **[NV] en ESTA cuenta**: la API de free tier",
        "  no devuelve registros hasta que haya uso.",
        "",
        f"  A {50} solicitudes por ejecucion del instrumento, agotar el millon de",
        f"  API Gateway exigiria {APIGW_LLAMADAS_MES // 50:,} ejecuciones en un mes.",
        "  **No es el limite que aprieta.** El que aprieta es la capacidad",
        "  instantanea de DynamoDB, y su sintoma no es una factura: es",
        "  SYS-CAPACIDAD, que invalida la medicion.",
    ]
    texto = "\n".join(L)
    print(texto)
    EVIDENCIA.mkdir(exist_ok=True)
    (EVIDENCIA / "ce4-consumo-por-solicitud.txt").write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
