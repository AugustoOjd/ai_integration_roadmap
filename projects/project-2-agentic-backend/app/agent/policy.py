"""Qué tools necesitan que un humano diga que sí.

Archivo separado y no una constante en `agent.py` porque lo que contiene no es
técnica, es política de negocio: la misma tool —`send_email`— necesita aprobación
en un asistente interno y no la necesita en un bot de notificaciones.

El criterio: una tool necesita aprobación si es irreversible o visible para
afuera.

    leer            → no    (get_my_orders, get_order, calculate)
    escribir        → sí    (cancel_order, refund)
    salir al mundo  → sí    (send_email, post_tweet)

La pregunta que resuelve la duda: si el modelo se equivoca acá, ¿se puede
deshacer sin que nadie se entere? Si la respuesta es no, va a la lista.
"""

from datetime import timedelta

# frozenset y no set: una política que otro módulo puede editar en runtime no es
# una política.
#
# Los nombres son strings y no referencias a las funciones: la política se
# escribe en el vocabulario del protocolo (el `name` que pide el modelo), así que
# puede mudarse a la base o a un archivo de config sin tocar código.
REQUIEREN_APROBACION: frozenset[str] = frozenset(
    {
        "cancel_order",
        "send_email",
        "refund",
    }
)


# Cuánto vive un pedido de aprobación antes de vencer.
#
# Sin vencimiento, alguien aprueba el martes un "cancelá el pedido 991" que el
# agente propuso el viernes, cuando el pedido ya se entregó.
TTL_APROBACION = timedelta(hours=24)


# Las tools cuya ejecución deja una marca en el mundo.
#
# Dos conjuntos y no uno, aunque acá tengan los mismos elementos, porque
# responden preguntas distintas:
#
#   REQUIEREN_APROBACION  ¿hace falta que un humano diga que sí?
#   TIENEN_EFECTOS        ¿correrla dos veces hace daño dos veces?
#
# Se separan en cuanto aparece una tool que escribe pero no necesita permiso —un
# contador, un evento de auditoría, un webhook interno—: tiene efectos y no pide
# aprobación. Y la que no tiene efectos nunca necesita el candado: pagar una fila
# de idempotencia por un `calculate` es gasto puro.
TIENEN_EFECTOS: frozenset[str] = frozenset(
    {
        "cancel_order",
        "send_email",
        "refund",
    }
)


def tiene_efectos(tool_name: str) -> bool:
    """¿Esta tool pasa por el candado de idempotencia?

    La pregunta que resuelve la duda: si el worker se cae y esto corre de nuevo,
    ¿alguien se entera? Un `SELECT` no; un `UPDATE`, un mail o un cobro sí.
    """
    return tool_name in TIENEN_EFECTOS


def requiere_aprobacion(tool_name: str) -> bool:
    """¿Esta tool pausa el loop?

    Una función y no un `in` suelto en el agente, para que exista un solo lugar
    donde cambiar el criterio cuando deje de ser una lista fija (por ejemplo,
    "también los montos mayores a $1000").
    """
    return tool_name in REQUIEREN_APROBACION
