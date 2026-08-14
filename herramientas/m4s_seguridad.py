"""Los dos mutantes de SEGURIDAD: apagar el autorizador y apagar el contador.

`security-agent` los exige para G4. El plan de construccion los coloco en I-6 y
no en I-5, y la razon es simple: en I-5 ninguno de los dos existia todavia. Se
declaran como **extension de M4**, no como pieza nueva `[V — plan §3.1 punto 2]`.

Mismo criterio invertido que M4:

    mutante en ROJO  -> el control existe y hay pruebas que lo vigilan.
    mutante en VERDE -> **nadie lo vigila. Se rompe el build.**

POR QUE ESTOS DOS Y NO OTROS

  Son los dos controles de los que depende que el techo del sistema sea
  calculable. El autorizador decide **quien** actua; el contador, **cuanto**.
  Sin el primero, cualquiera es cualquiera; sin el segundo, `50 x tope` vuelve a
  ser infinito. Que existan no basta: hay que poder demostrar que si se cayeran,
  algo se enteraria.

COMO SE APAGAN

  Sustituyendo la funcion **en memoria**, sobre el modulo ya importado, y
  restaurandola despues en un `finally`. No se toca ningun fichero, por la misma
  razon que en M4: un mutante que se aplica editando el disco es un mutante que
  puede quedarse aplicado.

Uso:  python -m herramientas.m4s_seguridad
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
EVIDENCIA = RAIZ / "evidencia"


@contextlib.contextmanager
def _apagado(modulo, nombre: str, sustituto):
    """Cambia una funcion por otra y la devuelve pase lo que pase."""
    original = getattr(modulo, nombre)
    setattr(modulo, nombre, sustituto)
    try:
        yield
    finally:
        setattr(modulo, nombre, original)


def _correr(*ficheros: str) -> tuple[int, str]:
    """Ejecuta uno o varios ficheros de pruebas y devuelve (codigo, salida)."""
    captura = io.StringIO()
    rutas = [str(RAIZ / "pruebas" / f) for f in ficheros]
    with contextlib.redirect_stdout(captura), contextlib.redirect_stderr(captura):
        codigo = pytest.main(["-q", "--no-header", "-p", "no:cacheprovider", *rutas])
    return int(codigo), captura.getvalue()


def _resumen(salida: str) -> str:
    for linea in reversed(salida.strip().splitlines()):
        if "passed" in linea or "failed" in linea or "error" in linea:
            return linea.strip()
    return "(sin resumen)"


def main() -> int:
    from reservas.seguridad import contador as c
    from reservas.seguridad import prestamo as p

    lineas = [
        "Los dos mutantes de seguridad — extension de M4 (SEC-1, SEC-2)",
        "=" * 70,
        "",
        "  Criterio invertido: un mutante que SOBREVIVE rompe el build, porque",
        "  significa que ningun test vigila ese control.",
        "",
    ]

    # Control: sin mutar, los tres ficheros tienen que estar en verde.
    for fichero in ("test_prestamo.py", "test_contador.py", "test_atender.py"):
        codigo, salida = _correr(fichero)
        lineas.append(f"  CONTROL {fichero:<20} {_resumen(salida)}")
        if codigo != 0:
            lineas.append("")
            lineas.append("  No estan en verde de partida. Los mutantes no concluirian nada.")
            print("\n".join(lineas))
            return 1
    lineas.append("")

    sobrevivientes = []

    # -- Mutante 1 · apagar el autorizador ---------------------------------
    # `verificar` acepta cualquier cosa y devuelve un prestamo de residente.
    # Es el sistema sin autorizador: cualquiera es cualquiera.
    def verificar_apagado(token, clave, ahora):
        return p.Prestamo(unidad="U-101", rol=p.ROL_RESIDENTE, expira=2 ** 31)

    # Se corre tambien `test_atender.py`, y eso es lo que anadio I-6.
    #
    # Con solo `test_prestamo.py`, el mutante prueba que el autorizador
    # FUNCIONA. No prueba que este ENCHUFADO: alguien podria borrar la llamada
    # a `verificar` del caso de uso, dejar el modulo intacto, y este mutante
    # seguiria saliendo rojo con el borde abierto de par en par. Es el patron
    # T-14 —un control que existe y cuya actuacion no esta medida— aplicado al
    # cableado en vez de al control.
    with _apagado(p, "verificar", verificar_apagado), \
         _apagado(p, "exigir_rol", lambda prestamo, rol: None):
        codigo, salida = _correr("test_prestamo.py", "test_atender.py")
    estado = "ROJO " if codigo != 0 else "VERDE"
    lineas.append(f"  [{estado}] apagar el AUTORIZADOR   {_resumen(salida)}")
    if codigo == 0:
        sobrevivientes.append("autorizador")

    # -- Mutante 2 · apagar el contador ------------------------------------
    # `registrar` no cuenta nada y nunca levanta: el techo 50 x tope vuelve a
    # ser infinito sin que ninguna llamada falle.
    with _apagado(c.ContadorIntentos, "registrar", lambda self, u, r, a: None):
        codigo, salida = _correr("test_contador.py", "test_atender.py")
    estado = "ROJO " if codigo != 0 else "VERDE"
    lineas.append(f"  [{estado}] apagar el CONTADOR      {_resumen(salida)}")
    if codigo == 0:
        sobrevivientes.append("contador")

    lineas += ["", "=" * 70]
    if sobrevivientes:
        lineas.append(
            f"VEREDICTO: FALLA — sobreviven {', '.join(sobrevivientes)}. "
            "Apagar ese control no rompe ninguna prueba: nadie lo vigila."
        )
    else:
        lineas.append(
            "VEREDICTO: PASA — apagar el autorizador o el contador rompe las "
            "pruebas. Los dos controles estan vigilados."
        )
    lineas += [
        "",
        "Estos dos NO sustituyen a M4: M4 muta las reglas de negocio del nucleo",
        "y esto muta los controles de seguridad. Son suites distintas porque",
        "protegen cosas distintas.",
    ]
    texto = "\n".join(lineas)
    print(texto)
    EVIDENCIA.mkdir(exist_ok=True)
    (EVIDENCIA / "m4s-mutantes-seguridad.txt").write_text(texto + "\n", encoding="utf-8")
    return 1 if sobrevivientes else 0


if __name__ == "__main__":
    sys.exit(main())
