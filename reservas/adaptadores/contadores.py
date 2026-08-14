"""Los dos contadores de tasa, contra el motor. La mitad que faltaba de SEC-1.

`reservas/seguridad/contador.py` y `prestamo.py` cuentan **en memoria del
proceso**, que es correcto para las pruebas y falso para una Lambda: cada
contenedor tendria el suyo y el techo dejaria de ser `50 x tope` para pasar a
`50 x tope x contenedores`. Aqui viven las versiones que cuentan de verdad.

------------------------------------------------------------------------------
UNA SOLA ESCRITURA CONDICIONAL, Y POR QUE NO SE LEE ANTES
------------------------------------------------------------------------------
La forma ingenua es *leer el contador, comprobar el tope, escribir*. Eso tiene
una carrera dentro: entre la lectura y la escritura caben otras solicitudes, y
justo este contador existe para el momento en que **cincuenta llegan a la vez**.
Un limite de tasa que se cae precisamente bajo carga no es un limite de tasa.

Se hace en un solo acto:

    UpdateItem  Condicion: attribute_not_exists(contador) OR contador < :tope
                Accion:    ADD contador 1 ; SET ttl

Es el mismo patron que el contador de cupo de la transaccion (modelo-datos
§5.1), y por el mismo motivo: **quien decide es la condicion, nunca la lectura**.
Si la condicion falla, la cuota estaba agotada — y no hizo falta leerla.

------------------------------------------------------------------------------
LO QUE ESTO CUESTA, DICHO CON EL NUMERO DE V-8
------------------------------------------------------------------------------
Es **1 WCU por intento**, escritura suelta y no transaccional: no paga el
multiplicador x2 de D-P4-20. Una ejecucion del instrumento son 50 intentos = 50
WCU, que se suman a los ~400 de las reservas. Entra en el mismo presupuesto de
D-CE4-1 y no cambia su conclusion.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..nucleo import claves
from ..seguridad.contador import (
    RUTAS_CONTADAS,
    EnfriamientoActivo,
    TasaExcedida,
    cubeta,
    fin_de_cubeta,
)
from ..seguridad.prestamo import IdentidadNoPrestable
from . import dynamodb as motor


class _CuotaEnLaTabla:
    """Cuota por ventana fija, contada con una escritura condicional.

    No es publica: las dos cuotas del sistema la usan, pero cada una traduce el
    agotamiento a **su** excepcion. Que `TasaExcedida` e `IdentidadNoPrestable`
    sigan siendo distintas importa — una es una medicion invalida del
    instrumento y la otra es el dispensador diciendo que no; confundirlas haria
    que el instrumento no supiera cual de las dos cosas le paso.
    """

    def __init__(self, cliente, tabla: str, ventana: timedelta, tope: int):
        if tope < 1:
            raise ValueError("un tope menor que 1 impide hasta el calentamiento")
        self.cliente = cliente
        self.tabla = tabla
        self.ventana = ventana
        self.tope = tope

    def consumir(self, pk: str, sk_de_cubeta, ahora: datetime) -> bool:
        """Suma uno si cabe. Devuelve `False` si la cuota estaba agotada."""
        numero = cubeta(ahora, self.ventana)
        try:
            self.cliente.update_item(
                TableName=self.tabla,
                Key={"PK": motor.S(pk), "SK": motor.S(sk_de_cubeta(numero))},
                ConditionExpression="attribute_not_exists(contador) OR contador < :tope",
                UpdateExpression="ADD contador :uno SET #ttl = :ttl",
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":tope": motor.N(self.tope),
                    ":uno": motor.N(1),
                    ":ttl": motor.N(fin_de_cubeta(numero, self.ventana)),
                },
            )
        except self.cliente.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def consumido(self, pk: str, sk_de_cubeta, ahora: datetime) -> int:
        """Cuanto lleva gastado. **Solo para diagnostico y pruebas.**

        Nadie decide con esto: decide la condicion de `consumir`. Si algun dia
        alguien encadena `consumido()` y luego `consumir()`, habra reintroducido
        la carrera que este modulo existe para no tener.
        """
        numero = cubeta(ahora, self.ventana)
        r = self.cliente.get_item(
            TableName=self.tabla,
            Key={"PK": motor.S(pk), "SK": motor.S(sk_de_cubeta(numero))},
            ConsistentRead=True,
        )
        item = r.get("Item")
        return int(item["contador"]["N"]) if item else 0


class ContadorIntentosDynamoDB:
    """SEC-1 contra el motor. Misma superficie que `ContadorIntentos`.

    **Misma superficie a proposito**: `test_contador.py` corre sus casos contra
    las dos implementaciones, y eso es lo unico que garantiza que el limite que
    se prueba en local sea el limite que actua desplegado. Es la leccion de V-2b
    -*la clase del fallo tiene que coincidir entre motores*- aplicada a un
    control en vez de a una regla.
    """

    def __init__(
        self,
        cliente,
        ventana: timedelta,
        tope: int,
        tabla: str = None,
    ):
        self.ventana = ventana
        self.tope = tope
        self._cuota = _CuotaEnLaTabla(
            cliente, tabla or motor.config.TABLA, ventana, tope
        )

    def registrar(self, unidad: str, ruta: str, ahora: datetime) -> None:
        if ruta not in RUTAS_CONTADAS:
            return  # las lecturas no consumen cuota
        if not self._cuota.consumir(
            claves.pk_identidad(unidad), claves.sk_intentos, ahora
        ):
            raise TasaExcedida(
                f"{unidad} agoto {self.tope} intentos en {self.ventana}"
            )

    def consumido(self, unidad: str, ahora: datetime) -> int:
        return self._cuota.consumido(
            claves.pk_identidad(unidad), claves.sk_intentos, ahora
        )


class CuotaOrigenDynamoDB:
    """D-SEC-6 contra el motor: los lotes que un origen puede pedir por ventana.

    Se inyecta en `Dispensador`, que sin ella cuenta en memoria. **Con una sola
    Lambda desplegada la diferencia no se nota; con dos, el tope se dobla** — y
    nadie decide cuantas hay.
    """

    def __init__(
        self,
        cliente,
        ventana: timedelta,
        tope: int,
        tabla: str = None,
    ):
        self.ventana = ventana
        self.tope = tope
        self._cuota = _CuotaEnLaTabla(
            cliente, tabla or motor.config.TABLA, ventana, tope
        )

    def consumir(self, origen: str, ahora: datetime) -> None:
        if not self._cuota.consumir(
            claves.pk_origen(origen), claves.sk_prestamos, ahora
        ):
            raise IdentidadNoPrestable(
                f"el origen agoto su cuota de {self.tope} lotes (D-SEC-6)"
            )

    def consumido(self, origen: str, ahora: datetime) -> int:
        return self._cuota.consumido(
            claves.pk_origen(origen), claves.sk_prestamos, ahora
        )


class EnfriamientoInstrumento:
    """D-CE4-1 · el enfriamiento entre ejecuciones del instrumento.

    **Es global, no por origen, y esa es toda la decision.** Lo que protege es el
    **deposito de rafaga** de la tabla: una ejecucion son ~400 WCU de golpe sobre
    25 sostenidos, y funciona porque el deposito los absorbe. El deposito es un
    recurso compartido — **dos desconocidos ejecutando a la vez lo agotan igual
    que uno ejecutando dos veces**. Un enfriamiento por origen seria el limite
    de D-SEC-6 otra vez con otro nombre, y no protegeria lo que hay que
    proteger.

    **Y no evita una factura, evita algo peor de explicar:** en modo
    aprovisionado pasarse **estrangula, no cobra**. Lo que se pierde al agotar la
    rafaga es la validez de la medicion. Un visitante que provoque
    estrangulamiento no ve el sistema fallar: ve **la demo dejar de demostrar**.

    Se implementa como una cuota de **uno por ventana**, que es la misma pieza
    que los otros dos contadores. Hereda su efecto de frontera —en el cambio de
    cubeta caben dos ejecuciones seguidas— y se acepta por el mismo motivo: el
    deposito aguanta unas doce seguidas `[A, extrapolado]`, asi que dos no lo
    vacian.

    **Vive en el borde y no en el instrumento**, porque un tope que se aplica en
    el cliente lo quita quien quiera — y el instrumento esta hecho para que un
    desconocido lo ejecute.
    """

    def __init__(self, cliente, ventana: timedelta, tabla: str = None):
        self.ventana = ventana
        self._cuota = _CuotaEnLaTabla(cliente, tabla or motor.config.TABLA, ventana, 1)

    def consumir(self, ahora: datetime) -> None:
        if not self._cuota.consumir(
            claves.pk_instrumento(), claves.sk_enfriamiento, ahora
        ):
            raise EnfriamientoActivo(
                f"el instrumento se enfria {self.ventana} entre ejecuciones "
                "(D-CE4-1)"
            )
