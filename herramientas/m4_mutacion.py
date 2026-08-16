"""M4 — apagar cada regla, una por una, y exigir que el banco se ponga en ROJO.

**Un verde solo demuestra algo si sabe ponerse rojo.** El banco tiene 66 casos y
todos pasan; eso, por si solo, es compatible con un sistema que no comprueba
nada. M4 es lo que distingue las dos situaciones: apaga cada regla y comprueba
que **al menos un caso** se cae. Si apagar una regla no rompe nada, esa regla no
esta vigilada por ninguna prueba, y el criterio se invierte:

    mutacion en ROJO  -> la regla existe y el banco la vigila. Correcto.
    mutacion en VERDE -> **el banco no vigila esa regla. Aqui se rompe el build.**

COMO SE MUTA, Y POR QUE ASI

  El nucleo lleva anclas `# [M4:RR-XX]` delante de cada regla y `# [M4:FIN]` al
  cerrar cada evaluador. La mutacion **borra el bloque entre el ancla de una
  regla y la siguiente**, compila el modulo resultante en memoria y corre el
  banco contra el.

  Se hace con anclas y no adivinando el formato del codigo porque una mutacion
  que falla al aplicarse **es indistinguible de una regla no vigilada** si nadie
  lo comprueba: las dos dejan el banco en verde. Aqui, si un ancla no aparece,
  la herramienta se detiene en vez de contar la mutacion como aplicada.

  Y **no se toca ningun fichero**. La sesion anterior perdio trabajo revirtiendo
  una mutacion con `git checkout` sobre un fichero con cambios sin commitear;
  mutar en memoria elimina esa clase de accidente entera.

QUE NO CUBRE

  **RR-11 no esta aqui, y no puede estarlo.** Es inalcanzable desde la lectura:
  vive en la condicion de escritura, y su mutacion es H2 -`sensibilidad.py`-,
  que necesita el motor. M4 cubre las catorce reglas del nucleo puro; entre las
  dos herramientas, las quince.

Uso:  python -m herramientas.m4_mutacion
"""

from __future__ import annotations

import os
import pathlib
import re
import sys
import types

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FUENTE = RAIZ / "reservas" / "nucleo" / "reglas.py"
EVIDENCIA = RAIZ / "evidencia"

# Misma puerta que en `pruebas/conftest.py`. Aqui el informe es determinista y
# hoy no produciria ruido, pero la regla es "una corrida local no toca la
# constancia del repositorio": si vale para unas herramientas y no para otras,
# no es una regla, es una coincidencia que se rompe el dia que este informe
# gane un numero que cambie.
ESCRIBIR_EVIDENCIA = os.environ.get("RESERVAS_EVIDENCIA") == "1"

ANCLA = re.compile(r"^\s*# \[M4:([A-Z0-9\-]+)\]\s*$")

REGLAS = (
    "RR-01", "RR-02", "RR-03", "RR-04", "RR-05", "RR-06", "RR-07",
    "RR-08", "RR-09", "RR-10", "RR-12", "RR-13", "RR-14", "RR-15",
)


class AnclaAusente(Exception):
    """Una mutacion que no se pudo aplicar. NO cuenta como superada."""


def _mutar(fuente: str, regla: str) -> str:
    """Devuelve la fuente sin el bloque de `regla`.

    El bloque va desde su ancla hasta la siguiente ancla (de otra regla o FIN).
    """
    lineas = fuente.splitlines()
    marcas = [(i, m.group(1)) for i, l in enumerate(lineas) if (m := ANCLA.match(l))]

    # TODOS los bloques de la regla, no solo el primero.
    #
    # Lo descubrio la propia herramienta al afinar el criterio: RR-02 esta
    # implementada DOS VECES -en el flujo de creacion y en el de administracion-
    # y quitar solo el primer bloque dejaba media regla viva, con lo que su caso
    # R-34 seguia pasando.
    #
    # Una mutacion PARCIAL es peor que ninguna: produce un rojo que parece
    # demostrar que la regla esta vigilada, cuando lo vigilado es una mitad.
    bloques = []
    for pos, (i, nombre) in enumerate(marcas):
        if nombre != regla:
            continue
        if pos + 1 >= len(marcas):
            raise AnclaAusente(f"no hay ancla de cierre tras [M4:{regla}]")
        bloques.append((i, marcas[pos + 1][0]))

    if not bloques:
        raise AnclaAusente(f"no hay ancla [M4:{regla}] en {FUENTE.name}")

    conservar = [
        linea
        for i, linea in enumerate(lineas)
        if not any(ini <= i < fin for ini, fin in bloques)
    ]
    return "\n".join(conservar)


