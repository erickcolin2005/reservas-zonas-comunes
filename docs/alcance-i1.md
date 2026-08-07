# Incremento I-1 — qué hay, qué no hay, y qué quedó abierto

Este fichero existe por la verificación **V5** del plan de construcción: *lo que
quedó pendiente o degradado se escribe donde se pueda encontrar, no se recuerda*.

No sustituye al README. El README dice lo que el sistema hace y lo que no para
quien llega de fuera; esto es la lista de trabajo para quien construye el
siguiente incremento.

> **Nada de este incremento toca AWS.** No hay recursos creados, no hay cuenta,
> no hay credenciales y no hay secretos en el repositorio. El reloj de seis meses
> de la cuenta **no ha arrancado**: eso ocurre en I-2, y su disparador es
> justamente que I-1 esté en verde.

---

## 1 · Qué se construyó

| Pieza | Dónde | Qué cierra |
|---|---|---|
| **V-2a** — capacidades del sustituto local | `herramientas/v2a_sonda.py`, `pruebas/test_v2a_sustituto_local.py` | Que el sustituto implementa escritura condicional y transacciones, y con qué semántica de error |
| **Canonización de la clave** | `reservas/nucleo/tiempo.py`, `reservas/nucleo/claves.py` | Las cinco reglas de `modelo-datos` §4.3, con pruebas propias |
| **Núcleo de reglas, puro** | `reservas/nucleo/reglas.py` | RR-07…RR-10. RR-11 inalcanzable desde la lectura, por construcción |
| **Escritura condicional y transacción** | `reservas/adaptadores/dynamodb.py` | El mecanismo: el hueco *es* el ítem, y la condición decide |
| **Reintento acotado y marca pegajosa** | `reservas/casos_uso/reservar.py` | ADR-04. *No ejercitable en local* — ver §4 |
| **Datos sintéticos** | `reservas/sembrado.py` | 50 activas + 1 inactiva + 1 administración + 3 espacios, relativos a T0 |
| **Cubos, competidoras efectivas, tres invariantes** | `reservas/desenlaces.py` | D-P4-08 y `banco` §5.0 |
| **Barrera de disparo y medición de simultaneidad** | `reservas/concurrencia.py` | Las tres señales de `arquitectura` §9 |
| **K-01, K-02, K-03** | `herramientas/casos_k.py`, `pruebas/test_concurrencia_k.py` | El criterio de cierre de I-1 |
| **H2 — mutación de las defensas** | `herramientas/sensibilidad.py`, `pruebas/test_h2_defensa_revertida.py` | Que el verde sabe ponerse rojo |
| **CI en cada push** | `.github/workflows/ci.yml` | RNF-14 |

---

## 2 · Qué NO se construyó, y a qué incremento pertenece

Nada de esta lista es un olvido. **Ampliar el alcance de I-1 era uno de los tres
fallos que este incremento existía para evitar.**

| Falta | Incremento | Consecuencia hoy |
|---|---|---|
| API expuesta y frontend | I-6 | Nada de I-1 es accesible desde fuera. No hay superficie pública que asegurar |
| Autorizador e identidad probada (ADR-26) | I-6 | **La unidad llega como dato del llamador.** No hay suplantación posible porque no hay nadie a quien suplantar: no hay borde |
| Contador de intentos (SEC-1, ADR-29) | I-6 | **El paso 2 del camino de escritura de `modelo-datos` §5.0 no existe.** Está declarado en `reservas/puertos.py` |
| Dispensador de identidades y los dos grupos (ADR-30, ADR-31) | I-6 | El sembrado ya escribe el campo `grupo`, pero nadie presta nada. `reserva_sesion` vale 0 por defecto |
| RR-01…RR-06 | I-4 | Registradas en su orden y **sin cuerpo**. Una precondición ausente levanta `PrecondicionAusente` en vez de fabricar un veredicto |
| RR-12…RR-15, cancelación, mantenimiento | I-4 | — |
| Los 75 casos del banco | I-4 | — |
| Mutación sobre las 15 reglas (M4) | I-5 | H2 cubre **solo** las defensas de I-1 |
| Registro de intentos y seudónimo (RF-19, D-P4-09b) | I-4 / I-6 | No hay registro. S-2 se mide en el proceso que lanza, no del registro |
| IaC, despliegue, expiración activa | I-7 | El atributo `ttl` se escribe; el mecanismo no se activa ni se prueba |
| Prueba de carga (M7) | I-8 | — |
| Instrumento para un extraño (M2-INS) | I-6 | El motor de medición ya existe y se reutilizará; la herramienta de línea de órdenes, no |

---

## 3 · Valores que siguen abiertos y que el código **no** inventa

