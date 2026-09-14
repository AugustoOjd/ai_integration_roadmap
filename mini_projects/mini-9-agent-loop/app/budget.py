"""Fase 7 — `max_iterations` no es un presupuesto.

El mini 8 acotaba el loop en VUELTAS. Eso protege contra el loop infinito: un
modelo confundido que pide la misma tool para siempre. No protege contra el
gasto, que es otro problema:

    5 iteraciones con un historial de 2 KB    → centavos
    5 iteraciones con un historial de 100 KB  → no

Y desde la Fase 2 los historiales crecen solos, porque el historial completo
viaja en CADA vuelta y en CADA turno. Hacen falta los dos topes, y miden cosas
distintas.

El tope real se cuenta en tokens y se chequea **antes** de mandar. Contar
después sirve para la factura, no para evitarla.
"""

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolParam, Usage
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ChatSession, SessionStatus
from app.repository import get_session


class BudgetExceededError(RuntimeError):
    """La sesión se quedó sin presupuesto. Se traduce a 402.

    Lleva los números adentro para que la respuesta pueda decir cuánto falta.
    Un "sin presupuesto" a secas obliga a quien lo recibe a adivinar si le
    faltan 100 tokens o 100.000.
    """

    def __init__(self, *, necesarios: int, disponibles: int) -> None:
        self.necesarios = necesarios
        self.disponibles = disponibles
        super().__init__(
            f"el turno necesita ~{necesarios} tokens de entrada y quedan {disponibles}"
        )


async def estimar(
    client: AsyncAnthropic,
    messages: list[MessageParam],
    tools: list[ToolParam],
) -> int:
    """Cuántos tokens de ENTRADA va a costar este request.

    `count_tokens` es un endpoint aparte de la API, y es **gratis**. Eso es lo
    que lo hace útil acá: preguntar cuánto va a costar no puede costar.

    Dos condiciones para que el número sirva:

      1. Hay que pasarle EXACTAMENTE lo mismo que a `messages.create`: los
         mismos `messages`, las mismas `tools` y el mismo `system` si lo
         hubiera. Las definiciones de tools son tokens de entrada en cada
         vuelta; dejarlas afuera de la cuenta subestima siempre, y subestimar un
         límite es no tener límite.
      2. Sólo estima la ENTRADA. Lo que el modelo va a generar no se puede saber
         de antemano — por eso el único control sobre el output es
         `max_tokens`, y por eso el gasto de salida se suma DESPUÉS, con el
         `usage` de la respuesta.

    Este mini no usa `system`, y por eso no aparece acá. Si algún día se agrega,
    esta llamada tiene que recibirlo también o la estimación empieza a mentir.
    """
    cuenta = await client.messages.count_tokens(
        model=settings.ANTHROPIC_MODEL,
        messages=messages,
        tools=tools,
    )
    return cuenta.input_tokens


def verificar(sesion: ChatSession, *, estimado: int, gastado_en_vuelo: int = 0) -> None:
    """¿Entra este request en lo que queda? Si no, levanta.

    `gastado_en_vuelo` son los tokens que este turno YA consumió pero que
    todavía no están en la fila: el turno se persiste recién al final, así que
    en la vuelta 3 la base sigue diciendo lo que valía antes de empezar. Sin
    este término, un turno de muchas vueltas podría pasarse del presupuesto
    porque cada chequeo mira un contador viejo.
    """
    disponibles = sesion.budget_tokens - sesion.input_tokens_used - gastado_en_vuelo

    if estimado > disponibles:
        raise BudgetExceededError(necesarios=estimado, disponibles=max(0, disponibles))


async def marcar_agotada(
    db: AsyncSession, session_id: str, *, input_tokens: int, output_tokens: int
) -> None:
    """Cobra lo que este turno alcanzó a gastar y deja la sesión agotada.

    Se llama en el camino de fallo, donde `save_turn` nunca va a correr. Sin
    esto, un turno que se pasa del presupuesto en la vuelta 3 saldría GRATIS:
    el modelo trabajó dos vueltas, el historial no se guarda, y nadie registra
    ese gasto. El agujero no es teórico — es el caso en el que más se gasta.

    El estado `exhausted` no es un error transitorio: reintentar no lo arregla.
    Hace falta subir el presupuesto o abrir otra sesión, y por eso la sesión
    deja de aceptar mensajes en vez de fallar una y otra vez.
    """
    sesion = await get_session(db, session_id, for_update=True)
    sesion.input_tokens_used += input_tokens
    sesion.output_tokens_used += output_tokens
    sesion.status = SessionStatus.EXHAUSTED
    await db.commit()


def costo_usd(usage: Usage) -> float:
    """De tokens a dinero.

    Input y output se convierten por SEPARADO porque tienen precios distintos
    (con Haiku 4.5, $1 y $5 por millón). Ésa es la razón por la que la tabla
    guarda dos contadores y no uno: un `tokens_used` único no se puede convertir
    a plata sin inventar un promedio.

    Los precios salen de config y no están hardcodeados acá: cambian, y cuando
    cambian querés poder corregir el número sin un deploy.
    """
    entrada = usage.input_tokens / 1_000_000 * settings.PRECIO_INPUT_USD_POR_MTOK
    salida = usage.output_tokens / 1_000_000 * settings.PRECIO_OUTPUT_USD_POR_MTOK
    return round(entrada + salida, 6)
