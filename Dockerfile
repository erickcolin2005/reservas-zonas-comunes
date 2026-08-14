# El sistema entero en una imagen: motor + funcion + pagina.
#
# Es lo que sirve la DEMO PUBLICA, y vive fuera de AWS a proposito. La razon esta
# en §6.1 del README y es economica, no tecnica: el instrumento es una superficie
# de consumo abierta y anunciada a desconocidos, y con la cuenta de AWS en Plan
# de Pago y cero creditos, dejarla viva y desatendida alli es el riesgo que este
# proyecto describio como no acotable con codigo.
#
# ---------------------------------------------------------------------------
# DOS PROCESOS EN UN CONTENEDOR, Y POR QUE AQUI SI
# ---------------------------------------------------------------------------
# Meter dos procesos en una imagen suele ser mala idea. Aqui se hace porque los
# alojamientos gratuitos dan UN contenedor, y separar el motor exigiria un plan
# de pago — que es exactamente lo que esta imagen existe para no necesitar.
#
# La consecuencia se asume y se declara: si el motor muere, el contenedor no se
# entera. Para una demostracion cuyo peor caso es "se reinicia y se resiembra",
# es un precio razonable; para produccion de verdad no lo seria.
#
# ---------------------------------------------------------------------------
# EL MOTOR ES EL SUSTITUTO LOCAL, Y ESO NO SE DISIMULA
# ---------------------------------------------------------------------------
# Aqui corre DynamoDB Local, no DynamoDB. **Serializa mas que el motor real**, y
# ese sesgo va en una sola direccion: no puede producir menos dobles reservas que
# el real. Por eso la afirmacion central del proyecto NO se apoya en esta imagen
# — se apoya en las corridas contra DynamoDB de verdad, que estan en
# `evidencia/k-motor-real.txt`. Esto sirve para que puedas intentarlo tu.
#
#   docker build -t reservas .
#   docker run -p 8080:8080 -e RESERVAS_ORIGEN_PERMITIDO=http://localhost:8080 reservas

# El motor sale de la MISMA imagen que usan el CI y las pruebas locales, no de
# una descarga aparte.
#
# El primer intento fue un `ADD` del tarball oficial con la version en el nombre,
# **y esa URL con fecha da 404**: AWS solo publica `..._latest.tar.gz` en esa
# ruta. Habria quedado un Dockerfile con un comentario diciendo "version fijada"
# encima de una descarga que no lo esta — la clase de texto falso que este
# proyecto persigue. Copiandolo de aqui, la version se fija donde se puede fijar
# de verdad: en la etiqueta de la imagen.
FROM amazon/dynamodb-local:latest AS motor

FROM python:3.13-slim

# El JRE es para el motor. `--no-install-recommends` y el borrado de listas
# mantienen la imagen dentro de lo que un alojamiento gratuito admite.
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jre-headless curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=motor /home/dynamodblocal/DynamoDBLocal.jar /opt/motor/
COPY --from=motor /home/dynamodblocal/DynamoDBLocal_lib /opt/motor/DynamoDBLocal_lib

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY reservas/ ./reservas/
COPY herramientas/ ./herramientas/
COPY frontend/ ./frontend/
COPY arranque.sh .
RUN chmod +x arranque.sh

# Sin privilegios. El proceso no necesita ser root para escuchar en 8080.
RUN useradd --create-home --uid 10001 reservas && chown -R reservas /app /opt/motor
USER reservas

ENV RESERVAS_ENDPOINT=http://127.0.0.1:8000 \
    PORT=8080

EXPOSE 8080

# La sonda pega a /salud, que NO toca el motor: una sonda que leyera la tabla
# cada pocos segundos convertiria la vigilancia en consumo.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/salud" || exit 1

CMD ["./arranque.sh"]
