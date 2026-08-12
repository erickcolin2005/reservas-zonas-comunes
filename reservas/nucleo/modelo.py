"""Los tipos del dominio. Puros: sin red, sin reloj, sin motor.

Todo lo de este modulo es inmutable a proposito. Una `Solicitud` que se pudiera
modificar despues de fijar su instante de referencia seria una via para que dos
comprobaciones de la misma solicitud leyeran dos relojes distintos (RF-07).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from . import tiempo


class TipoPeriodo(str, Enum):
    """Periodo sobre el que se cuenta el cupo de un espacio."""

    MENSUAL = "MENSUAL"
    SEMANAL = "SEMANAL"


class TipoOcupacion(str, Enum):
    """Que ocupa una franja. Reserva y bloqueo comparten primitivo (ADR-17)."""

    RESERVA = "RESERVA"
    BLOQUEO = "BLOQUEO"


@dataclass(frozen=True, order=True)
class Franja:
    """Un hueco: espacio implicito, un dia y una hora en punto.

    Es la unidad indivisible de reserva. Dos reservas se solapan si y solo si
    comparten al menos una franja — con eso, el solapamiento total, el parcial
    por la cabeza, el parcial por la cola, la contencion y la continencia son el
    mismo caso, y la adyacencia deja de ser un caso limite delicado.
    """

    dia: date
    hora: int

    def __post_init__(self) -> None:
        if not 0 <= self.hora <= 23:
            raise ValueError(f"hora fuera de rango: {self.hora}")

    @property
    def inicio(self) -> datetime:
        return tiempo.instante_local(self.dia.year, self.dia.month, self.dia.day, self.hora)

    @property
    def fin(self) -> datetime:
        """Fin de la franja. Intervalo semiabierto: [inicio, fin)."""
        from datetime import timedelta

        return self.inicio + timedelta(minutes=tiempo.MINUTOS_POR_FRANJA)

    def __str__(self) -> str:  # pragma: no cover - solo diagnostico
        return f"{self.dia.isoformat()} {self.hora:02d}:00"


@dataclass(frozen=True)
class ParametrosEspacio:
    """Los parametros de un espacio.

    Llegan como DATO, leidos del item `ESP#.../META`, nunca como constante del
    codigo. Es lo que impide que un sistema con los valores escritos fijos pase
    el banco entero sin haber implementado una sola regla configurable
    (hallazgo 3, RF-25).
    """

    id: str
    nombre: str
    apertura: int  # hora en punto en que abre la ventana
    cierre: int  # hora en punto en que cierra; la ultima franja empieza antes
    duracion_minima: int  # en franjas
    duracion_maxima: int  # en franjas
    antelacion_minima_horas: int
    horizonte_maximo_dias: int
    cupo: int
    tipo_periodo: TipoPeriodo
    plazo_cancelacion_horas: int
    habilitado: bool = True

    def periodo_de(self, dia: date) -> str:
        """El periodo de cupo al que se imputa una reserva que empieza ese dia.

        Inequivoco porque RR-03 impide cruzar la medianoche: una reserva tiene
        una sola fecha de inicio y por tanto un solo periodo.
        """
        if self.tipo_periodo is TipoPeriodo.SEMANAL:
            return tiempo.periodo_semanal(dia)
        return tiempo.periodo_mensual(dia)


@dataclass(frozen=True)
class Unidad:
    """Una unidad residencial. El sujeto de las reglas, nunca la persona."""

    id: str
    activa: bool
    grupo: str  # RAFAGA | SESION — ADR-30. En I-1 solo se siembra.
    bloqueo_fundamento: str | None = None  # MC-7: un bloqueo sin fundamento es invalido


@dataclass(frozen=True)
class Solicitud:
    """Una peticion de reserva ya canonizada.

    `inicio` viene de `tiempo.canonizar_inicio`. Si no cayo en la rejilla, esta
    solicitud no llega a existir: no hay clave aproximada.
    """

    unidad: str
    espacio: str
    inicio: datetime
    n_franjas: int

    def __post_init__(self) -> None:
        if self.n_franjas < 1:
            raise ValueError("una solicitud de cero franjas no es una solicitud")
        if self.inicio.tzinfo is None:
            raise ValueError("el inicio de una solicitud tiene que estar canonizado")

    @property
    def franjas(self) -> tuple[Franja, ...]:
        """Las franjas contiguas que ocupa. Todas del mismo dia (RR-03)."""
        primera = self.inicio.hour
        return tuple(
            Franja(self.inicio.date(), primera + i) for i in range(self.n_franjas)
        )

    @property
    def dia(self) -> date:
        return self.inicio.date()


@dataclass(frozen=True)
class OcupacionLeida:
    """Lo que la lectura previa vio en una franja."""

    tipo: TipoOcupacion
    id_reserva: str | None
    unidad: str | None


@dataclass(frozen=True)
class EstadoLeido:
    """El estado que alimenta la evaluacion. **No decide nada.**

    Decide la condicion de escritura. Esta lectura existe para poder decir
    *cual* regla rechazo, que es C3 — y para producir RR-10, que es una ruta de
    codigo distinta de RR-11.
    """

    parametros: ParametrosEspacio | None
    unidad: Unidad | None
    ocupacion: dict[Franja, OcupacionLeida] = field(default_factory=dict)
    agenda: dict[Franja, str] = field(default_factory=dict)  # franja -> id_reserva
    cupo_consumido: int = 0


@dataclass(frozen=True)
class IntencionEscritura:
    """Lo que el nucleo devuelve cuando ninguna regla se violo.

    **El nucleo no puede confirmar nada.** Devuelve una intencion; el adaptador
    la convierte en transaccion; la confirmacion la produce el motor al aceptar
    la condicion. Esa separacion es lo que hace verdad a C1: si se apaga el
    nucleo entero, la doble reserva sigue siendo imposible.
    """

    solicitud: Solicitud
    franjas: tuple[Franja, ...]
    periodo_cupo: str
    tope_cupo: int


@dataclass(frozen=True)
class Veredicto:
    """Resultado de la evaluacion pura."""

    aceptada: bool
    regla: str | None = None
    intencion: IntencionEscritura | None = None
    franja_culpable: Franja | None = None

    @staticmethod
    def rechaza(regla: str, franja: Franja | None = None) -> "Veredicto":
        return Veredicto(aceptada=False, regla=regla, franja_culpable=franja)

    @staticmethod
    def acepta(intencion: IntencionEscritura) -> "Veredicto":
        return Veredicto(aceptada=True, intencion=intencion)


# ---------------------------------------------------------------------------
# I-4 · Flujo de CANCELACION y flujo de ADMINISTRACION
# ---------------------------------------------------------------------------
# Hasta I-4 el nucleo solo sabia crear. Estas piezas son las que RR-12..RR-15
# necesitan, y ni una mas: se anaden por el caso de uso que las exige, no por
# completar un modelo de dominio que nadie ha pedido.


class EstadoReserva(str, Enum):
    """Una reserva solo tiene dos estados, y la ausencia de un tercero importa.

    No hay "expirada": una reserva pasada sigue siendo CONFIRMADA y lo que la
    hace incancelable es RR-13, que mira el instante. Inventar un estado que
    cambie solo por el paso del tiempo obligaria a alguien a escribirlo, y ese
    alguien no existe en un sistema sin proceso de fondo.
    """

    CONFIRMADA = "confirmada"
    CANCELADA = "cancelada"


@dataclass(frozen=True)
class ReservaLeida:
    """Lo que se sabe de una reserva al ir a cancelarla.

    `titular` es la unidad duena. **Es lo unico que decide RR-12**, y por eso
    esta aqui y no se deduce de ningun otro sitio.
    """

    id: str
    titular: str
    espacio: str
    inicio: datetime
    n_franjas: int
    estado: EstadoReserva = EstadoReserva.CONFIRMADA


@dataclass(frozen=True)
class PeticionCancelacion:
    """Quien cancela y que cancela.

    `es_administracion` no se deduce del identificador: llega como dato, igual
    que los parametros del espacio. Deducirla de una cadena que empiece por
    "ADM-" seria fijar en el codigo una convencion de datos.
    """

    id_reserva: str
    quien: str
    es_administracion: bool = False
    motivo: str | None = None


@dataclass(frozen=True)
class PeticionBloqueo:
    """Un bloqueo de mantenimiento sobre franjas contiguas de un espacio."""

    espacio: str
    inicio: datetime
    n_franjas: int
    motivo: str | None = None

    @property
    def franjas(self) -> tuple["Franja", ...]:
        primera = self.inicio.hour
        return tuple(
            Franja(self.inicio.date(), primera + i) for i in range(self.n_franjas)
        )
