"""Las tools del agente.

Importar este paquete es lo que las registra: el decorador `@registry.tool`
corre al importar cada módulo. Si una tool no aparece nunca en los requests, lo
primero a chequear es si su módulo se importó.

Los imports de abajo parecen no usarse y por eso llevan `noqa: F401`. No son
decorativos: son el efecto de lado que llena el registry. Borrar uno hace
desaparecer esa tool del sistema sin ningún error.

El ORDEN de estos imports es el orden de las tools en cada request, y conviene
que sea estable: las tools se serializan antes que el system y los mensajes,
así que reordenarlas invalida la caché de prompts entera.
"""

from app.tools import calculator, clock, orders, search  # noqa: F401
from app.tools.registry import registry

__all__ = ["registry"]
