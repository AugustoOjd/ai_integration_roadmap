"""Imprime el JSON Schema que el modelo realmente ve, para cada rol.

    uv run python -m app.schema

No llama a la API: `TestModel` reemplaza al modelo, responde con datos válidos
derivados de los tipos y guarda los parámetros del request. Gratis y determinista.

Lo que hay que mirar: `ctx` no aparece en ningún schema, y `refund` directamente
no existe para el rol customer.
"""

import asyncio
import json

from pydantic_ai.models.test import TestModel

from app.agent.deps import Deps, Role
from app.agent.triage import Triage, triage_agent
from app.core.db import SessionFactory, engine


def _dump(titulo: str, data: object) -> None:
    print(f"\n{'─' * 70}\n{titulo}\n{'─' * 70}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


async def _tools_de(role: Role) -> list:
    """Los ToolDefinition que se le arman al modelo para ese rol."""
    # call_tools=[]: por default TestModel ejecuta TODAS las tools con
    # argumentos inventados, y un order_id inventado dispara el ModelRetry de
    # refund hasta agotar los reintentos. Acá sólo queremos leer el request.
    test_model = TestModel(call_tools=[])
    deps = Deps(session_factory=SessionFactory, customer_id="cus_ana", role=role)
    # override sustituye el modelo sin tocar la definición del agente.
    with triage_agent.override(model=test_model):
        await triage_agent.run("ping", deps=deps)
    return list(test_model.last_model_request_parameters.function_tools)


async def main() -> None:
    por_rol = {role: await _tools_de(role) for role in ("customer", "agent")}

    print("\ntools visibles por rol")
    for role, tools in por_rol.items():
        print(f"  {role:<10} {', '.join(t.name for t in tools) or '—'}")

    # El schema completo una sola vez, con el set más grande.
    for tool in por_rol["agent"]:
        _dump(f"tool: {tool.name}", tool.parameters_json_schema)
        print(f"\ndescription: {tool.description}")

    _dump("output_type: Triage", Triage.model_json_schema())

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
