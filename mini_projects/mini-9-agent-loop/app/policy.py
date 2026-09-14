"""Fase 5 — qué tools necesitan que un humano diga que sí.

En el mini 8, "el modelo pide, vos ejecutás" era una frase: ejecutabas todo lo
que pedía. Acá se vuelve código.

Este archivo existe separado, y no como una constante perdida en `agent.py`,
porque lo que contiene **no es técnica, es política de negocio**. Ningún
framework puede decidirlo por vos: no es una propiedad del código, es una del
dominio. La misma tool —`send_email`— necesita aprobación en un asistente
interno y no la necesita en un bot de notificaciones.

El criterio para la lista: una tool necesita aprobación si es **irreversible o
visible para afuera**.

    leer            → no          (get_my_orders, get_order, calculate)
    escribir        → sí          (cancel_order, refund)
    salir al mundo  → sí          (send_email, post_tweet)

La pregunta que resuelve la duda: *si el modelo se equivoca acá, ¿se puede
deshacer sin que nadie se entere?* Si la respuesta es no, va a la lista.
"""

from datetime import timedelta

# Las tools que pausan el loop.
#
# `frozenset` y no `set`: es una constante de configuración, y que sea inmutable
# hace que nadie pueda "agregarle una excepción temporal" en runtime desde otro
# módulo. Una política que se puede editar en caliente no es una política.
#
# Nótese que los nombres son strings y no referencias a las funciones. Es a
# propósito: la política se escribe en el vocabulario del PROTOCOLO (el `name`
# que el modelo pide), no en el de Python. Así se puede mover a la base o a un
# archivo de configuración sin tocar código, que es hacia dónde va esto en
# cuanto haya más de un cliente con reglas distintas.
REQUIEREN_APROBACION: frozenset[str] = frozenset(
    {
        "cancel_order",
        "send_email",
        "refund",
    }
)


# Cuánto vive un pedido de aprobación antes de vencer.
#
# Un pendiente sin vencimiento es una acción que puede ejecutarse en cualquier
# momento del futuro. Alguien aprueba el martes un "cancelá el pedido 991" que
# el agente propuso el viernes anterior, cuando el contexto era otro y el pedido
# ya se entregó. El TTL convierte eso en un error explícito.
TTL_APROBACION = timedelta(hours=24)


def requiere_aprobacion(tool_name: str) -> bool:
    """¿Esta tool pausa el loop?

    Es una función y no un `in` suelto en el agente para que exista UN lugar
    donde cambiar el criterio. El día que la regla deje de ser una lista fija
    —por ejemplo, "también requieren aprobación los montos mayores a $1000"—
    se cambia acá y el loop no se entera.
    """
    return tool_name in REQUIEREN_APROBACION