| Valor | De quién | Dónde está hoy |
|---|---|---|
| **`H`** — horizonte de vida de una reserva pasada (RT-2) | **Erick** (VALIDAR-ERICK) | `config.HORIZONTE_H_DIAS_PRUEBA = 30`, marcado como **valor de prueba, no decisión**. Ninguna prueba de I-1 depende de él |
| **Todos los valores de `banco` §2** — ventanas, duraciones, antelaciones, horizontes, cupos, plazos | **Erick** (VALIDAR-ERICK) | `reservas/sembrado.ESPACIOS`. Siguen siendo `[A]` de `analyst-agent`. **Ya no son gratis de cambiar**: tocarlos obliga a recalcular los desenlaces esperados de los casos que los usen |
| **Ventana y tope del contador de intentos** | `security-agent` | No existe contador. Cota inferior conocida: 4 |
| **`reserva_sesion` y `vigencia_sesion`** | `design-agent` | Parámetro del sembrado, por defecto 0 |
| **Cuántas veces repetir cada caso K** (Q-9) | `qa-agent` | Una vez por push. `--repeticiones N` para más |
| **Reintentos y espera de ADR-04** | Medición en I-3 | `config.Reintentos`: 5 intentos, espera base 10 ms, tope 200 ms. **Elegidos aquí y declarados**, no verificados |

---

## 4 · Lo que el sustituto local no puede probar

Sale de V-2a y gobierna cuánto vale el verde de este incremento.

> **Un sustituto local serializa más que el servicio real.** Por eso
> **dos confirmaciones en local ⇒ dos confirmaciones en AWS** (refutación
> válida), pero **una confirmación en local ⇏ una confirmación en AWS**
> (confirmación **no** válida). **H1 es provisional hasta I-3.**

| No reproducible en local | Medido en V-2a | Consecuencia |
|---|---|---|
| **Conflicto de transacción** (`TransactionConflict`) | 16 transacciones simultáneas sobre el mismo ítem: **ninguna** devolvió conflicto | El reintento acotado y la marca pegajosa de **ADR-04 nunca se ejecutan en local**. Están implementados y **sin ejercitar**. Su primera prueba real es I-3 |
| **Estrangulamiento por capacidad** | 200 escrituras seguidas sobre 25 WCU: **cero** estrangulamientos | El cubo `SYS-CAPACIDAD` existe en el código y no se puede provocar. `SYS-CONTENCION` tampoco, porque depende del conflicto |
| Arranque en frío, latencia, momento de la expiración | — | Nada de C4 ni de C5 se afirma aquí |

---

## 5 · Hallazgos que devuelven trabajo a F2 y a F1

Tres cosas de la especificación **no son construibles tal como están escritas**.
Ninguna es un fracaso: las tres son información que solo aparece al implementar.

### 5.1 · El enunciado de la vivacidad de `banco` §5.0 es falso para K-02 → `analyst-agent`

El banco enuncia: *para toda franja con competidoras efectivas ≥ 1,
confirmadas = 1*.

En K-02, `10-14` y `12-16` comparten solo las franjas de las 12 y las 13. Si gana
`12-16`, la perdedora había disputado además las de las 10 y las 11 —que nadie
más quería— y esas quedan con cero confirmadas. **Eso es el todo-o-nada
funcionando**, que es justo lo que K-02 existe para comprobar. Con el enunciado
literal, **K-02 sale en rojo con el sistema correcto**, y se comprobó: la primera
ejecución lo hizo.

Sustituido por tres comprobaciones, documentadas en
`reservas/desenlaces.evaluar_invariantes` y probadas en `pruebas/test_desenlaces.py`.

### 5.2 · La idempotencia de ADR-25 es inalcanzable por el camino normal → `architect-agent`

RNF-11 promete que reintentar una solicitud con el mismo token devuelve la
confirmación en vez de un rechazo. El mecanismo del token **funciona** —está
probado contra el motor—, pero **no se llega a él**: la repetición encuentra su
propia entrada en `AGENDA#` durante la lectura previa y **RR-08 la rechaza antes**.

Es una interacción entre ADR-19 (agenda atómica) y ADR-25 que ningún documento
de F2 contempla. El comportamiento observado queda fijado por una prueba que lo
dice con esas palabras, para que el hueco no se pierda.

### 5.3 · V-2 no era ejecutable entera, y la partición propuesta se confirma → `architect-agent`

La partición **V-2a en I-1 / V-2b en I-3** (Q-4 del plan) resultó necesaria y
suficiente: **V-2a sale POSITIVA** y no requirió nada del motor real. La
comparación de la semántica de error entre los dos motores sigue siendo V-2b.

