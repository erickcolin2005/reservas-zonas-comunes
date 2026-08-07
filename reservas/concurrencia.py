"""Producir concurrencia de verdad, y medir cuanta hubo.

Este modulo existe por el fallo fatal n.o 1 del proyecto: **la prueba de
concurrencia que no produce concurrencia**. Cincuenta peticiones en un bucle
secuencial dan verde con el patron ingenuo, porque llegan en fila y nunca
compiten. Una prueba asi no demuestra que el sistema este bien: demuestra que la
medicion fallo, y lo hace en verde, que es la peor forma de fallar.

Tres cosas lo evitan, y las tres estan aqui:

  1. BARRERA DE DISPARO. Todos los hilos preparados y bloqueados, y soltados a
     la vez. Nada de trabajo caro despues de la barrera: lo que ocurre despues
     es la solicitud y nada mas.

  2. RONDA DE CALENTAMIENTO ANTES DE LA BARRERA. Cada hilo abre su conexion y la
     usa una vez antes de bloquearse. Sin esto, el establecimiento de conexion
     produce una fila justo donde no puede haberla — FF1 exacto.

  3. SE MIDE Y SE DECLARA la simultaneidad que se observo. Si no hubo solape
     real, la medicion es invalida y se reporta como tal. "50 solicitudes
     enviadas" NO es "50 solicitudes simultaneas", y un instrumento que informa
     lo primero y lo presenta como lo segundo produce un verde falso que nadie
     va a notar mirando el resultado.

Sobre los hilos y el interprete: la carga de cada tarea es de red —una peticion
HTTP al motor—, y el interprete suelta su bloqueo global mientras espera al
socket. Por eso los hilos si producen simultaneidad real aqui. **Y si al medirla
resultara que no la hay, este modulo lo dice: es exactamente lo que existe para
detectar.**
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .desenlaces import Cubo, Desenlace, Simultaneidad


class _ContadorEnVuelo:
    """S-1: maximo de solicitudes en vuelo a la vez, visto desde el cliente.

    Es una cota superior y nada mas: solapar en el cliente no prueba solapar en
    el punto de decision. Por eso no decide nada — decide S-3.
    """

    def __init__(self) -> None:
        self._cerrojo = threading.Lock()
        self._actual = 0
        self.maximo = 0

    def entra(self) -> None:
        with self._cerrojo:
            self._actual += 1
            self.maximo = max(self.maximo, self._actual)

    def sale(self) -> None:
        with self._cerrojo:
            self._actual -= 1


@dataclass
class Corrida:
    """El resultado bruto de una tanda: desenlaces y como se lanzaron."""

    desenlaces: list = field(default_factory=list)
    salidas_barrera: list = field(default_factory=list)
    max_en_vuelo: int = 0
    errores: list = field(default_factory=list)


def lanzar_con_barrera(tareas, calentar=None, tiempo_maximo: float = 120.0) -> Corrida:
    """Ejecuta `tareas` a la vez y devuelve sus desenlaces.

    `tareas`   secuencia de invocables sin argumentos que devuelven `Desenlace`.
    `calentar` invocable opcional `calentar(indice)` que se ejecuta ANTES de la
               barrera. Ahi va todo lo caro: crear el cliente, abrir la conexion,
               precalcular la solicitud. Despues de la barrera solo queda la
               peticion.
    """
    n = len(tareas)
    corrida = Corrida(desenlaces=[None] * n, salidas_barrera=[0.0] * n)
    barrera = threading.Barrier(n)
    en_vuelo = _ContadorEnVuelo()

    def trabajo(indice: int) -> None:
        try:
            if calentar is not None:
                calentar(indice)
        except Exception as error:  # pragma: no cover - se reporta, no se traga
            corrida.errores.append(f"calentamiento[{indice}]: {error!r}")
            barrera.wait(timeout=tiempo_maximo)
            return
        try:
            barrera.wait(timeout=tiempo_maximo)
            corrida.salidas_barrera[indice] = time.perf_counter()
            en_vuelo.entra()
            try:
                corrida.desenlaces[indice] = tareas[indice]()
            finally:
                en_vuelo.sale()
        except Exception as error:
            corrida.errores.append(f"tarea[{indice}]: {error!r}")
            corrida.desenlaces[indice] = Desenlace(
                cubo=Cubo.OTRO, detalle=repr(error)
            )

    hilos = [
        threading.Thread(target=trabajo, args=(i,), name=f"solicitud-{i}")
        for i in range(n)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=tiempo_maximo)

    corrida.max_en_vuelo = en_vuelo.maximo
    corrida.desenlaces = [
        d if d is not None else Desenlace(cubo=Cubo.OTRO, detalle="sin desenlace")
        for d in corrida.desenlaces
    ]
    return corrida


def max_solapamiento(intervalos) -> int:
    """Cuantas ventanas se solapan como maximo, por barrido de eventos.

    Cada intervalo es `(inicio, fin)`. Un intervalo que empieza justo cuando
    otro acaba **no cuenta como solape**: se procesan primero los cierres.
    """
    eventos: list[tuple[float, int]] = []
    for inicio, fin in intervalos:
        if inicio is None or fin is None:
            continue
        if fin < inicio:
            inicio, fin = fin, inicio
        eventos.append((inicio, +1))
        eventos.append((fin, -1))
    if not eventos:
        return 0
    # Orden: a igualdad de instante, primero los cierres (delta -1 antes de +1).
    eventos.sort(key=lambda e: (e[0], e[1]))
    actual = maximo = 0
    for _, delta in eventos:
        actual += delta
        maximo = max(maximo, actual)
    return maximo


def medir_simultaneidad(corrida: Corrida) -> Simultaneidad:
    """Las tres senales de arquitectura §9, calculadas sobre una corrida.

    S-2 se calcula sobre la **ventana de escritura** de cada solicitud: desde
    que empieza a evaluar hasta que intenta escribir. Aqui todos los instantes
    salen del mismo reloj monotono del mismo proceso, asi que **no hay desfase
    de reloj entre entornos que corregir**. Contra el motor real eso deja de ser
    cierto y S-2 pasa a ser una estimacion declarada.
    """
    desenlaces = corrida.desenlaces
    ventanas = [
        (d.t_inicio_evaluacion, d.t_intento_escritura)
        for d in desenlaces
        if d.t_inicio_evaluacion is not None and d.t_intento_escritura is not None
    ]
    salidas = [s for s in corrida.salidas_barrera if s]
    dispersion = (max(salidas) - min(salidas)) * 1000.0 if len(salidas) > 1 else 0.0
    return Simultaneidad(
        s1_max_en_vuelo=corrida.max_en_vuelo,
        s2_max_ventanas_solapadas=max_solapamiento(ventanas),
        s3_rr11=sum(1 for d in desenlaces if d.regla == "RR-11"),
        dispersion_barrera_ms=dispersion,
        lanzadas=len(desenlaces),
    )


def agrupar_por_franja(desenlaces) -> dict:
    """Cada desenlace aparece en TODAS las franjas que su solicitud disputo.

    Es lo que permite evaluar la vivacidad por franja, que es como K-03 se
    comprueba: cinco franjas disjuntas, cada una con exactamente una confirmada.
    """
    salida: dict = {}
    for desenlace in desenlaces:
        for franja in desenlace.franjas or ():
            salida.setdefault(franja, []).append(desenlace)
    return salida
