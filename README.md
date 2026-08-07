# Reservas de zonas comunes, donde dos personas no pueden ocupar el mismo hueco

Un sistema de reserva de zonas comunes de un conjunto residencial —salón social,
BBQ, cancha— construido alrededor de una sola pregunta incómoda: **¿qué hace el
sistema cuando dos peticiones llegan a la vez por el mismo espacio, el mismo día
y a la misma hora?**

La respuesta correcta es "acepta exactamente una". Este repositorio existe para
que eso no sea una afirmación, sino algo que puedas intentar romper tú.

> ## Estado: la carrera está cerrada. Nada más lo está.
>
> **Este README se escribió antes de la primera línea de código, a propósito**, y
> se actualiza cuando cambia lo que hay. No antes.
>
> **Lo que existe hoy y está medido** — contra un motor local, no contra la nube:
>
> - El mecanismo que impide la doble reserva: el hueco **es** la clave, y la
>   unicidad la impone la clave primaria, no una comprobación previa.
> - Una prueba que **produce concurrencia de verdad** —50 hilos con barrera de
>   disparo— y que **mide y publica la simultaneidad que consiguió**, en vez de
>   suponerla. Si no hubo solape real, la medición se declara inválida.
> - **106 pruebas en verde**, y dos mutaciones que las ponen en rojo a propósito
>   (§3.1). Un verde solo demuestra algo si sabe ponerse rojo.
>
> **Lo que NO existe todavía:** API, interfaz, despliegue, demo, el comando con el
> que un extraño provoque la carrera él mismo, las quince reglas de negocio
> completas, y las cifras de rendimiento.
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

Ninguna de estas siete conductas existe todavía. La columna de estado es la que
dice la verdad hoy, y es la que va a ir cambiando.

| # | Conducta | Cómo se comprueba sin creerme nada | Estado |
|---|---|---|---|
| 1 | Peticiones simultáneas al mismo hueco → **exactamente una** confirmada; el resto rechazadas nombrando su regla | **Ejecutas tú el comando** que el repositorio va a entregar, contra el sistema desplegado | ⬜ No construido |
| 2 | Una reserva que viola una regla → rechazo que dice **cuál** regla | Lo intentas en la demo, sin instrucciones | ⬜ No construido |
| 3 | La prueba de concurrencia **rompe el build** ante una sola confirmación de más | Miras el historial de integración continua, no la prosa | ⬜ No construido |
| 4 | **Apagar una regla a propósito tumba el build** | Miras la herramienta que las apaga, una por una | ⬜ No construido |
| 5 | Tabla de carga publicada **con los números reales, buenos o malos** | Lees §3 | ⬜ Sin medir |
| 6 | **Arranque en frío declarado aparte**, no escondido dentro de un promedio | Lees §3 | ⬜ Sin medir |
| 7 | Freno de gasto **probado** antes del primer recurso, caducidad declarada, y un comando que reconstruye el sistema entero | Lees §6 y §7, y el directorio de infraestructura | ⬜ No construido |

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
violación rompe el build, y contra el sistema desplegado, mediante el comando que
cualquiera puede ejecutar. **Hoy solo existe la primera.**

> **Salvedad que cambia lo que estos números prueban.** Se midieron contra un
> **motor local**, no contra la nube. Un motor local es un solo proceso: serializa
> más que el real, así que **no puede producir menos dobles reservas que él**. De
> ahí la asimetría, y conviene tenerla clara: si aquí salieran dos confirmadas,
> saldrían dos en la nube — **eso refutaría el diseño**. Que salga una **no
> demuestra** que salga una en la nube. Esa confirmación exige el motor real, y
> todavía no se ha hecho.

| Caso | Qué se lanza | Lanzadas | Compitieron de verdad | Confirmadas | Rechazadas nombrando su regla | Veredicto |
|---|---|---|---|---|---|---|
| K-01 | 50 unidades distintas, **el mismo horario** | 50 | **50** | **1** | 49 · colisión | ✅ local |
| K-02 | Dos reservas que **se solapan a medias** (10:00–14:00 y 12:00–16:00) | 2 | **2** | **1** | 1 · colisión | ✅ local |
| K-03 | 50 peticiones repartidas entre **cinco horarios** del mismo día | 50 | **50** | **5** | 45 · colisión | ✅ local |
| K-04 | Dos peticiones de **la misma unidad** por el mismo horario | | | | | sin medir |
| K-05 | Cuatro peticiones de la misma unidad en cuatro horarios, con **cupo de tres** | | | | | sin medir |
| K-06 | Una reserva y **una cancelación** del mismo horario, a la vez | | | | | sin medir |
| K-07 | 50 peticiones sobre un horario **bloqueado por mantenimiento** | | | | | sin medir |