### 5.4 · Desviación declarada: aquí `RR-11 = 0` sí rompe el build → `qa-agent`

`banco` §5.0 y ADR-13 dicen que la ausencia de RR-11 es **aviso de medición**, no
fallo, y dan una razón buena: exigirlo en rojo haría la prueba intermitente
porque la simultaneidad efectiva no es determinista.

**En I-1 se hace fallar de todos modos**, y la razón también es buena: sin un
solo RR-11 no hay evidencia directa de que dos solicitudes estuvieran dentro a la
vez, y un verde en esas condiciones es exactamente el fallo fatal n.º 1 pasando
desapercibido. Un caso K que no produjo carrera no puede publicarse como si la
hubiera producido.

Las dos lecturas son defendibles y **la decisión es de `qa-agent`**. Está aislada
en `pruebas/test_concurrencia_k.py::test_k01_hubo_simultaneidad_observada` y
cambiarla es una línea. Observado hasta ahora: 45–49 RR-11 por corrida sobre 50
solicitudes; el margen es amplio, pero **no se ha medido en un runner de CI
real** (§8).

---

## 6 · Cómo se ejecuta

Máquina limpia, sin cuenta de AWS. Sólo hacen falta Python y Docker.

**Probado en Python 3.13.14 y Docker 28.5.1, en Windows 11.** El CI corre sobre
Python 3.13 en Linux. En otras versiones debería funcionar y **no se ha
comprobado**, así que no se afirma.

```
python -m venv .venv
.venv/Scripts/activate        # en Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python -m pytest              # la suite entera; levanta el sustituto local sola
```

Herramientas, cada una por separado:

```
python -m herramientas.v2a_sonda      # V-2a, con su veredicto
python -m herramientas.casos_k        # K-01, K-02, K-03 con su desglose
python -m herramientas.sensibilidad   # H2: revierte las defensas y exige el rojo
```

Si ya hay un sustituto levantado, o se quiere apuntar a otro:

```
export RESERVAS_ENDPOINT=http://localhost:8000
```

**`RESERVAS_ENDPOINT` no debe apuntar nunca a AWS.** Si lo hiciera, esto dejaría
de ser I-1.

---

## 7 · La evidencia versionada

`evidencia/` guarda la salida real de la última ejecución, con los fallos dentro.
Se regenera al correr las pruebas o las herramientas, y **se vuelve a versionar
cuando cambia**: es el registro de qué se observó, no un adorno.

| Fichero | Qué contiene |
|---|---|
| `v2a-sustituto-local.txt` | Las once preguntas de V-2a con su respuesta observada |
| `casos-k.txt` | K-01, K-02 y K-03 con su desglose por cubo y su simultaneidad |
| `h2-defensa-revertida.txt` | **La constancia del rojo**: qué pasa al apagar cada defensa |

---

## 8 · Lo que falta para dar I-1 por cerrado

El código está y las tres capas de K-01, K-02 y K-03 están en verde. **Aun así,
dos de las cinco verificaciones de cierre del plan (§6.2) no están satisfechas**,
y ninguna de las dos depende del código:

| Verificación | Estado | Qué falta |
|---|---|---|
| **V1** — las pruebas están en verde **en el historial del CI**, no en la máquina local | **NO** | El repositorio **no está bajo control de versiones todavía** y el flujo de CI **nunca ha corrido en un runner real**. Está escrito y su YAML es válido; eso no es lo mismo que verlo verde. Hasta que se vea, D-D no existe para nadie salvo para quien lo ejecutó |
| **V2** — las pruebas anteriores siguen en verde | n/a | I-1 es el primero |
| **V3** — el **README** dice lo que el sistema hace y lo que no a esta altura | **NO** | El README sigue diciendo *«aquí todavía no hay nada construido… no hay código»*, y ya lo hay. **Es la regla 2 del plan: ningún incremento se da por terminado hasta que el README diga la verdad.** No se tocó porque el encargo lo prohibía expresamente |
| **V4** — cada afirmación nueva del README tiene una medición detrás | pendiente de V3 | Las mediciones existen y están en `evidencia/` |
| **V5** — lo pendiente se escribe donde se pueda encontrar | **SÍ** | Es este fichero |

**Riesgo conocido sobre V1, para que no sorprenda:** las pruebas de concurrencia
exigen que las 50 solicitudes coincidan dentro del sistema
(`S-1 = 50 de 50`). En esta máquina se cumple con holgura, y **en un runner de
CI más lento o con menos núcleos podría no cumplirse**. Si ocurre, el rojo será
correcto —la medición habrá fallado— y lo que hay que subir es N, no bajar el
criterio (D-P4-08 punto 4).
