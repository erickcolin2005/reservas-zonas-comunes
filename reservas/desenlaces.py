"""Cubos de desenlace, competidoras efectivas y los tres invariantes.

Este modulo existe para no contar la cosa parecida.

El desenlace de una corrida de concurrencia **no es "se enviaron 50"**. Es
cuantas compitieron de verdad. Una solicitud que murio por capacidad, por
identidad o por tasa **no llego a disputar la franja**, y meterla en el
denominador de C1 seria declarar un numero que no se midio.

Fuente: banco-reglas-reserva.md §5.0 (cubos, D-P4-08 y los tres invariantes) y
arquitectura.md §10.1 y §10.3 (la frontera del 200).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class Cubo(str, Enum):
    """Las siete maneras en que puede terminar una solicitud.

    Solo tres significan que el sistema decidio algo sobre el dominio.
    """

    CONFIRMADA = "confirmada"
    RECHAZADA_REGLA = "rechazada-regla"
    SYS_CONTENCION = "SYS-CONTENCION"
    SYS_CAPACIDAD = "SYS-CAPACIDAD"
    SYS_IDENTIDAD = "SYS-IDENTIDAD"
    SYS_TASA = "SYS-TASA"
    OTRO = "otro"


CUBOS_COMPETIDORES = frozenset(
    {Cubo.CONFIRMADA, Cubo.RECHAZADA_REGLA, Cubo.SYS_CONTENCION}
)
"""**Competidora efectiva** es la solicitud de la que CONSTA que llego a
disputar la franja. Son exactamente estos tres cubos (D-P4-08 punto 1).

