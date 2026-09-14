"""Fase 8 — toda conversación larga se rompe sola.

Haiku 4.5 tiene 200K de ventana, no 1M. Una sesión larga llega — y con el
historial completo viajando en cada vuelta y en cada turno (Fase 2), llega antes
de lo que parece.

Las tres salidas, de peor a mejor:

    Ventana deslizante   tira los mensajes viejos       el agente "olvida" de golpe
    Resumen              pide resumir y reemplaza       una llamada extra, pierde detalle
    Recorte selectivo    vacía los tool_result viejos   barato y suele alcanzar

El recorte selectivo gana casi siempre porque los `tool_result` son lo más
pesado y lo menos necesario: el contenido de una búsqueda de hace diez turnos ya
está resumido en el texto que el modelo escribió después.

---

**La trampa**, que es la Fase 1 volviendo: no se puede borrar un `tool_use` sin
borrar su `tool_result`, ni al revés. Vienen de a pares.

La forma en que este módulo la evita es estructural, no por cuidado: el recorte
selectivo **nunca borra bloques**. Vacía el CONTENIDO de un `tool_result` y deja
el bloque con su `tool_use_id` intacto. Un par no se puede romper si nadie saca
una de sus mitades.

Recién cuando eso no alcanza se tiran mensajes enteros — y ahí sí hay que cortar
en el lugar correcto, que es el comienzo de un turno.

---

**Segunda decisión: se recorta lo que se MANDA, no lo que se guarda.** La base
conserva el historial completo, porque lo necesitás para el log de la Fase 4 y
para auditar. Lo que se recorta es la lista que se le pasa a `create`. Recortar
la base sería perder la auditoría para ahorrar tokens.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from anthropic.types import MessageParam

logger = logging.getLogger(__name__)

# Lo que queda en lugar del resultado de una tool vieja.
#
# Dice explícitamente que hubo algo y que se sacó. Un string vacío sería peor:
# el modelo lo leería como "la tool no devolvió nada", que es una afirmación
# falsa sobre el pasado y lo puede llevar a reintentarla.
PLACEHOLDER = "[resultado recortado para ahorrar contexto]"

# Cuántos mensajes del final quedan intactos pase lo que pase.
#
# Los `tool_result` recientes SÍ importan: son los datos con los que el modelo
# está razonando ahora mismo. Vaciarlos es lo mismo que no haber llamado a la
# tool.
CONSERVAR_RECIENTES = 6

Medidor = Callable[[list[MessageParam]], Awaitable[int]]


def _es_inicio_de_turno(mensaje: MessageParam) -> bool:
    """¿Este mensaje abre un turno nuevo?

    Un turno empieza con un mensaje del usuario que es texto de verdad — no uno
    de esos mensajes `user` que en realidad son `tool_result` (contraintuitivo,
    pero el protocolo los manda con ese rol).

    Cortar el historial JUSTO acá es lo único seguro: todo lo anterior son
    turnos completos, con sus pares cerrados. Cortar en cualquier otro lado
    parte un turno al medio y deja huérfanos.
    """
    if mensaje["role"] != "user":
        return False

    contenido = mensaje["content"]
    if isinstance(contenido, str):
        return True
    return not any(bloque.get("type") == "tool_result" for bloque in contenido)


def _vaciar_tool_results(
    messages: list[MessageParam], conservar: int = CONSERVAR_RECIENTES
) -> list[MessageParam]:
    """Reemplaza el contenido de los `tool_result` viejos por el placeholder.

    No borra NADA: cada `tool_result` sigue existiendo, con su `tool_use_id`. Por
    eso esta operación no puede romper un par, ni aunque se la llame mil veces.

    Copia en vez de mutar. Los `messages` que entran son los mismos objetos que
    después se persisten en `nuevos`: mutarlos acá guardaría el placeholder en
    la base, que es exactamente lo que este módulo NO tiene que hacer.
    """
    corte = max(0, len(messages) - conservar)
    recortados: list[MessageParam] = []

    for indice, mensaje in enumerate(messages):
        contenido = mensaje["content"]

        if indice >= corte or isinstance(contenido, str):
            recortados.append(mensaje)
            continue

        bloques: list[dict[str, Any]] = []
        for bloque in contenido:
            if bloque.get("type") == "tool_result" and bloque.get("content") != PLACEHOLDER:
                bloques.append({**bloque, "content": PLACEHOLDER})
            else:
                bloques.append(bloque)

        recortados.append({"role": mensaje["role"], "content": bloques})

    return recortados


def _tirar_turno_mas_viejo(messages: list[MessageParam]) -> list[MessageParam] | None:
    """Saca el turno más viejo entero. Devuelve `None` si ya no se puede.

    Busca el comienzo del SEGUNDO turno y corta ahí. Nunca corta en el medio,
    así que nunca separa un `tool_use` de su `tool_result`.

    Devuelve `None` cuando queda un solo turno: recortar más sería mandarle al
    modelo un historial que empieza con un `tool_result` sin su pedido, o sea un
    request inválido. Llegado ese punto el problema ya no es el contexto — es un
    turno que por sí solo no entra en la ventana.
    """
    inicios = [i for i, mensaje in enumerate(messages) if _es_inicio_de_turno(mensaje)]

    if len(inicios) < 2:
        return None

    return messages[inicios[1] :]


async def ajustar(
    messages: list[MessageParam],
    *,
    limite: int,
    medir: Medidor,
) -> tuple[list[MessageParam], int]:
    """Devuelve un historial que entra en `limite`, y cuánto mide.

    `medir` se inyecta en vez de llamar a `count_tokens` directamente: así esta
    función es pura respecto del mundo exterior y los tests pueden usar un
    medidor de mentira, determinístico y gratis. Es la misma idea que inyectar
    dependencias en las tools, un nivel más arriba.

    La escalera es de menos a más destructivo:

        1. ¿Ya entra? No se toca nada.
        2. Vaciar los `tool_result` viejos. Barato y suele alcanzar.
        3. Tirar turnos completos desde el principio, de a uno.

    Si ni así entra, devuelve lo mínimo que pudo dejar. No levanta: quien llama
    (el loop) ya tiene su propio manejo para "no entra", y que esta función
    decidiera abortar le sacaría esa decisión.
    """
    tokens = await medir(messages)
    if tokens <= limite:
        return messages, tokens

    # ---- Paso 2: vaciar los tool_result viejos ---------------------------
    recortados = _vaciar_tool_results(messages)
    if recortados != messages:
        tokens = await medir(recortados)
        logger.info("contexto: tool_results vaciados, quedó en %d tokens", tokens)
        if tokens <= limite:
            return recortados, tokens

    # ---- Paso 3: tirar turnos enteros ------------------------------------
    while tokens > limite:
        mas_corto = _tirar_turno_mas_viejo(recortados)
        if mas_corto is None:
            # Un solo turno y sigue sin entrar. Devolvemos lo que hay: el loop
            # lo va a rechazar por presupuesto, que es la respuesta honesta.
            logger.warning("contexto: no se puede recortar más, quedan %d tokens", tokens)
            return recortados, tokens

        recortados = mas_corto
        tokens = await medir(recortados)
        logger.info("contexto: turno viejo descartado, quedó en %d tokens", tokens)

    return recortados, tokens


def pares_intactos(messages: list[MessageParam]) -> bool:
    """¿Todo `tool_use` tiene su `tool_result` y viceversa?

    Es el invariante del mini entero, escrito como función para poder afirmarlo
    en los tests. Es la misma consulta que está en `QUERIES.md`, en Python.
    """
    pedidos: set[str] = set()
    resultados: set[str] = set()

    for mensaje in messages:
        contenido = mensaje["content"]
        if isinstance(contenido, str):
            continue
        for bloque in contenido:
            if bloque.get("type") == "tool_use":
                pedidos.add(bloque["id"])
            elif bloque.get("type") == "tool_result":
                resultados.add(bloque["tool_use_id"])

    return pedidos == resultados
