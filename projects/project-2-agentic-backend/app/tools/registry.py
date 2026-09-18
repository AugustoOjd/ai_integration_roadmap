"""El registry: una sola fuente de verdad por tool.

Sin él, la misma información vive en tres lugares que nada mantiene
sincronizados: el schema JSON, la firma de la función y el `if` del dispatch.

Acá la fuente de verdad es la función Python, y de ella se derivan las tres
partes que el modelo necesita:

    def calculate(expression: str) -> float:
        '''Evalúa una expresión aritmética...'''
         │         │                    │
         │         │                    └─ description  (el docstring)
         │         └─ input_schema  (los tipos, vía Pydantic)
         └─ name  (el nombre de la función)
"""

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_origin

from anthropic.types import ToolParam
from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from app.agent.deps import RunContext


class ToolError(Exception):
    """Un fallo esperable de una tool.

    Clase base a propósito: al agente no le importa cuál de los fallos fue, le
    importa que se le puede contar al modelo en vez de matar la corrida. El texto
    de estas excepciones lo lee el modelo, así que se escribe para que se corrija
    — no para un log.
    """


class UnknownToolError(ToolError):
    """El modelo pidió una tool que no existe. Pasa: los modelos alucinan nombres."""


class InvalidToolInputError(ToolError):
    """El modelo mandó argumentos que no validan contra el schema."""


@dataclass(slots=True, frozen=True)
class RegisteredTool:
    """Una tool ya procesada: lo que el modelo ve, más lo que vos ejecutás."""

    name: str
    description: str

    # El modelo de Pydantic generado desde la firma. Genera el JSON Schema y
    # valida lo que llega: que sean el mismo objeto es el punto del registry —
    # no puede haber desacuerdo entre lo que prometés y lo que aceptás.
    input_model: type[BaseModel]
    func: Callable[..., Any]

    # Si la firma empieza con un RunContext, la tool recibe el contexto
    # autenticado al ejecutarse y ese parámetro no aparece en el input_schema.
    wants_context: bool = False

    def to_param(self, *, strict: bool) -> ToolParam:
        """La forma que espera la API."""
        schema = self.input_model.model_json_schema()

        # Pydantic mete un "title" en el modelo y en cada propiedad, derivado del
        # nombre del campo. No aporta nada sobre la description y son tokens que
        # pagás en cada request del loop.
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)

        param: ToolParam = {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }
        if strict:
            # La API garantiza que el input que te llega valida contra el schema.
            # Exige additionalProperties: false (lo da el extra="forbid" de
            # abajo) y required.
            #
            # No exime de validar: seguimos llamando a model_validate en
            # execute(). El input de una tool nace de texto de un usuario y
            # termina ejecutando código tuyo; esa cadena se valida en tu proceso.
            param["strict"] = True
        return param


