"""Un run contra el modelo real, con aprobación y límites.

    uv run python -m app.cli "mi paquete nunca llegó y me cobraron dos veces"
    uv run python -m app.cli --customer cus_bruno --role agent "devolvéme la plata"
    uv run python -m app.cli --conversation conv_xxx "¿y el otro cobro?"
"""

import argparse
import asyncio

from pydantic_ai import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.usage import UsageLimits

from app.agent.deps import Deps
from app.agent.history import cargar, guardar
from app.agent.triage import Triage, triage_agent
from app.core.db import SessionFactory, engine
from app.core.telemetry import configurar


def _traza(mensajes: list[ModelMessage]) -> None:
    """Las llamadas a tools y sus resultados, en orden."""
    for msg in mensajes:
        for part in msg.parts:
            match part:
                case ToolCallPart():
                    print(f"  → {part.tool_name}({part.args})")
                case RetryPromptPart():
                    # El error que volvió al modelo como un turno más.
                    print(f"  ↺ retry [{part.tool_name}]: {part.content}")
                case ToolReturnPart():
                    print(f"  ← {part.tool_name}: {part.content}")
                case TextPart() if part.content.strip():
                    print(f"  · {part.content.strip()[:120]}")


def _decidir(pendientes: DeferredToolRequests, modo: str) -> DeferredToolResults:
    """Convierte las llamadas pendientes en una decisión por cada una.

    `approvals` se indexa por tool_call_id: es lo que aparea la decisión con la
    llamada exacta, no con la tool.
    """
    results = DeferredToolResults()

    for call in pendientes.approvals:
        print(f"\n  ⏸  {call.tool_name}({call.args})")

        match modo:
            case "all":
                respuesta = "s"
            case "none":
                respuesta = "n"
            case _:
                respuesta = input("     ¿aprobar? [s/N] ").strip().lower()

        if respuesta.startswith("s"):
            results.approvals[call.tool_call_id] = ToolApproved()
            print("     aprobado")
        else:
            # El mensaje del rechazo vuelve al modelo, que puede explicárselo al
            # cliente o intentar otra cosa. No es un error del run.
            results.approvals[call.tool_call_id] = ToolDenied(
                message="Un humano rechazó el reembolso. Explicá que se escaló."
            )
            print("     rechazado")

    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="Clasifica un ticket de soporte.")
    parser.add_argument("mensaje", help="El ticket, tal como lo escribió el cliente.")
    parser.add_argument(
        "--customer",
        default="cus_ana",
        help="Quién pregunta. Sale de tu auth, no del mensaje.",
    )
    parser.add_argument(
        "--role",
        default="customer",
        choices=["customer", "agent"],
        help="customer no ve la tool de reembolso; agent sí.",
    )
    parser.add_argument(
        "--conversation",
        help="Continúa un hilo ya guardado. Sin esto se crea uno nuevo.",
    )
    parser.add_argument(
        "--approve",
        default="ask",
        choices=["ask", "all", "none"],
        help="Qué hacer con las tools que requieren aprobación.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        help="Tope de llamadas al modelo en este run.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Muestra cada tool call, cada resultado y cada retry.",
    )
    args = parser.parse_args()

    # Antes del primer run: instrumentar parchea las clases del framework.
    configurar()

    # La fábrica viaja adentro de Deps; cada tool abre y cierra la suya.
    deps = Deps(
        session_factory=SessionFactory, customer_id=args.customer, role=args.role
    )
    limites = UsageLimits(request_limit=args.max_requests) if args.max_requests else None

    historial = None
    if args.conversation:
        async with SessionFactory() as session:
            historial = await cargar(session, args.conversation)

    try:
        # message_history= es todo lo que hace falta para continuar: el proceso
        # que empezó el hilo ya no existe.
        result = await triage_agent.run(
            args.mensaje, deps=deps, message_history=historial, usage_limits=limites
        )

        # Un run que llega a una tool gatillada TERMINA acá, con las llamadas
        # pendientes como valor. El while porque el run siguiente puede volver a
        # frenarse en otra tool.
        while isinstance(result.output, DeferredToolRequests):
            results = _decidir(result.output, args.approve)
            result = await triage_agent.run(
                message_history=result.all_messages(),
                deferred_tool_results=results,
                deps=deps,
                usage_limits=limites,
            )
    except UsageLimitExceeded as e:
        # El tope corta el run; lo hecho hasta acá ya está hecho.
        print(f"\nlímite alcanzado: {e}")
        await engine.dispose()
        return

    async with SessionFactory() as session:
        conv_id = await guardar(
            session, args.conversation, args.customer, result.all_messages_json()
        )

    if args.trace:
        print()
        _traza(result.all_messages())

    assert isinstance(result.output, Triage)
    t = result.output
    print(f"\ncategoría   {t.category}")
    print(f"prioridad   {t.priority}/5")
    print(f"humano      {'sí' if t.needs_human else 'no'}")
    print(f"resumen     {t.summary}")

    # requests > 1 significa que hubo tool calls: una vuelta para pedirlas, otra
    # para responder con los resultados ya en el contexto.
    u = result.usage
    print(
        f"\n{u.requests} requests · {u.tool_calls} tool calls · "
        f"{u.input_tokens} in / {u.output_tokens} out"
    )
    print(f"\nconversación  {conv_id}")
    print(f'continuar     uv run python -m app.cli --conversation {conv_id} "..."')

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
