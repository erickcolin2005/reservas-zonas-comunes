"""M9 — captura de evidencia del estado real desplegado en AWS.

**Es el unico gasto irreversible del proyecto** (CE-3). Si la cuenta desaparece
sin esta captura, no se recupera a ningun precio: no se puede volver a fotografiar
una infraestructura que ya no existe. Por eso M9 rompe el orden a proposito y
empieza en I-3 en vez de en I-7 — se captura en cuanto hay algo que capturar.

QUE CAPTURA ESTA HERRAMIENTA, Y QUE NO

  SI: el estado verificable de la infraestructura, leido del propio AWS y con
  fecha. Que la tabla existe, en que modo, con cuanta capacidad, sin replicas;
  que los presupuestos existen y con que configuracion; que la accion de
  denegacion es automatica. Es evidencia **comprobable**: cualquiera que lea el
  IaC puede contrastar que lo desplegado coincide con lo declarado.

  NO: capturas de pantalla ni video. Esta herramienta no ve la consola. La
  captura visual del sistema funcionando -que es la otra mitad de M9- la tiene
  que hacer una persona, y adquiere sentido cuando exista interfaz (I-6).

POR QUE ESTO ES EVIDENCIA Y NO UN VOLCADO

  Un `describe-table` crudo no dice nada a quien lo lee: hay que saber que
  buscar. Aqui cada dato va con la afirmacion del proyecto que sostiene, para
  que un revisor pueda comprobar la afirmacion en vez de creersela. Y donde un
  dato NO se pudo leer, se dice - no se rellena.

Uso:  RESERVAS_MOTOR_REAL=1 python -m herramientas.m9_captura
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys

import boto3
from botocore.exceptions import ClientError

from reservas import config

EVIDENCIA = pathlib.Path(__file__).resolve().parent.parent / "evidencia"
CUENTA = re.compile(r"\b\d{12}\b")


def _sin_cuenta(texto: str) -> str:
    """El ID de cuenta no se publica. No es secreto, pero no aporta y se enmascara."""
    return CUENTA.sub("<CUENTA>", texto)


def _seguro(fn, *a, **kw):
    """Ejecuta o declara por que no pudo. Nunca inventa el dato."""
    try:
        return fn(*a, **kw), None
    except ClientError as e:
        return None, f"[NO LEIDO] {e.response['Error']['Code']}: {e.response['Error']['Message']}"
    except Exception as e:  # noqa: BLE001
        return None, f"[NO LEIDO] {type(e).__name__}: {e}"


def capturar() -> str:
    ddb = boto3.client("dynamodb", region_name=config.REGION)
    cfn = boto3.client("cloudformation", region_name=config.REGION)
    bud = boto3.client("budgets", region_name=config.REGION)
    sts = boto3.client("sts", region_name=config.REGION)

    ident, err_id = _seguro(sts.get_caller_identity)
    cuenta = ident["Account"] if ident else None

    L: list[str] = [
        "M9 — evidencia del estado desplegado en AWS",
        "=" * 70,
        f"Capturado: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}",
        f"Region: {config.REGION}",
        "El identificador de cuenta se enmascara como <CUENTA>.",
        "",
        "Esta captura se lee contra el IaC del repositorio: lo desplegado debe",
        "coincidir con lo declarado en infra/. Si difiere, hay deriva.",
        "",
    ]

    # -- 1. La tabla ---------------------------------------------------------
    L += ["-" * 70, "1. LA TABLA — sostiene C1 y el presupuesto de escritura", "-" * 70, ""]
    tabla, err = _seguro(ddb.describe_table, TableName=config.TABLA)
    if err:
        L += [f"  {err}", ""]
    else:
        t = tabla["Table"]
        prov = t.get("ProvisionedThroughput", {})
        replicas = t.get("Replicas", [])
        gsi = t.get("GlobalSecondaryIndexes", [])
        ttl, err_ttl = _seguro(ddb.describe_time_to_live, TableName=config.TABLA)
        L += [
            f"  nombre .................. {t['TableName']}",
            f"  estado .................. {t['TableStatus']}",
            f"  creada .................. {t['CreationDateTime'].isoformat()}",
            f"  clave ................... {[k['AttributeName'] + ':' + k['KeyType'] for k in t['KeySchema']]}",
            f"  RCU / WCU ............... {prov.get('ReadCapacityUnits')} / {prov.get('WriteCapacityUnits')}",
            f"  clase ................... {t.get('TableClassSummary', {}).get('TableClass', 'STANDARD (por defecto)')}",
            f"  indices secundarios ..... {len(gsi)}",
            f"  replicas ................ {len(replicas)}",
            f"  ttl ..................... {ttl['TimeToLiveDescription'] if ttl else err_ttl}",
            "",
            "  QUE AFIRMA ESTO:",
            f"    - modo APROVISIONADO con {prov.get('WriteCapacityUnits')} WCU: es lo que exige el free",
            "      tier perpetuo. Bajo demanda saldria de el en silencio (CE-1 A2).",
            f"    - {len(replicas)} replicas: sin replicacion multirregion, que romperia C1 en",
            "      silencio por resolucion ultimo-en-escribir (CE-1 A1).",
            f"    - {len(gsi)} indices secundarios: una sola tabla, como fija ADR-24.",
            "",
        ]

    # -- 2. El guardarrail ---------------------------------------------------
    L += ["-" * 70, "2. EL GUARDARRAIL — lo unico que separa el proyecto de una factura", "-" * 70, ""]
    presu, err = _seguro(bud.describe_budgets, AccountId=cuenta, MaxResults=20)
    if err or not cuenta:
        L += [f"  {err or '[NO LEIDO] sin identidad de cuenta'}", ""]
    else:
        for b in presu.get("Budgets", []):
            ct = b.get("CostTypes", {})
            L += [
                f"  presupuesto ............. {b['BudgetName']}",
                f"    tipo / periodo ........ {b['BudgetType']} / {b['TimeUnit']}",
                f"    limite ................ {b.get('BudgetLimit', {}).get('Amount')} "
                f"{b.get('BudgetLimit', {}).get('Unit')}",
                f"    IncludeCredit ......... {ct.get('IncludeCredit')}",
                "",
            ]
        L += [
            "  QUE AFIRMA ESTO:",
            "    - hay DOS presupuestos porque necesitan agregaciones opuestas. El de",
            "      IncludeCredit=False mide el gasto BRUTO: si midiera el neto marcaria",
            "      ~0 mientras los creditos se vacian, porque el credito absorbe el",
            "      cargo. Es D-P4-13.",
            "",
        ]

    acciones, err = _seguro(bud.describe_budget_actions_for_account, AccountId=cuenta) if cuenta else (None, "[NO LEIDO]")
    if err:
        L += [f"  {err}", ""]
    else:
        for a in acciones.get("Actions", []):
            L += [
                f"  accion .................. {a['ActionType']}",
                f"    modelo de aprobacion .. {a['ApprovalModel']}",
                f"    estado ................ {a['Status']}",
                f"    umbral ................ {a['ActionThreshold'].get('ActionThresholdValue')}"
                f" ({a['ActionThreshold'].get('ActionThresholdType')})",
                "",
            ]
        L += [
            "  QUE AFIRMA ESTO:",
            "    - APPLY_IAM_POLICY es el unico tipo viable aqui: APPLY_SCP_POLICY exige",
            "      AWS Organizations, que convierte la cuenta en facturable (CE-1 B1).",
            "    - AUTOMATIC, no MANUAL. Con MANUAL el freno no frena: espera.",
            "",
        ]

    # -- 3. Las pilas --------------------------------------------------------
    L += ["-" * 70, "3. LAS PILAS — todo se creo por IaC, nada a mano", "-" * 70, ""]
    pilas, err = _seguro(
        cfn.describe_stacks
    )
    if err:
        L += [f"  {err}", ""]
    else:
        for p in pilas.get("Stacks", []):
            L += [
                f"  {p['StackName']:<24} {p['StackStatus']:<20} "
                f"creada {p['CreationTime'].isoformat(timespec='seconds')}",
            ]
        L += [
            "",
            "  QUE AFIRMA ESTO:",
            "    - el guardarrail se desplego ANTES que la tabla, y ese orden es la",
            "      condicion D-P4-01: nada se crea en la cuenta antes del freno.",
            "    - todo es reconstruible con un comando. Es lo que hace que la senal",
            "      sobreviva al cierre de la cuenta (D-P4-03).",
            "",
        ]

    L += [
        "=" * 70,
        "LO QUE ESTA CAPTURA NO CUBRE, y hace falta una persona para ello:",
        "  - captura visual (pantalla o video) del sistema funcionando. Tiene",
        "    sentido cuando exista interfaz, en I-6.",
        "  - H0-b: que Budgets aplique la denegacion por si solo al cruzar el",
        "    umbral. No se ha observado y no se afirma.",
    ]
    return _sin_cuenta("\n".join(L))


def main() -> int:
    if not config.motor_real():
        print(
            "M9 captura el estado REAL desplegado.\n"
            f"  {config.VARIABLE_MOTOR_REAL}=1 python -m herramientas.m9_captura"
        )
        return 2
    texto = capturar()
    print(texto)
    EVIDENCIA.mkdir(exist_ok=True)
    destino = EVIDENCIA / "m9-estado-desplegado.txt"
    destino.write_text(texto + "\n", encoding="utf-8")
    print(f"\n[evidencia] {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
