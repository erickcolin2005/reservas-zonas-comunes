# Reservas de zonas comunes, donde dos personas no pueden ocupar el mismo hueco

[![CI](https://github.com/erickcolin2005/reservas-zonas-comunes/actions/workflows/ci.yml/badge.svg)](https://github.com/erickcolin2005/reservas-zonas-comunes/actions/workflows/ci.yml)

La insignia enlaza a la ejecución real. Dos trabajos: la suite completa contra un
motor local, y **uno que rompe la defensa a propósito y exige que el build
caiga**. Si está en verde, lo que este documento afirma se midió en una máquina
que no es la mía — que es donde el proyecto anterior encontró dos fallos que en
local no se veían.

Un sistema de reserva de zonas comunes de un conjunto residencial —salón social,
BBQ, cancha— construido alrededor de una sola pregunta incómoda: **¿qué hace el
sistema cuando dos peticiones llegan a la vez por el mismo espacio, el mismo día
y a la misma hora?**

La respuesta correcta es "acepta exactamente una". Este repositorio existe para
que eso no sea una afirmación, sino algo que puedas intentar romper tú.

> ## Estado: la carrera está cerrada y ya la puedes provocar tú. Falta desplegar.
>
> **Este README se escribió antes de la primera línea de código, a propósito**, y
> se actualiza cuando cambia lo que hay. No antes.
>
> **Lo que existe hoy y está medido:**
>
> - El mecanismo que impide la doble reserva: el hueco **es** la clave, y la
>   unicidad la impone la clave primaria, no una comprobación previa. **Verificado
>   contra DynamoDB de verdad**, no solo contra el sustituto local.
> - Una prueba que **produce concurrencia de verdad** —50 hilos con barrera de
>   disparo— y que **mide y publica la simultaneidad que consiguió**, en vez de
>   suponerla. Si no hubo solape real, la medición se declara inválida.
> - **El comando con el que puedes provocar la carrera tú mismo** (§2), y el
>   sistema entero corriendo en tu máquina sin cuenta de nube:
>   `python -m herramientas.servidor --desarrollo --sembrar`.
> - Las **quince reglas de negocio**, con su banco de casos, y una interfaz donde
>   cada rechazo dice **qué regla** lo produjo.
> - **392 pruebas en verde**, y tres suites de mutación que las ponen en rojo a
>   propósito: las quince reglas, los dos controles de seguridad, y la condición
>   de escritura (§3.1). Un verde solo demuestra algo si sabe ponerse rojo.
>
> **Lo que NO existe todavía:** el despliegue, el enlace de la demo, la evidencia
> visual grabada, y **las cifras de rendimiento** — que siguen sin medirse y por
> eso siguen sin afirmarse.
>
> **Las tablas de §3 siguen vacías en las columnas que no se han medido**, y así
> se quedan hasta que existan sus números — con los fallos dentro.

---

## 1 · El problema

Dos residentes abren la aplicación al mismo tiempo y piden el salón social el
sábado de 10:00 a 14:00. Los dos ven el horario libre, porque para los dos lo
estaba cuando miraron. Los dos pulsan "reservar".

En una base de datos relacional esto es rutina y se resuelve en una línea: una
restricción de unicidad, o una transacción con bloqueo. El motor te lo regala.

**El motor de datos que hay debajo de este sistema no regala ninguna de las
dos.** No tiene una restricción de unicidad que puedas declarar entre registros,
y no tiene un bloqueo que puedas tomar mientras decides. Eso deja el patrón que
casi cualquiera escribiría primero:

> leo si el horario está libre → si lo está, lo escribo

Ese patrón es una carrera. No a veces: siempre. Entre la lectura y la escritura
hay una ventana, y la otra petición cabe justo ahí. Con dos procesos corriendo en
paralelo —que es precisamente lo que este tipo de infraestructura garantiza que
va a pasar— las dos reservas se confirman y el sábado hay dos fiestas en el mismo
salón.

Y hay un agravante que hace que el problema no se detecte solo: **la ausencia de
un defecto no se ve.** Un sistema con esta carrera abierta funciona perfectamente
en cualquier demostración, porque una persona con un navegador no puede producir
la carrera por rápido que haga clic — sus peticiones llegan en fila. El fallo
aparece el día que hay dos personas de verdad.

Por eso el proyecto no se organiza alrededor de las pantallas. Se organiza
alrededor de cerrar esa carrera y de **entregar el medio para que un desconocido
intente abrirla**.

### La segunda mitad: las reglas

Un CRUD de reservas no tiene lógica de negocio. Un sistema de reservas sí, y se
contradice consigo misma: antelación mínima y máxima, duración permitida, cupo
por unidad y por semana, solapamientos parciales, plazo de cancelación, horarios
de disponibilidad, bloqueos por mantenimiento. Cuando dos reglas se pisan hay que
decidir cuál gana, y esa decisión hay que poder defenderla.

Aquí eso se trata como un banco de casos con su desenlace esperado escrito por
adelantado, y con una exigencia que es la que de verdad muerde: **un rechazo no
puede decir solo "no se pudo". Tiene que decir cuál regla lo rechazó.** Un caso
que se rechaza por la regla equivocada cuenta como fallo, no como acierto.

---

## 2 · Qué se va a poder comprobar, y quién lo comprueba

La columna de estado es la que dice la verdad hoy, y es la que va cambiando.
*Actualizada el 2026-08-14.*

| # | Conducta | Cómo se comprueba sin creerme nada | Estado |
|---|---|---|---|
| 1 | Peticiones simultáneas al mismo hueco → **exactamente una** confirmada; el resto rechazadas nombrando su regla | **Ejecutas tú el comando** contra el sistema, tuyo o desplegado | ✅ **Construido.** Falta el enlace público |
| 2 | Una reserva que viola una regla → rechazo que dice **cuál** regla | Lo intentas en la interfaz, sin instrucciones | ✅ **Construido.** Falta el enlace público |
| 3 | La prueba de concurrencia **rompe el build** ante una sola confirmación de más | Miras el historial de integración continua, no la prosa | ✅ En verde en cada empujón |
| 4 | **Apagar una regla a propósito tumba el build** | Miras las herramientas que las apagan, una por una | ✅ Las quince reglas, y también los dos controles de seguridad |
| 5 | Tabla de carga publicada **con los números reales, buenos o malos** | Lees §3 | ⬜ Sin medir |
| 6 | **Arranque en frío declarado aparte**, no escondido dentro de un promedio | Lees §3 | ⬜ Sin medir |
| 7 | Freno de gasto **probado** antes del primer recurso, caducidad declarada, y un comando que reconstruye el sistema entero | Lees §6 y §7, y el directorio `infra/` | 🟡 **El freno, probado.** El IaC del borde, escrito y sin ejecutar |

**Para la 1 y la 2 no hace falta esperar al enlace.** El sistema entero corre en
tu máquina, sin cuenta de nube y sin registrarte en nada:

```bash
python -m herramientas.servidor --desarrollo --sembrar     # en una terminal
python -m herramientas.m2_instrumento --url http://localhost:8080   # en otra
```

Lo segundo lanza cincuenta solicitudes simultáneas de cincuenta identidades
distintas contra el mismo hueco, y te enseña el reparto entero. **Y si no
consiguió provocar una carrera de verdad, te lo dice y se niega a publicar el
resultado** — que es la parte que más me importa de esa herramienta.

La 3 y la 4 son las que sostienen a todas las demás. Una prueba que nunca ha
sabido ponerse en rojo no demuestra nada: solo genera confianza injustificada. Y
un banco de reglas en verde no vale nada si nadie ha comprobado que sabe ponerse
rojo cuando se rompe una regla.

**La 1 es la que cambia la conversación.** El repositorio va a entregar un
comando que lanza decenas de peticiones simultáneas contra el mismo horario y te
enseña el reparto completo del resultado. Está puesto ahí para que intentes
provocar la doble reserva. Si consigues que acepte dos, es exactamente lo que
quiero saber.

---

## 3 · Los resultados

Las columnas se escribieron **antes de medir**, para que después no se pudiera
elegir cuáles publicar. Las filas se llenan a medida que se miden; las que no se
han medido siguen vacías y se nota.

### 3.1 · Concurrencia

Cada fila se ejecuta por dos vías: dentro de la integración continua, donde una
violación rompe el build, y **contra DynamoDB de verdad**, mediante el comando que
cualquiera puede ejecutar. *Las cifras de abajo son las del motor real, y están en
`evidencia/k-motor-real.txt`.*

> **Por qué hizo falta el motor real, y no bastaba el local.** El local es un solo
> proceso: serializa más que el real, así que **no puede producir menos dobles
> reservas que él**. La asimetría va en una sola dirección — si en local salieran
> dos confirmadas, saldrían dos en la nube y **eso refutaría el diseño**; pero que
> salga una en local **no demuestra** que salga una en la nube. Por eso la
> confirmación exigía el motor real, y por eso se hizo. En esas corridas se
> observó `TransactionConflict`, que es la ruta de código que el local **nunca**
> ejercita.

| Caso | Qué se lanza | Lanzadas | Compitieron de verdad | Confirmadas | Evidencia directa de carrera | Veredicto |
|---|---|---|---|---|---|---|
| K-01 | 50 unidades distintas, **el mismo horario** | 50 | **50 de 50** | **1** | 49 · perdieron la condición de escritura | ✅ **motor real** |
| K-02 | Dos reservas que **se solapan a medias** (10:00–14:00 y 12:00–16:00) | 2 | **2 de 2** | **1** | 1 | ✅ **motor real** |
| K-03 | 50 peticiones repartidas entre **cinco horarios** del mismo día | 50 | **50 de 50** | **5** | 45 | ✅ **motor real** |
| K-05 | Cuatro peticiones de la misma unidad en cuatro horarios, con **cupo de tres** | 4 | **4 de 4** | **3** | **0 — ver abajo** | ✅ **motor real**, con salvedad |
| K-04 | Dos peticiones de **la misma unidad** por el mismo horario | | | | | sin medir |
| K-06 | Una reserva y **una cancelación** del mismo horario, a la vez | | | | | sin medir |
| K-07 | 50 peticiones sobre un horario **bloqueado por mantenimiento** | | | | | sin medir |

**La salvedad de K-05 se publica porque es la que más tienta a callar.** Salió
correcta —tres confirmadas, el cupo respetado, las tres invariantes en verde— y
aun así **cero rechazos por pérdida de la condición de escritura**, que es la
única señal inmune al reloj. Las cuatro peticiones eran de la misma unidad y por
horarios distintos: no disputaban ninguna franja entre sí, así que el cupo se
resolvió por el contador de la transacción y no hubo carrera de franja que
observar. **El resultado vale; la corrida no demuestra concurrencia por sí sola.**
Escribirlo como un ✅ a secas habría sido la clase de redondeo que este documento
existe para no hacer.

**La simultaneidad no se supone, se mide.** En K-01 contra el motor real las 50
peticiones estuvieron en vuelo a la vez —50 de 50, contadas— y la dispersión de
la barrera de disparo fue de **85 ms**, que se publica aunque no haga falta: en
una máquina más lenta podría morder, y entonces el número que hay que corregir es
el de peticiones, no el criterio. La propia prueba lleva un guardia que comprueba
que **un bucle secuencial da solape 1** — si el medidor no sabe detectar la
ausencia de concurrencia, no sirve para afirmar su presencia.

**Dos mutaciones, y las dos ponen el build en rojo:**

| Qué se rompe a propósito | Qué pasa |
|---|---|
| Se quita la escritura condicional | **50 confirmadas** sobre el mismo horario |
| Se canoniza la hora en otro huso en la mitad de las peticiones | **2 confirmadas**, con el mecanismo intacto y **sin violar ninguna regla** |

La segunda es la interesante, y es la razón de que la clave se componga en un solo
sitio del código: **la unicidad la impone la clave, no el horario.** Si dos
peticiones por el mismo hueco producen dos claves distintas, no colisionan — y
todo lo demás funciona de maravilla mientras el sistema acepta dos reservas del
mismo sábado.

**K-03 es el guardia, y merece una explicación.** Un sistema que rechazara
absolutamente todo pasaría K-01 con nota: cero dobles reservas, garantizado. K-03
lo descarta, porque con cinco horarios libres y cincuenta peticiones exige
**cinco** confirmadas, una por horario. Correcto no basta: además tiene que
servir para algo.

**Y la columna que casi nunca se publica es "compitieron de verdad".** No todas
las peticiones que se lanzan llegan a disputar el horario: algunas se quedan por
el camino, estranguladas por la capacidad contratada. Contar esas como si
hubieran competido sería inflar el denominador. Así que la regla está fijada de
antemano:

> El criterio es **cero dobles reservas sobre al menos 50 peticiones que consten
> como competidoras reales**. Si en una corrida solo compitieron 31, no se
> redondea hacia arriba: **se publica 31, y por qué no llegaron a 50.** Decir
> "cero sobre 50" habiendo competido 31 sería medir la cosa parecida en vez de la
> cosa, justo en el único número que este proyecto no puede negociar.

Si la medición no es válida —porque el instrumento falló, no porque el sistema
fallara— **la herramienta lo declara y el resultado no se publica como
evidencia**. Un número sin simultaneidad observada no es un resultado: es una
ilusión con formato de tabla.

### 3.2 · Carga y latencia

| Medida | Valor | Cuándo se midió |
|---|---|---|
| Peticiones por segundo sostenidas | | |
| Latencia p95, en caliente | | |
| **Arranque en frío, declarado aparte** | | |
| Dobles reservas bajo esa carga | | |
| Peticiones que no llegaron a competir, y por qué | | |

**Si esta tabla se queda vacía, se borra y este README no vuelve a usar la
palabra "escalable" ni menciona ninguna latencia.** No se mide, no se afirma. Que
la plataforma escale no es lo mismo que que escale *este* sistema: el modelo de
datos, las reglas de concurrencia y los límites de capacidad son míos, y son
justo lo que puede no escalar.

---

## 4 · «Tu problema es la unicidad. En Postgres eso es una línea. ¿Por qué DynamoDB?»

Es la pregunta que más duele y la más justa, así que va escrita y no improvisada.

**Primero, la parte de la pregunta que es correcta:** sí, en PostgreSQL esto se
resuelve con una restricción de unicidad, y sería la decisión sensata para un
producto real de reservas. No voy a defender lo contrario.

**Y ese es justamente el punto.** Cuando el motor te regala la garantía, no
aprendes nada sobre ella: la declaras y funciona. Este proyecto elige un motor
que **no** la regala para tener que responder la pregunta completa: qué garantiza
el motor, qué no garantiza, y qué hay que diseñar para reemplazar esa línea que
aquí no existe.

La respuesta, en corto: la unicidad se consigue haciendo que **el hueco de tiempo
sea la clave del registro**, y dejando que la imponga el motor en la propia
escritura, sin lectura previa que decida nada. Pero eso no sale gratis. Depende de
cinco condiciones de diseño, y basta que falle una:

1. **Que el hueco sea la clave**, no un campo dentro del registro. Si no lo es, no
   hay unicidad de ninguna clase.
2. **Que esa clave se calcule siempre igual.** Dos formas de normalizar una hora
   son dos claves distintas, y dos claves distintas son dos reservas del mismo
   hueco. Aquí es donde el sistema puede fallar sin violar ninguna regla de
   negocio.
3. **Que una reserva de varias franjas se escriba entera o no se escriba.** Si no,
   el solapamiento parcial se cuela.
4. **Que no haya copias de la tabla en otra región.** Con copias, un conflicto se
   resuelve por "el último que escribió gana" y una de las dos reservas desaparece
   sin ruido — sin error, sin registro, sin nada que mirar después.
5. **Que un choque entre operaciones simultáneas se distinga de un "ese hueco ya
   está ocupado"**, y se reintente un número acotado de veces. Si se confunden,
   una carrera puede terminar con **cero** reservas confirmadas sobre un horario
   que estaba libre. Eso también es un fallo, y es el que nadie mira.

Ninguna de las cinco viene puesta. **Y ninguna de las cinco está comprobada
todavía:** lo que hay arriba es lo que la documentación del motor promete, no lo
que este proyecto ha verificado. Comprobarlo contra el motor real, con peticiones
de verdad, es el primer trabajo del proyecto. Si las garantías no se sostienen, no
hay proyecto — y este README lo dirá en vez de callarlo.

**Cuándo no elegiría esto:** si el problema principal fuera consultar y cruzar
datos entre entidades —quién debe cuánto, qué pagó quién, cuánto se recaudó el
mes pasado—, esta elección sería la equivocada. Lo sé porque el proyecto anterior
tenía ese problema, y ahí la decisión fue la contraria.

---

## 5 · El otro repositorio, y por qué son dos

Este es el segundo de dos, y están hechos sobre el mismo negocio a propósito.

El primero —[`cartera-consultas-ia`](https://github.com/erickcolin2005/cartera-consultas-ia)—
resuelve **consultas en lenguaje natural sobre datos de cartera de una
copropiedad**: preguntas escritas en español que un modelo traduce a SQL y que
pasan por una comprobación que las ejecuta o las rechaza nombrando la regla. Ahí
el problema es relacional de arriba abajo: entidades que se cruzan, agregaciones,
una respuesta correcta que hay que poder auditar. Ese problema pide SQL, y usa
SQL.

Este resuelve otra cosa del mismo negocio: **reservas puntuales de espacios**,
donde la pregunta no es "qué respondió" sino "quién llegó primero". Un hueco de
tiempo está libre o no lo está, no hay respuesta parcial, y dos peticiones
simultáneas tienen que resolverse sin que el sistema tenga que pensarlo.

**No son la misma decisión, y por eso no se resolvieron con la misma
herramienta.** Ese contraste —dos problemas del mismo negocio, dos arquitecturas,
porque los problemas son distintos— es lo único que ninguno de los dos
repositorios puede enseñar por separado. Por eso el enlace de arriba está aquí y
no al final.

---

## 6 · Esta demo va a caducar, y se sabe desde antes de existir

> ### ⚠️ Corregido el 2026-08-14 — lo que decía aquí era falso
>
> Esta sección afirmaba que la cuenta estaba en **Plan Gratuito** y que por tanto
> *«AWS no puede cobrarme»* y *«la cuenta vive seis meses»*. **Las tres cosas son
> falsas para esta cuenta.**
>
> Al abrirla y consultarla con `freetier:GetAccountPlanState`, resultó estar en
> **Plan de Pago**, sin fecha de caducidad y con **cero créditos** — la decisión
> de abrirla en el gratuito se tomó y no se aplicó, y nadie lo habría sabido sin
> comprobarlo. El FAQ oficial es literal: no se puede degradar.
>
> **Se deja el error escrito en vez de reescribir la sección en limpio.** Un
> proyecto que existe para denunciar afirmaciones sin medir no puede borrar las
> suyas: esto es un texto que llevaba semanas siendo falso porque un cambio de
> premisa no se propagó, que es exactamente el fallo que aquí se persigue.

Lo que es cierto hoy:

- **AWS sí puede facturar.** No hay apagado automático que sustituya al
  guardarraíl, así que **el guardarraíl es lo único que hay** — y por eso se monta
  antes que ningún otro recurso, con acción de denegación y umbral de 5 USD.
- **La cuenta no caduca.** Desaparece el reloj de seis meses, y con él la
  restricción que gobernaba el plan entero.
- **El gasto esperado sigue siendo cero, pero por una sola razón y no por dos:**
  los límites del *free tier*, no los créditos. Y eso cambia cómo se puede
  escribir: **«cero porque el uso se queda bajo los límites del free tier»**,
  nunca «cero garantizado por contrato». Son cosas distintas y este repositorio
  no puede confundirlas.

### 6.1 · Dónde vive la demo pública, y por qué no en AWS

**La demo pública no se aloja en la cuenta de AWS, y la razón es económica, no
técnica.** El instrumento de §2 es una superficie de consumo **abierta y
anunciada a desconocidos**: un comando que invita a cualquiera a lanzar cincuenta
solicitudes simultáneas, en bucle si quiere.

El análisis de costos de este proyecto concluyó que esa superficie era asumible
**porque la cuenta apagaba en vez de cobrar**. Con la cuenta en Plan de Pago y
cero créditos, esa premisa desapareció — y con ella, el argumento. Dejar una
superficie así anunciada y desatendida sobre una cuenta que puede facturar es
precisamente el riesgo que este proyecto describió como **no acotable con
código**.

Así que se parte en dos, y el corte va donde está el riesgo:

| | Dónde | Por qué |
|---|---|---|
| **La demo que se enlaza** | Fuera de AWS, en el nivel gratuito de un alojamiento de contenedores — declarado en [`render.yaml`](render.yaml) | Es lo que queda vivo y desatendido. Ahí el peor caso es perder la demo, no recibir una factura |
| **El despliegue en AWS** | En la cuenta, en una ventana **corta y supervisada** | Es donde se captura la evidencia grabada y donde se prueba el freno. Con el instrumento en mis manos, no en las de un desconocido en bucle |

**Lo que se pierde diciéndolo:** la demo que puedes tocar no corre sobre
DynamoDB, sino sobre su sustituto local. **Lo que no se pierde:** el mecanismo
está medido contra DynamoDB de verdad —esa medición es la que respalda la
afirmación de §3— y el IaC que levanta el sistema entero en AWS está en `infra/`
y se ejecuta con un comando.

Que el mismo código corra en los dos sitios sin tocar el núcleo no es casualidad:
es lo que compra la frontera de `reservas/adaptadores/`, y es la única parte de
este README que la justifica de verdad.

**Y lo que vas a notar al abrir el enlace, dicho antes de que lo notes:** la
máquina gratuita son 512 MB y **0,1 de CPU**, y duerme cuando nadie la usa.
Arrancar el motor con una décima de CPU tarda entre **53 y 71 segundos** —está
medido, en [`evidencia/contenedor-en-una-decima-de-cpu.txt`](evidencia/contenedor-en-una-decima-de-cpu.txt)—,
así que es probable que esperes cerca de un minuto. No es el sistema siendo
lento: es una máquina de cero euros despertándose. Con el sistema ya en pie, las
cincuenta simultáneas salen igual, y esa misma medición lo enseña.

---

O sea que **el enlace de la demo se va a morir de todas formas**, y se sabe antes
de publicarlo. Un enlace muerto en un README es peor que no tener enlace, así que
la demo no es el entregable:

> El entregable es **la infraestructura como código que levanta el sistema entero
> con un comando en una cuenta limpia**, más la evidencia grabada del sistema
> corriendo de verdad. La URL vive mientras viva la cuenta. Lo otro no caduca.

Consecuencia práctica: la evidencia grabada **se captura en cuanto haya algo que
capturar**, no al final. Es la única parte de este proyecto cuyo aplazamiento es
irreversible: si la cuenta se cierra antes, esa evidencia no se recupera nunca.

Y cuando el enlace desaparezca, este README no habrá que editarlo, porque el
enlace nunca se publicó solo: siempre acompañado de su fecha de caducidad, de la
evidencia y del comando que reconstruye todo.

### 6.2 · Lo que hay que darle al sistema para que arranque

Esta sección existe porque el código la exige por su nombre: cuando falta un
parámetro, el mensaje de error dice *«no hay valor por defecto: quien lo fija lo
declara en el README»* — y hasta hoy el README no las declaraba. **Se añade
anotando el hueco, no fingiendo que no estuvo.**

Ninguno de estos ocho tiene valor por defecto, ni en la imagen ni en la función.
No es rigidez: un despliegue con una variable mal puesta arrancaría con un valor
de demostración y **parecería configurado**. La diferencia entre «falla» y «no
arranca» es quién se entera.

| Variable | Qué fija | Valor de la demo pública |
|---|---|---|
| `RESERVAS_ESPACIOS` | Qué espacios existen | `E-SAL,E-BBQ,E-CAN` |
| `RESERVAS_VENTANA_SEGUNDOS` | La ventana que comparten los dos contadores. **Fija, no deslizante** | `300` |
| `RESERVAS_TOPE_POR_IDENTIDAD` | Intentos que una identidad puede hacer por ventana | `5` |
| `RESERVAS_TOPE_POR_ORIGEN` | Lotes de identidades que un mismo origen puede pedir prestados por ventana | `20` |
| `RESERVAS_CAPACIDAD_DEL_BORDE` | Lo que el borde deja pasar en esa misma ventana | `250` |
| `RESERVAS_ENFRIAMIENTO_SEGUNDOS` | Espera entre ejecuciones del instrumento | `20` |
| `RESERVAS_ORIGEN_PERMITIDO` | El único origen que CORS admite. Nunca `*` | La URL pública, con `https://` y sin barra final |
| `RESERVAS_CLAVE_FIRMA` | Firma las credenciales que presta el dispensador | Un secreto generado, distinto en cada despliegue |

**Los 250 no son un número redondo elegido a ojo.** El sistema comprueba **al
arrancar** que `identidades × tope ≤ capacidad del borde`, y el sembrado crea 50
unidades activas: 50 × 5. Si la desigualdad no se cumple, no arranca — porque
entonces el borde rechazaría antes que el contador, el instrumento empezaría a
recibir errores de tasa y **la medición se invalidaría sin que nadie hubiera
tocado el contador**. Es una desigualdad que hay que verificar, y una desigualdad
que hay que acordarse de verificar es una que un día no se verifica.

**En tu máquina no hace falta teclear nada de esto:** `--desarrollo` rellena los
huecos con estos mismos valores. Rellena solo los huecos — lo que el entorno diga
sigue mandando, porque al revés un despliegue mal configurado arrancaría en modo
demostración sin decirlo.

**Y el fallo que no se parece a su causa:** si `RESERVAS_ORIGEN_PERMITIDO` no
coincide **exactamente** con el origen desde el que se sirve la página, la página
carga, se ve entera y no hace nada. No aparece ningún error: el navegador bloquea
la llamada por CORS y el servidor ni se entera de que alguien lo intentó.

**Y todo esto está ejecutado, no deducido.** El comando que documenta el
`Dockerfile` nació sin correrlo y moría al arrancar; la corrida completa —imagen,
contenedor sano, el instrumento contra él, y el negativo al que le falta una
variable— está en
[`evidencia/contenedor-comando-documentado.txt`](evidencia/contenedor-comando-documentado.txt).

---

## 7 · Lo que cuesta, y cómo se sabe que no va a costar más

Este apartado existe porque es la otra mitad de "sé desplegar": saber qué pasa
con la factura. Lo que sigue se verificó en la documentación oficial antes de
abrir la cuenta, no se recuerda de memoria.

**AWS ya no da el free tier de 12 meses a las cuentas nuevas.** Lo reemplazó por
un modelo de créditos con dos planes: uno gratuito, que apaga la cuenta cuando se
agotan los créditos o a los seis meses, y uno de pago, que sigue abierto y cobra
tarifa estándar.

> **Corrección del 2026-08-14.** Aquí decía *«este proyecto elige el gratuito:
> prioriza riesgo de cobro cero sobre permanencia de la cuenta»*. Se eligió, sí,
> **y no se aplicó**: la cuenta quedó en Plan de Pago (§6). La frase describía una
> decisión, no un hecho, y llevaba semanas leyéndose como lo segundo.
>
> Lo que se gana con el plan de pago, y no es menor: **API Gateway y S3 recuperan
> su año gratis**, que solo está activo ahí. Lo que se pierde es el amortiguador,
> que era justamente lo que sostenía el argumento de §6.1.

Tres hechos que cambiaron decisiones de diseño, no solo el presupuesto:

| Hecho verificado | Qué obligó a cambiar |
|---|---|
| **El free tier de API Gateway es una oferta de plazo limitado**, no perpetua. En Plan Gratuito no está activa; en Plan de Pago sí | Motivó aislar API Gateway tras un adaptador desde el primer día. **Y la cuenta acabó en Plan de Pago**, así que el año gratis está activo — la decisión se mantiene, pero ya no por longevidad de la cuenta, sino porque separar la lógica de su transporte es lo que permite que el mismo código corra en AWS y fuera de él (§6.1) |
| **El free tier perpetuo de DynamoDB exige modo aprovisionado**, no bajo demanda | Es una condición de diseño y además un techo real de capacidad de escritura. Pasar la tabla a modo bajo demanda es una casilla, y sacaría la tabla del free tier en silencio |
| **AWS no tiene un tope duro de gasto.** Un presupuesto **notifica**, no frena | El freno hay que construirlo: una acción de presupuesto con política de denegación. Y no basta con que exista |

Ese último punto es el que ordena el trabajo. **El freno se monta y se prueba
antes de crear el primer recurso**, y "probado" no significa que llegue el correo:
significa que un intento de superar el umbral es **efectivamente denegado**. Es la
primera tarea del proyecto en la nube, no la última.

Sobre el resultado: **el gasto esperado es cero, y ahora sí hay algo de mérito en
ello — pero menos del que parece.** No lo garantiza el plan, porque este plan no
garantiza nada: lo garantizan los límites del *free tier* y el hecho de que los
volúmenes de este proyecto caben dentro con holgura. Lo que sí es trabajo es el
freno, porque AWS no lo trae puesto; **acotar el consumo del instrumento**, que es
lo único del alcance que un desconocido puede disparar en bucle; y la
reproducibilidad, porque es lo que hace que el proyecto sobreviva al cierre de la
cuenta.

Y una cifra que salió de medir y no de estimar: **una reserva confirmada consume
8 unidades de escritura, no 1.** La intuición dice que una reserva es una
escritura; el motor cobra por una transacción de varios ítems, cada uno a doble
tarifa. De ahí sale todo lo demás —la tasa sostenida real, y que una ejecución
del instrumento sean ~400 unidades de golpe sobre 25 sostenidas—. Estimarlo desde
el modelo habría dado una cifra tranquilizadora y falsa.

**Lo que no verifiqué:** la lista completa de servicios restringidos del Plan
Gratuito —la documentación da ejemplos, no un listado cerrado— y la clasificación
de Lambda como servicio siempre gratuito, que viene de la documentación de
facturación y no de una frase explícita en su página de precios. Además, esto es
una verificación de un día concreto: AWS cambió este esquema una vez y puede
volver a cambiarlo.

Fuentes:
[planes del free tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html) ·
[precios de API Gateway](https://aws.amazon.com/api-gateway/pricing/) ·
[precios de DynamoDB](https://aws.amazon.com/dynamodb/pricing/on-demand/) ·
[acciones de presupuesto](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html)

---

## 8 · Lo que este repositorio no va a afirmar

- **No va a decir "escalable" sin una tabla de números detrás.** Si la prueba de
  carga no se corre, la palabra no aparece y §3.2 se borra.
- **No va a esconder el arranque en frío** dentro de un promedio. Va aparte, con
  su número, aunque sea el peor.
- **No va a publicar una tabla de resultados sin sus fallos dentro.** Una tabla
  perfecta es una tabla que alguien limpió.
- **No es un sistema en producción.** Preparado para producción, que es otra cosa.
- **No es un producto de reservas** y no compite con ninguno. Sí, esto ya existe
  comprado; ese no es el punto.
- **No sanciona a nadie.** Si alguna vez bloquea a un residente, está ejecutando
  una decisión tomada fuera del sistema, no arrogándose una facultad.
- **Los datos son sintéticos**, generados para este proyecto. Ni una fila viene de
  un sistema real, y la interfaz lo va a decir donde se pueda leer sin buscarlo.

---

## 9 · Estado, sin adornos

*Al 2026-08-14. Esta tabla decía «Código: Nada · Pruebas: Ninguna · Cuenta de
AWS: Sin abrir» hasta hoy, y llevaba meses siendo falsa — en el mismo archivo que
termina exigiendo que se corrija cada vez. Queda anotado.*

| Qué | Hoy |
|---|---|
| Código | Núcleo puro, adaptadores, frontera HTTP, seguridad, instrumento e interfaz |
| Pruebas | **404 en verde**, más tres suites de mutación que las ponen en rojo a propósito |
| Integración continua | En verde en cada empujón, en una máquina que no es la mía |
| Cuenta de AWS | Abierta. **En Plan de Pago y sin créditos**, contra lo que se había decidido (§6) |
| Guardarraíl de costos | Desplegado **antes que ningún otro recurso**, y probado: deniega y nombra su causa |
| Motor real | La tabla existe y el mecanismo está verificado contra ella |
| Despliegue del borde | **Escrito y sin ejecutar.** El IaC está en `infra/`, el procedimiento también |
| Demo | No existe todavía. El despliegue está **declarado** en `render.yaml` y sin ejecutar; irá fuera de AWS y con su caducidad declarada (§6.1) |
| Evidencia visual grabada | **Pendiente, y es lo único irreversible**: si la cuenta muere sin ella, no se recupera |
| Tablas de §3 | Con las cifras de concurrencia dentro. **Las de carga y latencia siguen en blanco**, y por eso están ahí |

Lo que sí existe es la decisión de en qué orden hacer las cosas: **primero cerrar
la carrera, después todo lo visible.** Al revés —frontend desplegado, integración
continua bonita y la concurrencia sin resolver— es cómo se llega al final con la
plomería impecable y sin nada que demostrar.

Y una regla que gobierna este archivo mientras dure el proyecto: **ningún avance
se da por terminado hasta que este README diga lo que el sistema hace y lo que no
hace a esa altura.** No se escribe al final. Se corrige cada vez.
