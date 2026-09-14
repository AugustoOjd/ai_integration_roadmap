"""Fase 3 — lo que el modelo NO puede elegir.

Ésta es la pregunta 48 del `CHECK_LEARNING.md` del mini 8, y acá se responde.

Una tool que devuelve datos de un usuario necesita saber de qué usuario. La
forma obvia es pedirlo como argumento:

    def get_my_orders(user_id: str) -> list[dict]: ...

Y es un agujero. Si el `user_id` está en el `input_schema`, **lo elige el
modelo** — y el modelo lo saca del texto del usuario. Alguien escribe "mostrame
los pedidos del usuario 7" y tu tool obedece, porque desde su punto de vista
recibió un argumento válido. Es un IDOR con un LLM en el medio.

Y no se arregla con prompt engineering. El system prompt no es una frontera de
seguridad: es texto, compite con el resto del texto, y el usuario también
escribe texto. Un "nunca uses un user_id que venga del mensaje" aguanta hasta
que alguien encuentre la forma de pedirlo distinto.

La solución no es validar mejor: es que el dato **no esté en el schema**. El
modelo elige QUÉ hacer; el contexto autenticado define SOBRE QUÉ.

    def get_my_orders(ctx: RunContext[AgentDeps]) -> list[dict]:
        return await orders_for(ctx.deps.db, ctx.deps.user_id)

Ese `ctx` viaja por afuera del modelo: el registry lo inyecta al ejecutar, y
nunca aparece en el `input_schema` que la API ve.

La regla que queda: **lo que define permisos nunca va en el `input_schema`.**
Vale para el `user_id`, para el `tenant_id`, para el rol, para el scope de un
token, y para la conexión a la base.
"""

from dataclasses import dataclass
from typing import Annotated, Generic, TypeVar

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True, frozen=True)
class AgentDeps:
    """Todo lo que una tool necesita y el modelo no puede proveer.

    `frozen=True` no es estética: una tool que pudiera reescribir
    `ctx.deps.user_id` reintroduciría exactamente el agujero que esta clase
    cierra. Congelado, el dueño de la corrida queda fijado en el momento en que
    se autenticó el request.
    """

    # Del token de autenticación. NUNCA del prompt, nunca del body.
    user_id: str

    # La sesión de conversación en curso. Una tool podría querer saber en qué
    # conversación está (para loguear, o para la aprobación de la Fase 5).
    session_id: str

    # La conexión a la base, para las tools que consultan datos. Va por acá y no
    # como global por el mismo motivo que en FastAPI: es estado por-request, y
    # pasarlo explícito es lo que hace que una tool sea testeable con una base
    # de prueba sin monkeypatching.
    db: AsyncSession


# El tipo de las dependencias es un parámetro genérico, igual que en Pydantic AI.
# Acá siempre es `AgentDeps`, pero dejarlo abierto documenta la intención: el
# contexto es un sobre, y lo que importa es lo que va adentro.
DepsT = TypeVar("DepsT")


@dataclass(slots=True, frozen=True)
class RunContext(Generic[DepsT]):
    """El sobre que el registry le inyecta a una tool que lo pide.

    Es una clase de una sola línea, y podría no existir: se le podría pasar el
    `AgentDeps` directo. Existe por dos razones prácticas.

    La primera es de detección: el registry reconoce "esta tool quiere contexto"
    mirando la anotación del primer parámetro. Un tipo propio y sin otro uso es
    una señal inequívoca; `AgentDeps` a secas se confundiría con un argumento
    normal.

    La segunda es de futuro, y ya se cobró: la Fase 4 necesita saber en qué
    turno y en qué vuelta del loop está para dejar la traza, y eso no es una
    "dependencia" — es metadata de la corrida. Entró abajo sin tocar ni una tool
    ni el `AgentDeps`.

    Es el mismo patrón —y el mismo nombre— que usa Pydantic AI. Acá está escrito
    a mano porque el loop es nuestro, pero la idea es prestada y vale conocerla
    con su nombre.
    """

    deps: DepsT

    # ---- Metadata de la corrida (Fase 4) ---------------------------------
    #
    # Son las coordenadas que ubican un paso de la traza: en qué turno de la
    # conversación, y en qué vuelta del loop dentro de ese turno.
    #
    # Como la clase es `frozen`, el loop no las muta: crea un contexto nuevo por
    # vuelta con `dataclasses.replace(ctx, iteration=i)`. Suena caro y no lo es
    # —es copiar dos ints y una referencia— y a cambio una tool nunca puede ver
    # un contexto a medio actualizar.
    turn: int = 0
    iteration: int = 0


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------


async def usuario_actual(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
    """De dónde sale el `user_id`. ANDAMIAJE: en serio esto es un token.

    Un header con el id del usuario es, obviamente, falsificable: cualquiera
    manda `X-User-Id: u_7` y se hace pasar por otro. Está así porque la
    autenticación no es el tema de este mini y un JWT completo sería ruido.

    Lo que SÍ es real y es el punto de la fase es la FORMA: el `user_id` entra
    por un canal que el cliente no controla libremente y que el modelo no ve
    nunca. Cambiar este header por un `Depends(verificar_jwt)` es reemplazar
    esta función y nada más — ni las tools ni el registry ni el agente se
    enteran. Esa es la prueba de que la frontera está bien puesta.

    Lo que NO hay que hacer nunca, ni siquiera de andamiaje, es dejarlo en el
    body del request: ahí se mezcla con datos que el usuario legítimamente
    elige, y la distinción entre "lo que el cliente dice" y "lo que el servidor
    verificó" se pierde de vista.
    """
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el header X-User-Id.",
        )
    return x_user_id


# El alias para las rutas, igual que `Db` en `db.py`.
CurrentUser = Annotated[str, Depends(usuario_actual)]
