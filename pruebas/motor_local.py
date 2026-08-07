"""Arranque del sustituto local. Nunca un doble en memoria.

Regla 5 del plan de construccion, y no es negociable:

    las pruebas de concurrencia se ejecutan contra el sustituto local en
    contenedor o contra el motor real, JAMAS contra un doble escrito por
    nosotros: pasaria K-01 por construccion y seria el fallo fatal n.o 1 en su
    forma mas pura.

Un doble en memoria que nosotros escribieramos tendria la garantia que
quisieramos darle. Probar contra el es probar nuestra propia suposicion.

Dos modos:
  - `RESERVAS_ENDPOINT` definido -> se usa ese extremo y no se arranca nada.
    Es lo que hace el CI, que levanta el sustituto como contenedor de servicio.
  - sin definir -> se arranca `amazon/dynamodb-local` con docker y se para al
    terminar. Es lo que hace una maquina de desarrollo.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

IMAGEN = "amazon/dynamodb-local:latest"
NOMBRE = "reservas-ddb-local-pruebas"
PUERTO = 8000


class MotorNoDisponible(Exception):
    """No hay sustituto local y no se puede arrancar uno.

    Se levanta en vez de saltarse las pruebas en silencio: un CI que omite las
    pruebas de concurrencia y sale en verde es peor que uno en rojo.
    """


def responde(endpoint: str, espera: float = 1.5) -> bool:
    try:
        urllib.request.urlopen(endpoint, timeout=espera)
        return True
    except urllib.error.HTTPError:
        # Responde HTTP aunque sea con error: el proceso esta vivo.
        return True
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
        return False


def esperar(endpoint: str, segundos: float = 60.0) -> None:
    limite = time.time() + segundos
    while time.time() < limite:
        if responde(endpoint):
            return
        time.sleep(0.5)
    raise MotorNoDisponible(f"{endpoint} no respondio en {segundos:.0f} s")


class SustitutoLocal:
    """Ciclo de vida del contenedor. Idempotente."""

    def __init__(self) -> None:
        self.endpoint = os.environ.get("RESERVAS_ENDPOINT")
        self.gestionado_por_nosotros = False

    def arrancar(self) -> str:
        if self.endpoint:
            esperar(self.endpoint)
            return self.endpoint

        self.endpoint = f"http://localhost:{PUERTO}"
        if responde(self.endpoint):
            # Ya hay uno levantado. No lo tocamos ni lo paramos despues.
            return self.endpoint

        if shutil.which("docker") is None:
            raise MotorNoDisponible(
                "no hay docker y no hay sustituto local en "
                f"{self.endpoint}. Levanta uno con:\n"
                f"  docker run -d -p {PUERTO}:{PUERTO} --name {NOMBRE} {IMAGEN} "
                "-jar DynamoDBLocal.jar -inMemory -sharedDb\n"
                "o exporta RESERVAS_ENDPOINT apuntando al que tengas."
            )

        subprocess.run(["docker", "rm", "-f", NOMBRE], capture_output=True, check=False)
        arranque = subprocess.run(
            [
                "docker", "run", "-d", "--name", NOMBRE,
                "-p", f"{PUERTO}:{PUERTO}", IMAGEN,
                # -inMemory: sin fichero en disco, sin estado entre corridas.
                # -sharedDb: una sola base para todas las credenciales, que aqui
                #            son de relleno.
                "-jar", "DynamoDBLocal.jar", "-inMemory", "-sharedDb",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if arranque.returncode != 0:
            raise MotorNoDisponible(
                f"docker run fallo: {arranque.stderr.strip() or arranque.stdout.strip()}"
            )
        self.gestionado_por_nosotros = True
        esperar(self.endpoint)
        return self.endpoint

    def parar(self) -> None:
        if self.gestionado_por_nosotros:
            subprocess.run(
                ["docker", "rm", "-f", NOMBRE], capture_output=True, check=False
            )
            self.gestionado_por_nosotros = False
