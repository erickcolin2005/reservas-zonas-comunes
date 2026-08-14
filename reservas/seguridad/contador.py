"""El contador de intentos por identidad (SEC-1), y la desigualdad que lo ata.

Es el control que sostiene el **techo calculable** del sistema: con un conjunto
cerrado de 50 identidades y un tope por identidad, el trafico maximo es
`50 x tope` en vez de infinito. Quitarlo devuelve el sistema al defecto que
SEC-1 encontro `[V — arquitectura §14]`.

------------------------------------------------------------------------------
TRES COSAS QUE PARECEN DETALLES Y NO LO SON
------------------------------------------------------------------------------

**1. Cuenta INTENTOS, no confirmaciones.** Un contador de confirmaciones no
limita nada: quien quiera agotar el sistema puede hacerlo con solicitudes que se
rechazan. Consecuencia asumida y ya declarada por `architect-agent`: *un rechazo
no cuesta escritura* era falso del sistema — **contar intentos escribe**, y K-07
consume 50 WCU, no cero.

**2. Es lo PRIMERO, y va fuera de la transaccion** (ADR-29). Si viviera dentro,
un intento que la transaccion cancela no quedaria contado, y entonces el
contador contaria exactamente lo que no tiene que contar.

**3. La ventana expira sola.** El `ttl` del contador ES el fin de la ventana: no
hay proceso que limpie nada. Un control que necesita mantenimiento en un sistema
sin proceso de fondo es un control que un dia deja de estar.

------------------------------------------------------------------------------
LA VENTANA ES FIJA, NO DESLIZANTE — decision de Erick, y lo que cuesta
------------------------------------------------------------------------------
La ventana se parte en **cubetas** alineadas a la epoca: los intentos se cuentan
contra `INTENTOS#<cubeta>`, y la cubeta cambia sola con el reloj.

**Lo que se gana:** el contador desplegado es **una sola escritura de tamano
fijo** —`ADD contador 1` con condicion— y la cubeta vieja desaparece por `ttl`
sin que nadie limpie nada. Una ventana deslizante obligaria a guardar las marcas
de tiempo de cada intento, y el contador es **lo primero que escribe cada
solicitud**: encarecerlo encarece el camino que el instrumento satura a
proposito.

**Lo que cuesta, y se declara porque es real:** en el cambio de cubeta se pueden
colar hasta **2 x tope** intentos en un intervalo de una ventana —el final de
una cubeta y el principio de la siguiente—. Se acepta porque el control existe
para acotar el techo (`50 x tope` en vez de infinito), no para regular un caudal
exacto: un factor 2 sobre un techo calculable sigue siendo un techo calculable.
**Lo que no se acepta es que local y desplegado cuenten distinto**, y por eso
`cubeta()` es una sola funcion y las dos implementaciones corren las mismas
pruebas (`test_contador.py`).

------------------------------------------------------------------------------
POR QUE NO HAY VALORES POR DEFECTO
------------------------------------------------------------------------------
`security-agent` se nego a inventar la ventana y el tope, con la misma
disciplina con que `architect-agent` se nego a inventar la tasa sostenida:
*fijarlos antes de la primera ejecucion de I-3 es inventarlos*.

I-3 ya corrio. Por eso `sugerencia_de_tope()` existe y **deriva** el numero de lo
observado, en vez de proponerlo. Pero el contador **no tiene valores por
defecto**: hay que darselos, y quien los da los declara en el README.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Las rutas que el limite por identidad alcanza: **solo las que escriben**
# `[V — threat-model §3.1.2]`. Las lecturas se limitan solo en el borde, que es
# lo que deja el calendario publico fluido, y H5 lo necesita asi.
RUTAS_CONTADAS = frozenset(
    {"POST /reservas", "POST /reservas/{id}/cancelacion",
     "POST /admin/bloqueos", "POST /admin/reservas/{id}/cancelacion"}
)


class TasaExcedida(Exception):
    """La identidad agoto su cuota en la ventana. Se traduce a `SYS-TASA`.

    **Y `SYS-TASA` no es un rechazo del sistema de reservas**: es una medicion
    invalida. El banco lo clasifica como culpa del instrumento, no del sistema,
    y una corrida que lo produzca no se publica como evidencia de C1.
    """


def cubeta(ahora: datetime, ventana: timedelta) -> int:
    """La cubeta de ventana fija a la que pertenece un instante.

    **Alineada a la epoca y no al primer intento.** Si se anclara al primer
    intento, cada identidad tendria su propia rejilla y el contador desplegado
    necesitaria recordar cuando empezo cada una — que es justo el estado que la
    ventana fija existe para no guardar.

    Es una sola funcion a proposito: **es la definicion de "ventana" de todo el
    sistema**, y las dos implementaciones del contador la llaman. Dos copias de
    esto serian dos semanticas, y la de local no seria la de produccion.
    """
    segundos = int(ventana.total_seconds())
    if segundos <= 0:
        raise ValueError("una ventana no positiva no expira nunca")
    return int(ahora.timestamp()) // segundos


def fin_de_cubeta(numero: int, ventana: timedelta) -> int:
    """Segundos desde la epoca en que la cubeta deja de existir. Es el `ttl`."""
    return (numero + 1) * int(ventana.total_seconds())


@dataclass
class ContadorIntentos:
    """Cuenta intentos por identidad dentro de una ventana que expira sola.

    `ventana` y `tope` **no tienen valor por defecto a proposito**. Ver el
    encabezado del modulo: ponerlos aqui seria inventar los numeros que el
    modelo de amenazas se nego a inventar.
    """

    ventana: timedelta
    tope: int
    _intentos: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.tope < 1:
            raise ValueError("un tope menor que 1 impide hasta el calentamiento")
        if self.ventana <= timedelta(0):
            raise ValueError("una ventana no positiva no expira nunca")

    def registrar(self, unidad: str, ruta: str, ahora: datetime) -> None:
        """Anota un intento. Levanta `TasaExcedida` si la identidad agoto su cuota.

        Se llama ANTES de evaluar nada y fuera de la transaccion (ADR-29).
        """
        if ruta not in RUTAS_CONTADAS:
            return  # las lecturas no consumen cuota

        # La cubeta ES la ventana. Las cubetas viejas no se limpian: se dejan de
        # mirar, que es exactamente lo que hara el `ttl` del item en el motor
        # real. La semantica es la misma en local y desplegado por construccion,
        # porque los dos llaman a `cubeta()`.
        clave = (unidad, cubeta(ahora, self.ventana))
        if self._intentos.get(clave, 0) >= self.tope:
            raise TasaExcedida(
                f"{unidad} agoto {self.tope} intentos en {self.ventana}"
            )
        self._intentos[clave] = self._intentos.get(clave, 0) + 1

    def consumido(self, unidad: str, ahora: datetime) -> int:
        return self._intentos.get((unidad, cubeta(ahora, self.ventana)), 0)


class DesigualdadIncoherente(Exception):
    """Los dos controles se configuraron de forma que el mas flojo manda."""


def comprobar_desigualdad(
    n_identidades: int, tope_por_identidad: int, capacidad_del_borde: int
) -> None:
    """`n x tope <= lo que el borde deja pasar en la misma ventana`.

    **Es lo que impide que alguien "endurezca" un control y anule el otro**
    `[V — threat-model §3.1.2]`. Sin ella, subir el tope por identidad por encima
    de lo que el borde admite hace que el borde rechace primero: el instrumento
    empieza a recibir `SYS-TASA` del borde y **la medicion se invalida sin que
    nadie haya tocado el contador**.

    Se comprueba al arrancar y no en una revision manual, porque una desigualdad
    que hay que acordarse de verificar es una desigualdad que un dia no se
    verifica.
    """
    techo = n_identidades * tope_por_identidad
    if techo > capacidad_del_borde:
        raise DesigualdadIncoherente(
            f"{n_identidades} identidades x {tope_por_identidad} intentos = "
            f"{techo}, y el borde solo deja pasar {capacidad_del_borde} en la "
            "misma ventana. El borde rechazaria antes que el contador y la "
            "medicion se invalidaria sin que el contador hubiera actuado"
        )


def sugerencia_de_tope(repeticiones_observadas: int, margen: int = 2) -> int:
    """Deriva un tope de lo observado en I-3. **No lo inventa.**

    El modelo de amenazas fija la regla y el momento: el tope es *>= una
    ejecucion de calentamiento + las ejecuciones que el instrumento necesite
    para producir simultaneidad valida*, y **el numero se fija tras la primera
    ejecucion de I-3, contando cuantas repeticiones hicieron falta**.

    Dato observado el 2026-08-11: el CI necesito **3 corridas** de K-03 para la
    medicion de S-2 -y aun asi no la alcanzo, por lo que S-2 dejo de ser puerta-.
    Tres es, por tanto, el numero de repeticiones que un entorno lento llego a
    exigir.

    El calentamiento **no** suma: usa `describe_table`, que no es una ruta
    contada.

    `margen` es `[A]`: dos repeticiones extra para que un entorno peor que el
    runner no deje al revisor sin poder ejecutar el instrumento, que es la
    denegacion entre revisores de T-12.
    """
    if repeticiones_observadas < 1:
        raise ValueError("sin observaciones no se deriva nada: se mide primero")
    return repeticiones_observadas + margen