def _compilar(fuente: str) -> types.ModuleType:
    modulo = types.ModuleType("reglas_mutadas")
    modulo.__file__ = str(FUENTE)
    modulo.__package__ = "reservas.nucleo"
    codigo = compile(fuente, str(FUENTE), "exec")
    exec(codigo, modulo.__dict__)  # noqa: S102 — es el objeto de la herramienta
    return modulo


def _casos_que_caen(modulo) -> list[str]:
    """Corre el banco contra el modulo mutado y devuelve los casos que fallan."""
    from pruebas import test_banco_cancelacion as bc
    from pruebas import test_banco_creacion as bcr
    from reservas.nucleo.modelo import EstadoLeido, Solicitud

    caidos: list[str] = []

    # -- flujo de creacion --------------------------------------------------
    for caso in bcr.CASOS:
        params = caso.espacio_params
        if params is None and caso.espacio in bcr.ESPACIOS and caso.id != "R-03":
            params = bcr.ESPACIOS[caso.espacio]
        estado = EstadoLeido(
            parametros=params, unidad=caso.unidad,
            ocupacion=caso.ocupacion or {}, agenda=caso.agenda or set(),
            cupo_consumido=caso.cupo_consumido,
        )
        solicitud = Solicitud(
            unidad=caso.unidad.id if caso.unidad else "U-999",
            espacio=caso.espacio, inicio=bcr.en(caso.dia_rel, caso.hora),
            n_franjas=caso.n_franjas,
        )
        try:
            v = modulo.evaluar(solicitud, estado, bcr.T0)
            obtenido = v.regla
        except Exception as e:  # noqa: BLE001 — una excepcion tambien es un rojo
            obtenido = f"<{type(e).__name__}>"
        if obtenido != caso.esperado:
            caidos.append(caso.id)

    # -- flujo de cancelacion ----------------------------------------------
    for caso in bc.CANCELACION:
        try:
            v = modulo.evaluar_cancelacion(
                caso.peticion, caso.reserva, bc.ESPACIOS[caso.espacio], caso.evaluado_en
            )
            obtenido = None if v.aceptada else v.regla
        except Exception as e:  # noqa: BLE001
            obtenido = f"<{type(e).__name__}>"
        if obtenido != caso.esperado:
            caidos.append(caso.id)

    # -- flujo de administracion -------------------------------------------
    for ident, peticion, ocupacion, esperado, _ in bc.BLOQUEOS:
        try:
            v = modulo.evaluar_bloqueo(peticion, bc.ESPACIOS.get(peticion.espacio), ocupacion)
            obtenido = None if v.aceptada else v.regla
        except Exception as e:  # noqa: BLE001
            obtenido = f"<{type(e).__name__}>"
        if obtenido != esperado:
            caidos.append(ident)

    return caidos


def _casos_de(regla: str) -> set[str]:
    """Los casos que el banco declara que esta regla debe rechazar.

    Son los que TIENEN que caer al apagarla. Si alguno sobrevive, esa parte de
    la regla no la vigila nadie -aunque otras partes si-.
    """
    from pruebas import test_banco_cancelacion as bc
    from pruebas import test_banco_creacion as bcr

    propios = {c.id for c in bcr.CASOS if c.esperado == regla}
    propios |= {c.id for c in bc.CANCELACION if c.esperado == regla}
    propios |= {b[0] for b in bc.BLOQUEOS if b[3] == regla}
    return propios


