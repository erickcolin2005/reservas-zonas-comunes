"""Reservas de zonas comunes — el incremento I-1.

Lo que hay aqui: el modelo, la canonizacion de la clave, la escritura
condicional, la transaccion de confirmacion y los datos sinteticos. Es decir, el
mecanismo que hace imposible la doble reserva y la prueba que lo demuestra.

Lo que NO hay, y esta declarado en `docs/alcance-i1.md`: API expuesta, frontend,
dispensador de identidades, contador de tasa, IaC, prueba de carga, mutacion
sobre las 15 reglas, y las 15 reglas completas.
"""

__all__ = []
