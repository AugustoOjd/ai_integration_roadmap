"""Fase 4 — El registry: una sola fuente de verdad por tool.

El problema que resuelve está a la vista en `app/toolbox.py`: la misma
información escrita en tres lugares que nada mantiene sincronizados (el schema
JSON, la firma de la función, y el `if` del dispatch). Tocás uno, te olvidás de
otro, y explota en runtime cuando al modelo se le ocurra usar esa tool.

Acá la fuente de verdad es UNA: la función Python. De ella se derivan las tres
partes que el modelo necesita.

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
from typing import Any

from anthropic.types import ToolParam
from pydantic import BaseModel, ConfigDict, ValidationError, create_model


class ToolError(Exception):
    """Algo salió mal con una tool, de forma esperable.

    Clase base a propósito: al agente no le importa CUÁL de los fallos fue, le
    importa que es un fallo que se le puede contar al modelo en vez de matar la
    corrida. El texto de estas excepciones va a terminar leído POR EL MODELO,
    así que se escribe pensando en que lo entienda y se corrija — no para un log.
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
    # El modelo de Pydantic generado a partir de la firma. Es a la vez el
    # generador del JSON Schema y el validador de lo que llega. Que sean la
    # misma cosa es el punto entero del registry: no puede haber desacuerdo
    # entre lo que prometés y lo que aceptás.
    input_model: type[BaseModel]
    func: Callable[..., Any]

    def to_param(self, *, strict: bool) -> ToolParam:
        """La forma que espera la API."""
        schema = self.input_model.model_json_schema()

        # Pydantic mete un "title" en el modelo y en cada propiedad, derivado
        # del nombre del campo ("Expression"). No aporta nada que la
        # `description` no diga mejor, y son tokens que pagás en CADA request
        # del loop. Fuera.
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)

        param: ToolParam = {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }
        if strict:
            # `strict` hace que la API garantice que el `input` que te llega
            # valida contra el schema: sin campos de más, sin campos
            # requeridos faltando, con los tipos correctos.
            #
            # Exige que el schema tenga `additionalProperties: false` (nos lo
            # da el `extra="forbid"` de abajo) y `required`.
            #
            # Que te lo garantice la API no te exime de validar vos: seguimos
            # llamando a `model_validate` en `execute()`. El input de una tool
            # nace de texto de un usuario y termina ejecutando código tuyo; esa
            # cadena se valida en tu proceso, no por confianza en un tercero.
            param["strict"] = True
        return param


class ToolRegistry:
    """Registra funciones y las expone como tools.

    No es más que un diccionario con dos conversiones alrededor: de función
    Python a JSON Schema (para salir), y de dict JSON a argumentos validados
    (para entrar).
    """

    def __init__(self, *, strict: bool = True) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._strict = strict

    def tool(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorador. Registra la función y la devuelve intacta.

        Devolverla sin envolver es deliberado: `calculate` sigue siendo una
        función normal, llamable y testeable directo, sin pasar por el modelo
        ni por el registry. Los tests de la Fase 9 dependen de eso.
        """
        description = inspect.cleandoc(func.__doc__ or "")
        if not description:
            # Una tool sin docstring es una tool sin descripción, y una tool
            # sin descripción es una que el modelo no va a saber cuándo usar.
            # Mejor fallar al importar que descubrirlo por una tool que "nunca
            # se llama" — que es el síntoma más difícil de diagnosticar.
            raise ValueError(f"la tool {func.__name__!r} no tiene docstring")

        self._tools[func.__name__] = RegisteredTool(
            name=func.__name__,
            description=description,
            input_model=_input_model_for(func),
            func=func,
        )
        return func

    def to_params(self) -> list[ToolParam]:
        """Las tools para mandar en el request.

        El orden es el de registro y es estable. Importa para la caché de
        prompts: las tools se serializan antes que todo lo demás, así que una
        lista que cambia de orden entre requests invalida la caché entera.
        """
        return [tool.to_param(strict=self._strict) for tool in self._tools.values()]

    def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        """Valida y ejecuta. Devuelve un string, que es lo que pide tool_result."""
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(
                f"la tool {name!r} no existe. Disponibles: {sorted(self._tools)}"
            )

        try:
            # Acá muere el `**tool_input` a ciegas del toolbox. Antes, un campo
            # de más que el modelo inventara reventaba con un TypeError
            # incomprensible; ahora Pydantic lo rechaza con un mensaje que dice
            # exactamente qué campo sobra o falta, y ese mensaje se le puede
            # devolver al modelo para que se corrija.
            validated = tool.input_model.model_validate(tool_input)
        except ValidationError as exc:
            raise InvalidToolInputError(
                f"argumentos inválidos para {name!r}: {exc.errors(include_url=False)}"
            ) from exc

        output = tool.func(**validated.model_dump())

        # Lo que devuelve una tool entra al contexto del modelo, y el contexto
        # es texto. Un float se convierte con `str`; un dict o una lista van
        # como JSON, que el modelo lee bien y sin ambigüedad.
        if isinstance(output, str):
            return output
        return json.dumps(output, ensure_ascii=False, default=str)


def _input_model_for(func: Callable[..., Any]) -> type[BaseModel]:
    """Construye el modelo de Pydantic a partir de la firma de la función.

    `create_model` es el constructor dinámico de Pydantic: hace en runtime lo
    mismo que escribir `class CalculateInput(BaseModel): expression: str`.

    Las descripciones por campo salen de `Annotated[str, Field(description=...)]`
    en la firma, así que también viven en un solo lugar.
    """
    fields: dict[str, Any] = {}

    for param_name, param in inspect.signature(func).parameters.items():
        if param.annotation is inspect.Parameter.empty:
            # Sin anotación no hay tipo, sin tipo no hay schema, y sin schema
            # el modelo no sabe qué mandarte. Se corta al importar.
            raise TypeError(f"{func.__name__}: el parámetro {param_name!r} no tiene tipo")

        # `...` (Ellipsis) es como Pydantic escribe "requerido". Si el parámetro
        # tiene default en Python, ese default pasa a ser el del schema y el
        # campo deja de estar en `required` — la semántica se mantiene alineada
        # sola entre la función y el contrato.
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (param.annotation, default)

    return create_model(  # type: ignore[call-overload]
        f"{func.__name__}_input",
        # `extra="forbid"` se traduce a `additionalProperties: false` en el
        # JSON Schema, que es lo que `strict` exige. Y del lado de la
        # validación hace que un campo inventado por el modelo sea un error
        # explícito en vez de un valor que se ignora en silencio.
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


# La instancia única del proceso.
#
# Vive acá, junto a la clase, y no en `app/tools/__init__.py`, por una razón de
# imports: cada módulo de tool hace `from app.tools.registry import registry`
# para decorar sus funciones. Si la instancia viviera en el `__init__`, ese
# `__init__` tendría que importar los módulos de tools y los módulos de tools
# tendrían que importar el `__init__` — un ciclo que funciona o no según el
# orden, que es la peor clase de bug de imports.
registry = ToolRegistry()
