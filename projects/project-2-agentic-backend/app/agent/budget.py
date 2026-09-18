"""`max_iterations` no es un presupuesto.

Un tope en vueltas protege contra el loop infinito: un modelo confundido que pide
la misma tool para siempre. No protege contra el gasto, que es otro problema:

    5 iteraciones con un historial de 2 KB    → centavos
    5 iteraciones con un historial de 100 KB  → no

Y los historiales crecen solos, porque el historial completo viaja en cada vuelta
y en cada turno. Hacen falta los dos topes y miden cosas distintas.

El tope real se cuenta en tokens y se chequea antes de mandar: contar después
sirve para la factura, no para evitarla.
"""

from datetime import UTC, datetime

from anthropic import Anthropic
from anthropic.types import MessageParam, ToolParam, Usage
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.agent.repository import get_conversation
from app.core.config import settings
from app.core.models import Conversation, ConversationStatus, UserBudget


class BudgetExceededError(RuntimeError):
    """La conversación se quedó sin presupuesto. Se traduce a 402.

    Lleva los números adentro: un "sin presupuesto" a secas obliga a quien lo
    recibe a adivinar si le faltan 100 tokens o 100.000.
    """

    def __init__(self, *, necesarios: int, disponibles: int) -> None:
        self.necesarios = necesarios
        self.disponibles = disponibles
        super().__init__(
            f"el turno necesita ~{necesarios} tokens de entrada y quedan {disponibles}"
        )


def estimar(
    client: Anthropic,
    messages: list[MessageParam],
    tools: list[ToolParam],
) -> int:
    """Cuántos tokens de ENTRADA va a costar este request.

    `count_tokens` es un endpoint aparte y es gratis: preguntar cuánto va a
    costar no puede costar.

    Dos condiciones para que el número sirva:

      1. Hay que pasarle exactamente lo mismo que a `messages.create`: los mismos
         messages, las mismas tools y el mismo system si lo hubiera. Las
         definiciones de tools son tokens de entrada en cada vuelta; dejarlas
         afuera subestima siempre, y subestimar un límite es no tener límite.
      2. Sólo estima la entrada. Lo que el modelo va a generar no se puede saber
         de antemano: el único control sobre el output es `max_tokens`, y ese
         gasto se suma después con el `usage` de la respuesta.

    Este proyecto no usa `system`. Si algún día se agrega, esta llamada tiene que
    recibirlo también o la estimación empieza a mentir.
    """
    cuenta = client.messages.count_tokens(
        model=settings.ANTHROPIC_MODEL,
        messages=messages,
        tools=tools,
    )
    return cuenta.input_tokens


def verificar(conversacion: Conversation, *, estimado: int, gastado_en_vuelo: int = 0) -> None:
    """¿Entra este request en lo que queda? Si no, levanta.

    `gastado_en_vuelo` son los tokens que este turno ya consumió pero que todavía
    no están en la fila: el turno se persiste recién al final, así que en la
    vuelta 3 la base sigue diciendo lo que valía antes de empezar. Sin ese
    término, un turno de muchas vueltas se pasa del presupuesto porque cada
    chequeo mira un contador viejo.
    """
    disponibles = (
        conversacion.budget_tokens - conversacion.input_tokens_used - gastado_en_vuelo
    )

    if estimado > disponibles:
        raise BudgetExceededError(necesarios=estimado, disponibles=max(0, disponibles))


def marcar_agotada(
    db: Session, conversation_id: str, *, input_tokens: int, output_tokens: int
) -> None:
    """Cobra lo que este turno alcanzó a gastar y deja la conversación agotada.

    Se llama en el camino de fallo, donde `save_turn` nunca va a correr. Sin
    esto, un turno que se pasa del presupuesto en la vuelta 3 saldría gratis: el
    modelo trabajó dos vueltas, el historial no se guarda y nadie registra ese
    gasto. Es el caso en el que más se gasta.

    `exhausted` no es transitorio: reintentar no lo arregla, hace falta subir el
    presupuesto o abrir otra conversación. Por eso la conversación deja de aceptar mensajes
    en vez de fallar una y otra vez.
    """
    conversacion = get_conversation(db, conversation_id, for_update=True)
    conversacion.input_tokens_used += input_tokens
    conversacion.output_tokens_used += output_tokens
    conversacion.status = ConversationStatus.EXHAUSTED
    db.commit()


def costo_usd(usage: Usage) -> float:
    """De tokens a dinero.

    Input y output se convierten por separado porque tienen precios distintos.
    Ésa es la razón por la que la tabla guarda dos contadores: uno solo no se
    puede convertir a plata sin inventar un promedio.
    """
    entrada = usage.input_tokens / 1_000_000 * settings.PRECIO_INPUT_USD_POR_MTOK
    salida = usage.output_tokens / 1_000_000 * settings.PRECIO_OUTPUT_USD_POR_MTOK
    return round(entrada + salida, 6)