def main(argv=None) -> int:
    fuente = FUENTE.read_text(encoding="utf-8")
    lineas = [
        "M4 — mutacion sistematica de las reglas del nucleo",
        "=" * 70,
        "",
        "  Se apaga cada regla y se exige que el banco caiga. Una mutacion que",
        "  sobrevive NO es un exito: significa que ninguna prueba vigila esa",
        "  regla, y rompe el build.",
        "",
    ]

    # Control: sin mutar, el banco entero tiene que estar en verde. Si no lo
    # estuviera, cualquier "rojo" posterior seria ambiguo.
    caidos_control = _casos_que_caen(_compilar(fuente))
    lineas.append(f"  CONTROL sin mutar: {len(caidos_control)} casos caidos "
                  f"(tiene que ser 0){' -> ' + ', '.join(caidos_control) if caidos_control else ''}")
    lineas.append("")
    if caidos_control:
        lineas.append("  El banco NO esta en verde de partida. M4 no puede concluir nada.")
        texto = "\n".join(lineas)
        print(texto)
        return 1

    sobrevivientes: list[str] = []
    for regla in REGLAS:
        try:
            mutante = _compilar(_mutar(fuente, regla))
        except AnclaAusente as e:
            lineas.append(f"  [ERROR ] {regla}  {e}")
            sobrevivientes.append(regla)
            continue
        except SyntaxError as e:
            # Quitar el bloque dejo el modulo sin compilar. Es un rojo valido
            # -la regla es estructural- pero se declara como lo que es.
            lineas.append(f"  [ROJO  ] {regla}  el modulo no compila sin ella: {e.msg}")
            continue

        caidos = set(_casos_que_caen(mutante))
        propios = _casos_de(regla)
        sin_caer = sorted(propios - caidos)

        # "Al menos un caso cae" seria un criterio flojo: una mutacion torpe que
        # rompa el modulo entero lo cumple sin demostrar nada sobre la regla. Lo
        # que se exige es que caigan LOS CASOS DE ESA REGLA -los que el banco
        # declara que ella debe rechazar-. Es la misma idea que gobierna el
        # banco: no basta con que algo falle, tiene que fallar lo que toca.
        if not propios:
            lineas.append(f"  [AVISO ] {regla}  el banco no tiene ningun caso suyo")
            sobrevivientes.append(regla)
        elif sin_caer:
            lineas.append(
                f"  [VERDE ] {regla}  sus casos NO caen: {', '.join(sin_caer)} "
                "— la regla no esta vigilada"
            )
            sobrevivientes.append(regla)
        else:
            extra = len(caidos) - len(propios)
            cola = f" (y {extra} de arrastre)" if extra > 0 else ""
            lineas.append(
                f"  [ROJO  ] {regla}  caen sus {len(propios)}: "
                f"{', '.join(sorted(propios))}{cola}"
            )

    lineas += ["", "=" * 70]
    if sobrevivientes:
        lineas.append(
            f"VEREDICTO M4: FALLA — {len(sobrevivientes)} mutacion(es) sobreviven: "
            f"{', '.join(sobrevivientes)}. El banco no vigila esas reglas."
        )
    else:
        lineas.append(
            f"VEREDICTO M4: PASA — las {len(REGLAS)} reglas del nucleo puro estan "
            "vigiladas. Apagar cualquiera rompe el banco."
        )
    lineas += [
        "",
        "RR-11 no se muta aqui: es inalcanzable desde la lectura y vive en la",
        "condicion de escritura. Su mutacion es H2 (herramientas/sensibilidad.py),",
        "que necesita el motor. Entre las dos, las quince.",
    ]
    texto = "\n".join(lineas)
    print(texto)
    if ESCRIBIR_EVIDENCIA:
        EVIDENCIA.mkdir(exist_ok=True)
        (EVIDENCIA / "m4-mutacion-reglas.txt").write_text(
            texto + "\n", encoding="utf-8"
        )
    return 1 if sobrevivientes else 0


if __name__ == "__main__":
    sys.exit(main())