class ToolRegistry:
    """Registra funciones y las expone como tools.

    Un diccionario con dos conversiones alrededor: de función Python a JSON
    Schema (para salir), y de dict JSON a argumentos validados (para entrar).
    """

    def __init__(self, *, strict: bool = True) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._strict = strict

    def tool(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorador. Registra la función y la devuelve intacta.

        Sin envolver a propósito: `calculate` sigue siendo una función normal,
        llamable y testeable directo, sin pasar por el modelo ni por el registry.
        """
        description = inspect.cleandoc(func.__doc__ or "")
        if not description:
            # Una tool sin descripción es una que el modelo no va a saber cuándo
            # usar. Mejor fallar al importar que descubrirlo por una tool que
            # "nunca se llama", que es el síntoma más difícil de diagnosticar.
            raise ValueError(f"la tool {func.__name__!r} no tiene docstring")

        input_model, wants_context = _input_model_for(func)

        self._tools[func.__name__] = RegisteredTool(
            name=func.__name__,
            description=description,
            input_model=input_model,
            func=func,
            wants_context=wants_context,
        )
        return func

    def to_params(self) -> list[ToolParam]:
        """Las tools para mandar en el request.

        El orden es el de registro y es estable. Importa para la caché de
        prompts: las tools se serializan antes que todo lo demás, así que una
        lista que cambia de orden invalida la caché entera.
        """
        return [tool.to_param(strict=self._strict) for tool in self._tools.values()]

    def execute(
        self,
        name: str,
        tool_input: dict[str, Any],
        ctx: RunContext[Any] | None = None,
    ) -> str:
        """Valida y ejecuta. Devuelve un string, que es lo que pide tool_result."""
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(
                f"la tool {name!r} no existe. Disponibles: {sorted(self._tools)}"
            )

        if tool.wants_context and ctx is None:
            # Bug de programación, no del modelo. La alternativa —ejecutarla con
            # un contexto vacío— sería consultar datos sin saber de quién son.
            raise RuntimeError(f"la tool {name!r} necesita contexto y no se le pasó ninguno")

        try:
            # Acá muere el `**tool_input` a ciegas: un campo de más que el modelo
            # invente no revienta con un TypeError incomprensible, Pydantic dice
            # exactamente qué sobra o falta y ese mensaje se le puede devolver.
            validated = tool.input_model.model_validate(tool_input)
        except ValidationError as exc:
            raise InvalidToolInputError(
                f"argumentos inválidos para {name!r}: {exc.errors(include_url=False)}"
            ) from exc

        # El contexto se antepone como primer argumento posicional, fuera de los
        # argumentos validados: lo de la izquierda lo puso el servidor, lo de la
        # derecha lo pidió el modelo.
        args = (ctx,) if tool.wants_context else ()
        kwargs = validated.model_dump()

        def correr() -> str:
            output = tool.func(*args, **kwargs)
            # Lo que devuelve una tool entra al contexto del modelo, y el contexto
            # es texto. Un dict o una lista van como JSON, que el modelo lee sin
            # ambigüedad.
            #
            # La serialización va ACÁ adentro y no afuera para que lo que se
            # guarde en el candado de idempotencia sea exactamente el mismo string
            # que se le devuelve al modelo. Guardar el dict y serializar después
            # dejaría dos caminos que pueden producir texto distinto.
            if isinstance(output, str):
                return output
            return json.dumps(output, ensure_ascii=False, default=str)

        # Imports locales: `idempotency` importa `ToolError` de este módulo, así
        # que arriba serían un ciclo.
        from app.agent.policy import tiene_efectos
        from app.tools.idempotency import ejecutar_una_sola_vez

        if not tiene_efectos(name):
            # Leer no deja marca: pagar una fila de candado por un `calculate`
            # sería gasto puro.
            return correr()

        if ctx is None:
            raise RuntimeError(f"la tool {name!r} tiene efectos y necesita contexto")

        return ejecutar_una_sola_vez(ctx, name, correr)


def _es_contexto(annotation: Any) -> bool:
    """¿Esta anotación es un RunContext?

    Contempla las dos formas de escribirlo: `RunContext` a secas y
    `RunContext[AgentDeps]`. La segunda no es la clase sino un alias genérico, y
    `get_origin` devuelve la clase de atrás.
    """
    return annotation is RunContext or get_origin(annotation) is RunContext


def _input_model_for(func: Callable[..., Any]) -> tuple[type[BaseModel], bool]:
    """Construye el modelo de Pydantic desde la firma de la función.

    Devuelve además si la tool pide contexto, porque es la misma pasada por la
    firma la que lo descubre.

    `create_model` hace en runtime lo mismo que escribir
    `class CalculateInput(BaseModel): expression: str`. Las descripciones por
    campo salen de `Annotated[str, Field(description=...)]`, así que también
    viven en un solo lugar.
    """
    fields: dict[str, Any] = {}
    wants_context = False

    for posicion, (param_name, param) in enumerate(inspect.signature(func).parameters.items()):
        # Acá el user_id desaparece del contrato: este parámetro se saltea, no
        # genera campo, no llega al JSON Schema, y el modelo nunca se entera de
        # que la función lo recibe.
        #
        # Sólo en la primera posición, porque execute() lo pasa posicionalmente y
        # en el medio desalinearía los argumentos. Falla al importar y no en la
        # primera llamada del modelo a esa tool.
        if _es_contexto(param.annotation):
            if posicion != 0:
                raise TypeError(
                    f"{func.__name__}: el RunContext tiene que ser el primer parámetro"
                )
            wants_context = True
            continue

        if param.annotation is inspect.Parameter.empty:
            # Sin tipo no hay schema, y sin schema el modelo no sabe qué mandar.
            raise TypeError(f"{func.__name__}: el parámetro {param_name!r} no tiene tipo")

        # `...` es como Pydantic escribe "requerido". Un parámetro con default en
        # Python pasa a tener default en el schema y sale de `required`: la
        # semántica se mantiene alineada sola.
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (param.annotation, default)

    modelo = create_model(  # type: ignore[call-overload]
        f"{func.__name__}_input",
        # extra="forbid" se traduce a additionalProperties: false, que es lo que
        # strict exige. Y del lado de la validación hace que un campo inventado
        # por el modelo sea un error explícito en vez de ignorarse en silencio.
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    return modelo, wants_context


# La instancia única del proceso.
#
# Vive acá y no en app/tools/__init__.py por un ciclo de imports: cada módulo de
# tool hace `from app.tools.registry import registry` para decorar sus funciones,
# así que si la instancia viviera en el __init__, ese __init__ importaría las
# tools y las tools importarían el __init__.
registry = ToolRegistry()
