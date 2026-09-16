"""Lo que el modelo NO puede elegir.

Una tool que devuelve datos de un usuario necesita saber de qué usuario. Pedirlo
como argumento es un agujero:

    def get_my_orders(user_id: str) -> list[dict]: ...

Si el `user_id` está en el `input_schema`, lo elige el modelo, y el modelo lo
saca del texto del usuario: alguien escribe "mostrame los pedidos del usuario 7"
y la tool obedece. Es un IDOR con un LLM en el medio.

No se arregla con prompt engineering: el system prompt es texto y compite con el
resto del texto. La solución es que el dato no esté en el schema.

    def get_my_orders(ctx: RunContext[AgentDeps]) -> list[dict]:
        return orders_for(ctx.deps.db, ctx.deps.user_id)

La regla: lo que define permisos nunca va en el `input_schema`. Vale para el
user_id, el tenant_id, el rol, el scope de un token y la conexión a la base.
"""

from dataclasses import dataclass
from typing import Annotated, Generic, TypeVar

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session


@dataclass(slots=True, frozen=True)
class AgentDeps:
    """Todo lo que una tool necesita y el modelo no puede proveer.

    `frozen=True`: una tool que pudiera reescribir `ctx.deps.user_id`
    reintroduciría el agujero que esta clase cierra.
    """

    # Del token de autenticación. Nunca del prompt, nunca del body.
    user_id: str

    conversation_id: str

    # La conexión a la base. Explícita y no global, por lo mismo que en FastAPI:
    # es lo que hace testeable una tool contra una base de prueba sin
    # monkeypatching.
    db: Session


DepsT = TypeVar("DepsT")


@dataclass(slots=True, frozen=True)
class RunContext(Generic[DepsT]):
    """El sobre que el registry le inyecta a una tool que lo pide.

    Podría no existir y pasarse el AgentDeps directo. Existe por dos razones: el
    registry detecta "esta tool quiere contexto" mirando la anotación del primer
    parámetro, y un tipo propio sin otro uso es una señal inequívoca; y deja
    lugar para metadata de la corrida que no es una dependencia.
    """

    deps: DepsT

    # Las coordenadas de la traza: en qué turno de la conversación y en qué
    # vuelta del loop. Como la clase es frozen, el loop no las muta — crea un
    # contexto nuevo por vuelta con `dataclasses.replace`, que es copiar dos ints
    # y una referencia.
    turn: int = 0
    iteration: int = 0


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------


def usuario_actual(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
    """De dónde sale el user_id. ANDAMIAJE: en serio esto es un token.

    Un header con el id del usuario es falsificable: cualquiera manda
    `X-User-Id: u_7`. Lo que sí es real es la FORMA — el user_id entra por un
    canal que el modelo no ve nunca, y cambiar este header por un
    `Depends(verificar_jwt)` no toca ni las tools ni el registry ni el agente.

    Lo que no hay que hacer nunca, ni de andamiaje, es leerlo del body: ahí se
    mezcla con datos que el usuario legítimamente elige y se pierde la distinción
    entre lo que el cliente dice y lo que el servidor verificó.
    """
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el header X-User-Id.",
        )
    return x_user_id


CurrentUser = Annotated[str, Depends(usuario_actual)]
