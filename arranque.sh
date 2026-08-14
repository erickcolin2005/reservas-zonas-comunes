#!/bin/sh
# Arranca el motor y despues el servidor. En este orden y en el mismo contenedor.
set -eu

# -Xmx256m no es una cifra al azar: los alojamientos gratuitos dan 512 MB, y sin
# tope la JVM se queda con lo que quiera y el servidor de Python muere sin
# explicacion. El sintoma -"el contenedor se reinicia solo"- no se parece nada a
# la causa.
java -Xmx256m -Djava.library.path=/opt/motor/DynamoDBLocal_lib \
     -jar /opt/motor/DynamoDBLocal.jar -inMemory -sharedDb -port 8000 &
MOTOR=$!

# Si el motor se cae, el contenedor entero se va con el. Sin esto quedaria un
# servidor vivo respondiendo 500 a todo, que es peor que estar caido: el
# alojamiento lo veria sano y no lo reiniciaria.
trap 'kill -TERM "$MOTOR" 2>/dev/null || true' INT TERM

# `--sembrar` en cada arranque, y es deliberado: el motor va EN MEMORIA, asi que
# reiniciar limpia los datos. Para una demostracion publica eso es una ventaja —
# las reservas que dejen los visitantes no se acumulan hasta que no quede ni una
# franja libre y la demo deje de poder demostrar nada.
exec python -m herramientas.servidor \
     --host 0.0.0.0 \
     --puerto "${PORT:-8080}" \
     --sembrar