# ---------------------------------------------------------------------------
# Presupuesto por usuario: reservar y liquidar
# ---------------------------------------------------------------------------
#
# El de la conversación se puede leer y después escribir porque un solo turno la
# toca por vez (el FOR UPDATE de `save_turn` lo garantiza). Éste no: el mismo
# usuario puede tener cuatro tareas corriendo en cuatro workers, y las cuatro
# chequean contra la misma fila.
#
# Leer, decidir y escribir por separado sería un lost update de manual: los
# cuatro leen "gastó 9.000 de 10.000", los cuatro concluyen que entran, los
# cuatro llaman al modelo.
#
# Y hay un segundo problema que el de la conversación no tiene: **el gasto se
# conoce después**. `count_tokens` estima el input; el output se sabe recién con
# la respuesta. De ahí el patrón de dos tiempos:
#
#     reservar(estimado)  ──> llamar al modelo ──> liquidar(real)
#                         └──> si algo falla ──> liberar(estimado)


def _ventana(momento: datetime | None = None) -> datetime:
    """El inicio de la ventana actual, truncado a la hora."""
    ahora = momento or datetime.now(UTC)
    return ahora.replace(minute=0, second=0, microsecond=0)


def reservar(db: Session, user_id: str, estimado: int) -> bool:
    """Aparta `estimado` tokens si entran. Devuelve si prendió.

    Una sola sentencia: el UPSERT inserta la fila de la ventana si no existía, y
    si existía suma a `tokens_reserved` **sólo si el total sigue bajo el límite**.
    Esa condición adentro del `DO UPDATE` es lo que cierra la carrera — la base
    arbitra, y el que llega segundo ve cero filas afectadas.

    Es el mismo compare-and-swap que las transiciones de estado, sobre números en
    vez de sobre un enum.
    """
    limite = settings.PRESUPUESTO_USUARIO_TOKENS

    if estimado > limite:
        # Un solo request que no entra ni en una ventana vacía. Se corta acá para
        # que el UPSERT no cree una fila con una reserva imposible.
        return False

    ventana = _ventana()

    insercion = pg_insert(UserBudget).values(
        user_id=user_id,
        window_start=ventana,
        tokens_limit=limite,
        tokens_reserved=estimado,
        tokens_used=0,
    )
    sentencia = insercion.on_conflict_do_update(
        index_elements=["user_id", "window_start"],
        set_={"tokens_reserved": UserBudget.tokens_reserved + estimado},
        # El `where` va sobre el DO UPDATE: si no se cumple, la fila existente no
        # se toca y `rowcount` queda en 0.
        where=(
            UserBudget.tokens_reserved + UserBudget.tokens_used + estimado
            <= UserBudget.tokens_limit
        ),
    )
    resultado = db.execute(sentencia)
    db.commit()
    return resultado.rowcount == 1


def liquidar(db: Session, user_id: str, reservado: int, real: int) -> None:
    """Cierra la reserva con lo que se gastó de verdad.

    Suelta lo apartado y suma lo real. Las dos cosas en una sentencia, porque si
    se hicieran en dos y el proceso muriera en el medio quedaría un presupuesto
    contando mal para siempre.
    """
    db.execute(
        update(UserBudget)
        .where(UserBudget.user_id == user_id, UserBudget.window_start == _ventana())
        .values(
            tokens_reserved=UserBudget.tokens_reserved - reservado,
            tokens_used=UserBudget.tokens_used + real,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()


def liberar(db: Session, user_id: str, reservado: int) -> None:
    """Devuelve una reserva que no se llegó a usar.

    Se llama cuando la llamada al modelo falla: lo apartado no se gastó y dejarlo
    reservado le come presupuesto al usuario por algo que nunca ocurrió.
    """
    db.execute(
        update(UserBudget)
        .where(UserBudget.user_id == user_id, UserBudget.window_start == _ventana())
        .values(tokens_reserved=UserBudget.tokens_reserved - reservado)
        .execution_options(synchronize_session=False)
    )
    db.commit()


def estado_usuario(db: Session, user_id: str) -> dict[str, int | str]:
    """Cuánto le queda al usuario en esta ventana."""
    ventana = _ventana()
    fila = db.get(UserBudget, (user_id, ventana))
    limite = fila.tokens_limit if fila else settings.PRESUPUESTO_USUARIO_TOKENS
    usados = fila.tokens_used if fila else 0
    reservados = fila.tokens_reserved if fila else 0
    return {
        "window_start": ventana.isoformat(),
        "tokens_limit": limite,
        "tokens_used": usados,
        "tokens_reserved": reservados,
        "tokens_remaining": max(0, limite - usados - reservados),
    }
