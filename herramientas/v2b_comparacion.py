"""V-2b — ¿coincide la semantica de error del sustituto local con la del motor real?

Es la otra mitad de V-2a, y vive en I-3 porque **exige los dos motores**: no se
puede comparar con algo que todavia no existe. V-2a comprobo que el sustituto
implementa el mecanismo; V-1 comprobo que el motor real tambien. V-2b comprueba
que **fallan igual**, que es lo que de verdad importa.

Por que importa, dicho sin rodeos:

    Todo el CI corre contra el sustituto (ADR-08). Si el sustituto devolviera
    `ConditionalCheckFailed` donde el motor real devuelve otra cosa, el CI
    seguiria verde mientras el sistema desplegado atribuye la regla equivocada.
    Las pruebas no comprobarian el sistema: comprobarian el sustituto.

Y por eso la practica heredada n.o 1 se aplica aqui entera: una prueba negativa
afirma la CLASE del fallo, no solo que hubo fallo. Si las dos clases no
coinciden entre motores, el CI pierde la capacidad de afirmar la clase.

METODO, y sus limites declarados:

    Se comparan los resultados REGISTRADOS de las dos corridas, leidos de sus
    ficheros de evidencia. No se re-ejecuta nada. Es comparacion de dos
    mediciones, no una medicion nueva.

    Eso significa que V-2b hereda la vigencia de las dos evidencias: si una es
    vieja, la comparacion es vieja. El fichero lo declara.

Uso:  python -m herramientas.v2b_comparacion
"""

from __future__ import annotations

import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
EVIDENCIA = RAIZ / "evidencia"
LOCAL = EVIDENCIA / "v2a-sustituto-local.txt"
REAL = EVIDENCIA / "v1-motor-real.txt"

# Comprobaciones cuyo resultado DEBE coincidir entre motores para que el CI
# pueda afirmar la clase del fallo. Las demas se comparan igual, pero divergir
# en ellas no invalida el CI: se declara y se sigue.
BLOQUEANTES = {"V2a-1", "V2a-4", "V2a-5", "V2a-8"}

# Comprobaciones donde se ESPERA divergencia, con su motivo. Que difieran no es
# un hallazgo: seria un hallazgo que coincidieran.
DIVERGENCIA_ESPERADA = {
    "V2a-9": (
        "El sustituto serializa por construccion y puede no producir nunca "
        "TransactionConflict. Si el real si lo produce, el reintento de ADR-04 "
        "solo se ejercita de verdad contra el motor real."
    ),
    "V2a-10": (
        "El sustituto ignora la capacidad aprovisionada; el real tiene reserva "
        "de rafaga. Medir la tasa sostenida es V-8, no esto."
    ),
    "V2a-11": (
        "Activar el ttl no es borrar. El sustituto no borra por expiracion; "
        "cuando borra el real es [NV] y pertenece a V-8."
    ),
}

_CABECERA = re.compile(r"^\s*\[(OK|!!|\?\?)\]\s+(V2a-\d+)\s+(.*)$")
_RESULTADO = re.compile(r"^\s*->\s*(.*)$")


def leer(fichero: pathlib.Path) -> dict[str, tuple[str, str, str]]:
    """{id: (marca, pregunta, resultado)} a partir de un fichero de evidencia."""
    if not fichero.exists():
        raise SystemExit(
            f"Falta {fichero}. V-2b compara dos corridas y necesita las dos.\n"
            "  sustituto local:  python -m herramientas.v2a_sonda\n"
            "  motor real:       RESERVAS_MOTOR_REAL=1 python -m herramientas.v2a_sonda"
        )
    hallazgos: dict[str, tuple[str, str, str]] = {}
    actual: str | None = None
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        cabecera = _CABECERA.match(linea)
        if cabecera:
            marca, ident, pregunta = cabecera.groups()
            hallazgos[ident] = (marca, pregunta.strip(), "")
            actual = ident
            continue
        resultado = _RESULTADO.match(linea)
        if resultado and actual:
            marca, pregunta, _ = hallazgos[actual]
            hallazgos[actual] = (marca, pregunta, resultado.group(1).strip())
            actual = None
    return hallazgos