**La simultaneidad no se supone, se mide.** En K-01 las 50 peticiones estuvieron
en vuelo a la vez —50 de 50, contadas— y la dispersión de la barrera de disparo
fue de **63 a 87 ms**, que se publica aunque no haga falta: en una máquina más
lenta podría morder, y entonces el número que hay que corregir es el de
peticiones, no el criterio. La propia prueba lleva un guardia que comprueba que
**un bucle secuencial da solape 1** — si el medidor no sabe detectar la ausencia
de concurrencia, no sirve para afirmar su presencia.

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

La cuenta de AWS de este proyecto se abre en el **Plan Gratuito**. Eso significa
dos cosas, y las dos van dichas de frente:

- **AWS no puede cobrarme:** cuando se acaban los créditos, apaga en vez de
  facturar. No hay factura sorpresa posible.
- **La cuenta vive seis meses desde el registro.** Después AWS la cierra, retiene
  el contenido 90 días y luego lo borra para siempre.

O sea que **el enlace de la demo se va a morir**, y se sabe antes de publicarlo.
Un enlace muerto en un README es peor que no tener enlace, así que la demo no es
el entregable:

> El entregable es **la infraestructura como código que levanta el sistema entero
> con un comando en una cuenta limpia**, más la evidencia grabada del sistema
> corriendo de verdad. La URL vive mientras viva la cuenta. Lo otro no caduca.

Consecuencia práctica: la evidencia grabada **se captura en cuanto haya algo que
capturar**, no al final. Es la única parte de este proyecto cuyo aplazamiento es
irreversible: si la cuenta se cierra antes, esa evidencia no se recupera nunca.

Y cuando el enlace desaparezca, este README no habrá que editarlo, porque el
enlace nunca se publicó solo: siempre acompañado de su fecha de caducidad, de la
evidencia y del comando que reconstruye todo.

---

## 7 · Lo que cuesta, y cómo se sabe que no va a costar más

Este apartado existe porque es la otra mitad de "sé desplegar": saber qué pasa
con la factura. Lo que sigue se verificó en la documentación oficial antes de
abrir la cuenta, no se recuerda de memoria.

**AWS ya no da el free tier de 12 meses a las cuentas nuevas.** Lo reemplazó por
un modelo de créditos con dos planes: uno gratuito, que apaga la cuenta cuando se
agotan los créditos o a los seis meses, y uno de pago, que sigue abierto y cobra
tarifa estándar. Este proyecto elige el gratuito: prioriza riesgo de cobro cero
sobre permanencia de la cuenta.

Tres hechos que cambiaron decisiones de diseño, no solo el presupuesto:

| Hecho verificado | Qué obligó a cambiar |
|---|---|
| **El free tier de 12 meses de API Gateway es una oferta de plazo limitado, y en el Plan Gratuito no está activa.** Cada llamada sale de los créditos | A este volumen de tráfico son centavos, así que los créditos no son la restricción. **Lo que se agota es el plazo**, y optimizar créditos sería optimizar la variable que no ata |
| **El free tier perpetuo de DynamoDB exige modo aprovisionado**, no bajo demanda | Es una condición de diseño y además un techo real de capacidad de escritura. Pasar la tabla a modo bajo demanda es una casilla, y sacaría la tabla del free tier en silencio |
| **AWS no tiene un tope duro de gasto.** Un presupuesto **notifica**, no frena | El freno hay que construirlo: una acción de presupuesto con política de denegación. Y no basta con que exista |

Ese último punto es el que ordena el trabajo. **El freno se monta y se prueba
antes de crear el primer recurso**, y "probado" no significa que llegue el correo:
significa que un intento de superar el umbral es **efectivamente denegado**. Es la
primera tarea del proyecto en la nube, no la última.

Sobre el resultado: **el gasto va a ser cero, y eso no es mérito de ingeniería.**
Es lo que hace el Plan Gratuito. Lo que sí es trabajo es el freno, porque AWS no
lo trae puesto, y la reproducibilidad, porque es lo que hace que el proyecto
sobreviva al cierre de la cuenta.

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

| Qué | Hoy |
|---|---|
| Código | Nada |
| Pruebas | Ninguna |
| Integración continua | Sin configurar |
| Cuenta de AWS | Sin abrir. El reloj de seis meses no ha arrancado |
| Demo | No existe |
| Tablas de §3 | En blanco, y por eso están ahí |

Lo que sí existe es la decisión de en qué orden hacer las cosas: **primero cerrar
la carrera, después todo lo visible.** Al revés —frontend desplegado, integración
continua bonita y la concurrencia sin resolver— es cómo se llega al final con la
plomería impecable y sin nada que demostrar.

Y una regla que gobierna este archivo mientras dure el proyecto: **ningún avance
se da por terminado hasta que este README diga lo que el sistema hace y lo que no
hace a esa altura.** No se escribe al final. Se corrige cada vez.
