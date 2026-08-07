"""H2 — revertir la defensa y exigir que la prueba se ponga en ROJO.

**Un verde solo demuestra algo si sabe ponerse rojo.** Una prueba de
concurrencia que no ha demostrado nunca que puede fallar genera confianza
injustificada, que es peor que no tener prueba: con ella, nadie vuelve a mirar.

Esta herramienta apaga a proposito cada defensa de I-1, una por una, y **falla si
alguna mutacion sigue en verde**. El criterio esta invertido respecto de una
prueba normal:

    mutacion en ROJO  -> la defensa existe y la prueba la vigila. Correcto.
    mutacion en VERDE -> la prueba no vigila nada. Aqui se rompe el build.

Alcance: **solo las defensas de I-1**. La mutacion sobre las quince reglas es M4
y vive en I-5; esto no la sustituye ni pretende hacerlo.

Uso:  python -m herramientas.sensibilidad
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from reservas import config
from reservas.adaptadores.dynamodb import S, AdaptadorDynamoDB, crear_cliente
from reservas.nucleo import claves, tiempo
from reservas.puertos import ClaseItem

from . import casos_k


# ---------------------------------------------------------------------------
# Mutacion A · quitar la escritura condicional sobre el hueco
# ---------------------------------------------------------------------------


class SinCondicionSobreElHueco(AdaptadorDynamoDB):
    """El patron ingenuo: leo si esta libre y escribo.

    Se quita la condicion SOLO de los items de franja, para aislar la defensa
    que se esta revirtiendo. La lectura previa sigue estando, y sigue rechazando
    lo que ya estaba ocupado cuando miro — que es justamente por lo que este
    fallo es invisible en cualquier demostracion con una sola persona.

    Lo que tiene que pasar: las 50 leen libre, las 50 escriben, y el hueco acaba
    con 50 confirmaciones. **I-1 violado: doble reserva.**
    """

    def construir_items(self, intencion, token_solicitud, id_reserva):
        items, mapa = super().construir_items(intencion, token_solicitud, id_reserva)
        for item, (clase, _) in zip(items, mapa):
            if clase is ClaseItem.FRANJA:
                item["Put"].pop("ConditionExpression", None)
        return items, mapa


# ---------------------------------------------------------------------------
# Mutacion B · normalizar la clave en UTC en vez de en hora local
# ---------------------------------------------------------------------------


class NormalizaLaClaveEnUtc(AdaptadorDynamoDB):
    """La canonizacion rota, y es la mutacion que mas importa.

    Aqui **ninguna regla se viola y la escritura condicional sigue puesta**. Lo
    unico que cambia es que la clave del hueco se compone a partir de la hora en
    UTC en lugar de la hora local. A las 10:00 de Bogota le corresponden las
    15:00 UTC, asi que dos implementaciones que difieran en esto **nunca
    colisionan**: cada una escribe su propia clave, las dos condiciones se
    cumplen, y hay dos reservas del mismo hueco.

    Es el modo de fallo que el banco entero no ve: todas las reglas se cumplen,
    todos los casos A/L/R salen en verde, y el sabado hay dos fiestas en el
    salon. Si esta mutacion no pusiera la prueba en rojo, la canonizacion no
    estaria vigilada por nada.
    """

    def construir_items(self, intencion, token_solicitud, id_reserva):
        items, mapa = super().construir_items(intencion, token_solicitud, id_reserva)
        espacio = intencion.solicitud.espacio
        for item, (clase, franja) in zip(items, mapa):
            if clase is not ClaseItem.FRANJA or franja is None:
                continue
            en_utc = franja.inicio.astimezone(timezone.utc)
            item["Put"]["Item"]["PK"] = S(claves.pk_hueco(espacio, en_utc.date()))
            item["Put"]["Item"]["SK"] = S(claves.sk_hueco(en_utc.hour))
        return items, mapa


# ---------------------------------------------------------------------------
# El catalogo de mutaciones
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mutacion:
    id: str
    que_se_apaga: str
    que_deberia_pasar: str
    caso: str
    fabrica: object


def _mitad_y_mitad(clase):
    """La mitad de las solicitudes usa la implementacion mutada.

    Con TODAS mutadas, dos implementaciones coherentes entre si volverian a
    colisionar y la mutacion pasaria desapercibida. El fallo que se demuestra es
    **la discrepancia entre dos normalizaciones**, y para eso hacen falta las
    dos.
    """

    def fabrica(cliente, indice):
        if indice % 2 == 0:
            return AdaptadorDynamoDB(cliente, config.TABLA)
        return clase(cliente, config.TABLA)

    return fabrica


MUTACIONES = (
    Mutacion(
        id="M-a · sin escritura condicional sobre el hueco",
        que_se_apaga="la condicion attribute_not_exists en los items de franja",
        que_deberia_pasar="varias confirmadas sobre la misma franja: I-1 violado",
        caso="K-01",
        fabrica=lambda cliente, indice: SinCondicionSobreElHueco(cliente, config.TABLA),
    ),
    Mutacion(
        id="M-b · canonizacion de la clave en UTC",
        que_se_apaga="la regla 1 de §4.3: la clave en hora local",
        que_deberia_pasar=(
            "dos confirmadas sobre la misma franja SIN violar ninguna regla y "
            "con la escritura condicional intacta"
        ),
        caso="K-01",
        fabrica=_mitad_y_mitad(NormalizaLaClaveEnUtc),
    ),
)


NO_EJERCITABLES_EN_LOCAL = (
    (
        "M-c · marca pegajosa de ADR-04",
        "El sustituto local NUNCA devuelve TransactionConflict (V-2a, hallazgo "
        "V2a-9): serializa por construccion. Sin conflicto no hay reintento, y "
        "sin reintento la marca pegajosa no llega a usarse. **Apagarla aqui no "
        "cambiaria ningun resultado, asi que una mutacion local saldria en "
        "verde y no probaria nada.** Su primera prueba real es I-3, contra el "
        "motor real. Se declara en vez de fabricar una mutacion que pase.",
    ),
    (
        "M-d · SYS-CAPACIDAD",
        "El sustituto local ignora la capacidad aprovisionada (V-2a, hallazgo "
        "V2a-10): 200 escrituras seguidas sin un solo estrangulamiento sobre 25 "
        "WCU. El cubo SYS-CAPACIDAD existe en el codigo y no se puede ejercitar "
        "en local. I-3.",
    ),
)


def ejecutar_todas(endpoint: str, cliente, t0: datetime):
    """Corre todas las mutaciones y devuelve `(resultados, texto, fallos)`.

    La usan la linea de ordenes y el CI, para que la constancia que queda en
    disco sea **la misma** en los dos casos. Dos redacciones distintas del mismo
    hecho acaban divergiendo, y entonces nadie sabe cual leer.
    """
    partes = [
        "H2 — al revertir la defensa, la prueba se pone en ROJO",
        "=" * 70,
        "",
        "Criterio invertido: una mutacion en ROJO es el resultado CORRECTO.",
        "Si alguna mutacion sale en verde, la prueba no vigila nada.",
        "",
        f"Sustituto local: {endpoint}",
        f"T0 derivado: {t0.isoformat()}",
        "",
    ]
    fallos = []
    resultados = {}

    for mutacion in MUTACIONES:
        conjunto = casos_k.preparar(cliente, t0)
        caso = casos_k.CASOS[mutacion.caso](t0, conjunto)
        resultado = casos_k.ejecutar(
            caso, endpoint, t0, fabrica_adaptador=mutacion.fabrica
        )
        resultados[mutacion.id] = resultado
        rojo = resultado.invariantes.build_en_rojo
        partes.append("-" * 70)
        partes.append(f"MUTACION {mutacion.id}")
        partes.append(f"  se apaga ......... {mutacion.que_se_apaga}")
        partes.append(f"  deberia pasar .... {mutacion.que_deberia_pasar}")
        partes.append(f"  caso ............. {mutacion.caso}")
        partes.append(
            f"  RESULTADO ........ {'ROJO (correcto)' if rojo else 'VERDE (MAL)'}"
        )
        partes.append("")
        partes.append(resultado.texto)
        if not rojo:
            fallos.append(mutacion.id)

    partes.append("-" * 70)
    partes.append("Mutaciones que NO se pueden ejercitar contra el sustituto local:")
    partes.append("")
    for identificador, motivo in NO_EJERCITABLES_EN_LOCAL:
        partes.append(f"  {identificador}")
        for linea in _envolver(motivo, 68):
            partes.append(f"      {linea}")
        partes.append("")

    partes.append("=" * 70)
    if fallos:
        partes.append(
            "VEREDICTO H2: FALLIDO. Estas mutaciones NO pusieron la prueba en "
            "rojo, luego la prueba no vigila lo que dice vigilar: "
            + ", ".join(fallos)
        )
    else:
        partes.append(
            "VEREDICTO H2: CUMPLIDO. Todas las mutaciones pusieron la prueba en "
            "rojo. El verde de los casos K sabe ponerse rojo."
        )

    return resultados, "\n".join(partes), fallos


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="H2 — mutacion de las defensas de I-1")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--evidencia", default=None)
    args = parser.parse_args(argv)

    endpoint = args.endpoint or config.endpoint()
    cliente = crear_cliente(endpoint)
    t0 = tiempo.t0_desde(datetime.now(timezone.utc))

    _, salida, fallos = ejecutar_todas(endpoint, cliente, t0)
    print(salida)
    if args.evidencia:
        destino = pathlib.Path(args.evidencia)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(salida + "\n", encoding="utf-8")
    return 1 if fallos else 0


def _envolver(texto: str, ancho: int):
    import textwrap

    return textwrap.wrap(texto, ancho)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
