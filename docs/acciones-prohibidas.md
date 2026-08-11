# Acciones prohibidas en la cuenta de AWS

Este fichero existe por la condición **CE-1** del caso de negocio, y tiene que
estar escrito **antes de que exista el primer recurso en AWS**. La razón es
incómoda: tres de las acciones de abajo se ejecutan con una sola casilla, y
ninguna produce un error visible. El sistema sigue devolviendo 200. Lo que
cambia es que **deja de demostrar lo que afirma**.

> **Es una lista, no un control.** Nada de esto está impedido por una política,
> ni lo detecta una prueba, ni pone el build en rojo. Se cumple leyéndolo. Si
> alguna fila llegara a estar realmente impedida, dejaría de pertenecer a esta
> lista y pasaría a ser un control con su prueba — **mezclar las dos cosas
> produciría exactamente la falsa confianza que este proyecto intenta no tener**:
> creer que algo está bloqueado cuando solo está escrito.

El orden **no** es por gravedad. Es por **qué tan fácil es ejecutarlas sin
querer**.

---

## Grupo A — las que alguien haría creyendo que mejora el sistema

Estas tres no requieren descuido. Requieren buena intención y no haber leído
esto.

### A1 · No actives una tabla global ni una réplica en otra región

Hace dos daños distintos, y conviene no confundirlos:

- **Corrección.** Con réplicas multirregión la resolución de conflictos es por
  último-en-escribir. **Una de las dos reservas desaparece sin ruido.** Es
  romper la garantía central del proyecto en silencio, que es la peor forma de
  romperla.
- **Capacidad.** Las asignaciones del free tier se calculan **agregadas entre
  todas las regiones, no por región**. La réplica no recibiría su propia cuota
  de 25 WCU: replicar **no duplica** el presupuesto de escritura, **lo divide**.

### A2 · No pases la tabla a modo bajo demanda (*on-demand*)

El free tier perpetuo de DynamoDB exige **modo aprovisionado**. Cambiarlo saca
la tabla del único componente del sistema que es gratis para siempre. **Es una
casilla, no una migración**, y parece una mejora de elasticidad.

### A3 · No bajes la ráfaga del borde por debajo de `N`

El borde rechazaría por tasa **antes de que las solicitudes lleguen a competir**.
El instrumento dejaría de producir concurrencia — y un caso K en verde por
estrangulamiento se lee **exactamente igual** que uno en verde por corrección.
Parece un endurecimiento de seguridad razonable. Es la desactivación de la
medición central del proyecto.

---

## Grupo B — las que convierten la cuenta en facturable

Todas tienen el mismo efecto: **conversión automática de Plan Gratuito a Plan de
Pago**. Eso reintroduce la clase de riesgo que no se acota con código, que es
justamente la que se eligió eliminar al abrir la cuenta.

Lista completa según la documentación oficial vigente:

1. Activar **AWS Organizations**
2. Desplegar una **landing zone de AWS Control Tower**
3. Inscribirse en **AWS Partner Network**
4. Contratar **Professional Services**
5. Marcar la cuenta como **HIPAA o SEC**
6. Firmar un **Enterprise Agreement** con AWS
7. Comprar una suscripción a **AWS Skill Builder Team**

> **Las dos últimas se añadieron el 2026-08-11**, al reverificar la
> documentación: la lista que este proyecto venía arrastrando tenía cinco
> entradas y la oficial tiene siete. **La séptima es la más fácil de ejecutar de
> todas** — es una compra de formación, no una acción de infraestructura, y nadie
> la asociaría con la facturación de la cuenta.

---

## Grupo C — la que destruye una propiedad de privacidad

### C1 · No publiques el registro crudo como evidencia

El calendario oculta el mapa de ocupación del conjunto a propósito, y el
seudónimo de las unidades es estable solo dentro de una corrida por la misma
razón. Publicar el registro sin tratar devuelve el mapa completo.

---

## Una puerta cerrada, que no es una prohibición

Los planes gratuitos **no son elegibles para otros créditos promocionales ni
descuentos**.

Se anota aquí porque este es el sitio donde alguien lo buscaría. Si en algún
momento se pensara en alargar la ventana de seis meses aplicando un crédito de
un evento, de un programa de estudiantes o de una certificación: **no funciona**.
La ventana no se extiende comprándola ni pidiéndola. Lo único que se controla es
**cuándo se abre**.