`SYS-CONTENCION` cuenta: disputo, simplemente nadie gano.
`SYS-CAPACIDAD` no cuenta: no hay constancia de que llegara a disputar.
`SYS-IDENTIDAD` y `SYS-TASA` no cuentan: no hubo evaluacion.
"""

CULPA_DEL_INSTRUMENTO = frozenset({Cubo.SYS_IDENTIDAD, Cubo.SYS_TASA})
"""Si aparece alguno, la culpa es de la medicion, nunca del sistema de reservas.
La corrida es invalida y no se publica (banco §5.0)."""


@dataclass(frozen=True)
class Desenlace:
    """Como termino una solicitud, con lo que hace falta para medir."""

    cubo: Cubo
    regla: str | None = None
    id_reserva: str | None = None
    franjas: tuple = ()
    unidad: str | None = None
    # Instantes en reloj monotono del proceso que lanzo. Alimentan S-2.
    t_inicio_evaluacion: float | None = None
    t_intento_escritura: float | None = None
    t_fin: float | None = None
    intentos_internos: int = 1
    detalle: str | None = None

    @property
    def es_competidora_efectiva(self) -> bool:
        return self.cubo in CUBOS_COMPETIDORES

    def etiqueta(self) -> str:
        """Como se nombra este desenlace en el desglose publicado."""
        if self.cubo is Cubo.RECHAZADA_REGLA:
            return self.regla or "rechazada-sin-regla"
        return self.cubo.value


@dataclass
class Desglose:
    """El reparto completo por cubo. Lo que un extrano lee sin abrir el codigo."""

    por_etiqueta: Counter = field(default_factory=Counter)
    por_cubo: Counter = field(default_factory=Counter)
    total: int = 0

    @staticmethod
    def de(desenlaces) -> "Desglose":
        d = Desglose()
        for x in desenlaces:
            d.por_etiqueta[x.etiqueta()] += 1
            d.por_cubo[x.cubo] += 1
            d.total += 1
        return d

    @property
    def competidoras_efectivas(self) -> int:
        return sum(self.por_cubo[c] for c in CUBOS_COMPETIDORES)

    @property
    def confirmadas(self) -> int:
        return self.por_cubo[Cubo.CONFIRMADA]

    def cuenta(self, etiqueta: str) -> int:
        return self.por_etiqueta.get(etiqueta, 0)

    def lineas(self) -> list[str]:
        orden = sorted(self.por_etiqueta.items(), key=lambda kv: (-kv[1], kv[0]))
        return [f"    {etiqueta:<18} {n}" for etiqueta, n in orden]


@dataclass
class Simultaneidad:
    """Las tres senales de arquitectura §9. **Decide S-3.**

    S-1  maximo de solicitudes en vuelo a la vez, en el cliente.
         Cota superior. Solapar en el cliente no prueba solapar en el punto de
         decision.
    S-2  solapamiento de las ventanas de escritura: desde que una solicitud
         empieza a evaluar hasta que intenta escribir. Es la que cuenta.
    S-3  al menos un rechazo RR-11. Inmune al reloj: solo puede existir si una
         condicion fallo sobre una franja que la lectura vio libre. Evidencia
         directa de carrera.
    """

    s1_max_en_vuelo: int = 0
    s2_max_ventanas_solapadas: int = 0
    s3_rr11: int = 0
    dispersion_barrera_ms: float = 0.0
    lanzadas: int = 0

    @property
    def hubo_carrera_observada(self) -> bool:
        return self.s3_rr11 >= 1

    def lineas(self) -> list[str]:
        return [
            f"    S-1 max en vuelo a la vez ....... {self.s1_max_en_vuelo} de {self.lanzadas}",
            f"    S-2 max ventanas solapadas ...... {self.s2_max_ventanas_solapadas}",
            f"    S-3 rechazos RR-11 .............. {self.s3_rr11}"
            + ("" if self.s3_rr11 else "   <-- SIN evidencia directa de carrera"),
            f"    dispersion de la barrera ........ {self.dispersion_barrera_ms:.2f} ms",
        ]


@dataclass
class Invariantes:
    """Las tres capas. Confundirlas es como se produce un falso verde.

    I-1 CORRECCION  para toda franja, confirmadas <= 1. Es C1.
                    Si se viola: BUILD EN ROJO.
    I-2 VIVACIDAD   nadie puede rechazarlo todo. Tres comprobaciones, ver
                    `evaluar_invariantes`. Si se viola: BUILD EN ROJO, con
                    clase distinta de I-1.
    I-3 VALIDEZ     SYS-IDENTIDAD = 0, SYS-TASA = 0 y competidoras efectivas
                    por encima del minimo del caso. Si se viola: MEDICION
                    INVALIDA — no se publica como evidencia de C1.
    """

    correccion_ok: bool
    vivacidad_ok: bool
    validez_ok: bool
    motivos_correccion: list = field(default_factory=list)
    motivos_vivacidad: list = field(default_factory=list)
    motivos_validez: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    @property
    def build_en_rojo(self) -> bool:
        """La validez NO rompe el build: invalida la medicion (banco §5.0)."""
        return not (self.correccion_ok and self.vivacidad_ok)


def evaluar_invariantes(
    desenlaces_por_franja: dict,
    minimo_competidoras: int,
    confirmadas_esperadas_total: int,
    maximo_confirmadas_por_franja: int = 1,
) -> Invariantes:
    """Aplica las tres capas sobre un reparto agrupado por franja.

    `desenlaces_por_franja` mapea una franja a la lista de desenlaces que la
    disputaron. Una solicitud de varias franjas aparece en todas las suyas.

    `maximo_confirmadas_por_franja` es 1 en el caso general y 0 en K-07 (franja
    bloqueada), donde una sola confirmada rompe el build.

    --------------------------------------------------------------------------
    DESVIACION DECLARADA respecto de banco §5.0, y por que
    --------------------------------------------------------------------------
    El banco enuncia la vivacidad asi: *para toda franja con competidoras
    efectivas >= 1, confirmadas = 1*.

    **Ese enunciado es falso en cuanto una solicitud ocupa mas de una franja, y
    K-02 lo demuestra.** En K-02, `10-14` y `12-16` comparten las franjas de las
    12 y las 13. Si gana `12-16`, la perdedora `10-14` habia disputado tambien
    las de las 10 y las 11 — franjas que nadie mas queria — y esas se quedan con
    cero confirmadas. **Eso no es un fallo de vivacidad: es el todo-o-nada
    funcionando**, que es exactamente lo que K-02 existe para comprobar. Con el
    enunciado literal, K-02 sale en rojo con el sistema correcto.

    Se sustituye por tres comprobaciones que son mas fuertes donde importa y
    correctas donde el enunciado literal no lo era:

      V-a  el numero total de confirmadas es el que el caso declara.
           **Es el guardia contra "rechazarlo todo"**: K-03 exige CINCO
           confirmadas, no cero dobles. Un sistema que rechazara siempre
           satisface la correccion y muere aqui.
      V-b  toda franja disputada por 2 o mas competidoras efectivas tiene
           exactamente una confirmada. Nadie pierde una franja que nadie mas
           queria.
      V-c  una franja con una sola competidora efectiva y cero confirmadas solo
           se admite si esa competidora disputaba MAS de una franja — es decir,
           si perdio por el todo-o-nada en otra. Si disputaba una sola, es una
           franja libre que nadie gano, y eso si es rojo.

    Se reporta a `analyst-agent`: el enunciado de banco §5.0 necesita esta
    correccion, o K-02 no puede pasar nunca.
    """
    todos = [d for lista in desenlaces_por_franja.values() for d in lista]
    vistos = {id(d): d for d in todos}
    global_ = Desglose.de(vistos.values())

    motivos_c: list[str] = []
    motivos_v: list[str] = []
    motivos_val: list[str] = []
    avisos: list[str] = []

    # V-a · el guardia contra el sistema que rechaza todo.
    if global_.confirmadas != confirmadas_esperadas_total:
        motivos_v.append(
            f"confirmadas totales = {global_.confirmadas}, y el caso declara "
            f"{confirmadas_esperadas_total}. Un sistema que rechaza de mas "
            "satisface la correccion y no sirve para nada"
        )

    for franja, lista in sorted(desenlaces_por_franja.items(), key=lambda kv: str(kv[0])):
        d = Desglose.de(lista)
        # I-1 · Correccion. Sin excepcion, sea cual sea el reparto de cubos.
        if d.confirmadas > maximo_confirmadas_por_franja:
            motivos_c.append(
                f"franja {franja}: {d.confirmadas} confirmadas "
                f"(maximo admitido {maximo_confirmadas_por_franja}) "
                "— ESTO ES UNA DOBLE RESERVA"
            )
        if maximo_confirmadas_por_franja < 1 or d.confirmadas >= 1:
            continue
        # V-b · disputada por varias y nadie gano.
        if d.competidoras_efectivas >= 2:
            motivos_v.append(
                f"franja {franja}: {d.competidoras_efectivas} competidoras "
                "efectivas y ninguna confirmada — nadie gano una franja que "
                "estaba libre"
            )
        # V-c · una sola competidora, que ademas no disputaba nada mas.
        elif d.competidoras_efectivas == 1:
            unica = next(x for x in lista if x.es_competidora_efectiva)
            if len(unica.franjas or ()) <= 1:
                motivos_v.append(
                    f"franja {franja}: una sola competidora efectiva, que solo "
                    "pedia esta franja, y no se confirmo. No hay todo-o-nada "
                    "que lo explique"
                )

    # I-3 · Validez de la medicion.
    for cubo in sorted(CULPA_DEL_INSTRUMENTO, key=lambda c: c.value):
        if global_.por_cubo[cubo] > 0:
            motivos_val.append(
                f"{cubo.value} = {global_.por_cubo[cubo]} — la culpa es del "
                "instrumento o del prestamo de identidades, nunca del sistema "
                "de reservas"
            )
    if global_.competidoras_efectivas < minimo_competidoras:
        motivos_val.append(
            f"competidoras efectivas = {global_.competidoras_efectivas}, "
            f"minimo del caso = {minimo_competidoras}. **No se redondea hacia "
            "arriba**: se publica el denominador real (D-P4-08 punto 5)"
        )
    if global_.por_cubo[Cubo.SYS_CAPACIDAD] > 0:
        avisos.append(
            f"SYS-CAPACIDAD = {global_.por_cubo[Cubo.SYS_CAPACIDAD]}: se publica "
            "con su numero y se descuenta de las competidoras efectivas"
        )
    if global_.cuenta("RR-11") == 0:
        avisos.append(
            "RR-11 = 0: la corrida no produjo evidencia directa de carrera. "
            "Es aviso de medicion (RF-14), no fallo del sistema"
        )

    return Invariantes(
        correccion_ok=not motivos_c,
        vivacidad_ok=not motivos_v,
        validez_ok=not motivos_val,
        motivos_correccion=motivos_c,
        motivos_vivacidad=motivos_v,
        motivos_validez=motivos_val,
        avisos=avisos,
    )


def informe(
    titulo: str,
    desglose: Desglose,
    simultaneidad: Simultaneidad,
    invariantes: Invariantes,
) -> str:
    """El texto que se imprime y se guarda como evidencia.

    Lleva los fallos dentro a proposito: una tabla que solo publica aciertos no
    es un resultado, es un folleto.
    """
    lineas = [f"== {titulo} " + "=" * max(0, 60 - len(titulo)), ""]
    lineas.append(f"  lanzadas .......................... {simultaneidad.lanzadas}")
    lineas.append(f"  competidoras efectivas ............ {desglose.competidoras_efectivas}")
    lineas.append(f"  confirmadas ....................... {desglose.confirmadas}")
    lineas.append("")
    lineas.append("  reparto por cubo de desenlace:")
    lineas.extend(desglose.lineas())
    lineas.append("")
    lineas.append("  simultaneidad observada:")
    lineas.extend(simultaneidad.lineas())
    lineas.append("")

    def bloque(nombre: str, ok: bool, motivos, consecuencia: str) -> None:
        lineas.append(f"  {nombre}: {'OK' if ok else 'VIOLADO -> ' + consecuencia}")
        for m in motivos:
            lineas.append(f"      - {m}")

    bloque("I-1 CORRECCION (C1)", invariantes.correccion_ok,
           invariantes.motivos_correccion, "BUILD EN ROJO")
    bloque("I-2 VIVACIDAD", invariantes.vivacidad_ok,
           invariantes.motivos_vivacidad, "BUILD EN ROJO")
    bloque("I-3 VALIDEZ DE LA MEDICION", invariantes.validez_ok,
           invariantes.motivos_validez, "MEDICION INVALIDA, no se publica")
    if invariantes.avisos:
        lineas.append("  avisos:")
        for a in invariantes.avisos:
            lineas.append(f"      - {a}")
    lineas.append("")
    return "\n".join(lineas)