def _codigos(texto: str) -> set[str]:
    """Los codigos de error nombrados en un resultado.

    La comparacion se hace sobre ESTO y no sobre el texto entero, a proposito.
    Comparar cadenas completas marcaria como divergencia cualquier diferencia de
    redaccion o de orden de un diccionario -que es *medir la cosa parecida*-.
    Lo que V-2b afirma es que la CLASE del fallo coincide, y la clase es el
    codigo.
    """
    return set(re.findall(r"\b[A-Z][A-Za-z]+(?:Exception|Failed|Conflict)\b", texto))


def comparar() -> tuple[str, bool]:
    local = leer(LOCAL)
    real = leer(REAL)
    lineas = [
        "V-2b — semantica de error: sustituto local vs motor real",
        "=" * 70,
        "",
        f"  local: {LOCAL.name}",
        f"  real:  {REAL.name}",
        "",
        "  Se comparan los CODIGOS de error de cada comprobacion, no el texto",
        "  entero: lo que se afirma es que la clase del fallo coincide.",
        "",
    ]

    solo_local = sorted(set(local) - set(real))
    solo_real = sorted(set(real) - set(local))
    if solo_local or solo_real:
        lineas.append(f"  AVISO comprobaciones no pareadas: "
                      f"solo local {solo_local} · solo real {solo_real}")
        lineas.append("")

    divergencias_bloqueantes = 0
    for ident in sorted(set(local) & set(real), key=lambda s: int(s.split("-")[1])):
        _, pregunta, res_local = local[ident]
        _, _, res_real = real[ident]
        cl, cr = _codigos(res_local), _codigos(res_real)

        if cl == cr:
            estado = "IGUAL"
        elif ident in DIVERGENCIA_ESPERADA:
            estado = "DIFIERE (esperado)"
        elif ident in BLOQUEANTES:
            estado = "DIFIERE — BLOQUEANTE"
            divergencias_bloqueantes += 1
        else:
            estado = "DIFIERE (no bloqueante)"

        lineas.append(f"  [{estado}] {ident}  {pregunta}")
        if cl == cr:
            lineas.append(f"        codigos en ambos: {sorted(cl) or ['(ninguno)']}")
        else:
            lineas.append(f"        local: {sorted(cl) or ['(ninguno)']}")
            lineas.append(f"        real:  {sorted(cr) or ['(ninguno)']}")
            if ident in DIVERGENCIA_ESPERADA:
                lineas.append(f"        motivo: {DIVERGENCIA_ESPERADA[ident]}")
        lineas.append("")

    lineas.append("=" * 70)
    if divergencias_bloqueantes:
        lineas.append(
            f"VEREDICTO V-2b: NEGATIVA — {divergencias_bloqueantes} divergencia(s) "
            "en comprobaciones bloqueantes. El CI corre contra el sustituto y "
            "ya NO puede afirmar la clase del fallo del sistema desplegado. "
            "Se declara en el README; no se disimula (ADR-08)."
        )
    else:
        lineas.append(
            "VEREDICTO V-2b: POSITIVA — la clase del fallo coincide en todas las "
            "comprobaciones bloqueantes. El CI contra el sustituto conserva su "
            "capacidad de afirmar por que se rechazo, no solo que se rechazo."
        )
    lineas.append("")
    lineas.append(
        "Limite declarado: esto compara dos mediciones registradas, no las "
        "re-ejecuta. Hereda la vigencia de los dos ficheros de evidencia."
    )
    return "\n".join(lineas), divergencias_bloqueantes == 0


def main() -> int:
    texto, ok = comparar()
    print(texto)
    destino = EVIDENCIA / "v2b-comparacion-motores.txt"
    destino.write_text(texto + "\n", encoding="utf-8")
    print(f"\n[evidencia] {destino}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
