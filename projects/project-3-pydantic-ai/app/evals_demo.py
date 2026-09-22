"""Evaluar el agente como si fuera un test suite.

    uv run python -m app.evals_demo

El modelo mental es pytest: un Case es un test, un Dataset la suite, y correrla
es un experimento. La diferencia está en los evaluadores — las aserciones son
difusas, y una de ellas mira el CAMINO y no el resultado.
"""

import asyncio
from dataclasses import dataclass

import logfire
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from app.agent.deps import Deps
from app.agent.triage import Triage, triage_agent
from app.core.config import settings
from app.core.db import SessionFactory, engine

# Los evaluadores de trayectoria leen el árbol de spans, así que la
# instrumentación no es opcional acá: sin ella `ctx.span_tree` viene vacío.
# send_to_logfire=False mantiene todo local.
logfire.configure(send_to_logfire=False, console=False, service_name="evals")
logfire.instrument_pydantic_ai()


@dataclass
class Ticket:
    """La entrada de un caso: el mensaje y de quién es."""

    mensaje: str
    customer_id: str


async def clasificar(ticket: Ticket) -> Triage:
    """La función bajo prueba. Es el sistema entero, no una pieza."""
    deps = Deps(
        session_factory=SessionFactory, customer_id=ticket.customer_id, role="customer"
    )
    result = await triage_agent.run(ticket.mensaje, deps=deps)
    assert isinstance(result.output, Triage)
    return result.output


@dataclass
class CategoriaEsperada(Evaluator[Ticket, Triage]):
    """Aserción exacta: barata, determinista, sin modelo de por medio."""

    def evaluate(self, ctx: EvaluatorContext[Ticket, Triage]) -> bool:
        return ctx.output.category == ctx.expected_output.category


@dataclass
class ConsultoLasOrdenes(Evaluator[Ticket, Triage]):
    """Evalúa la TRAYECTORIA, no la respuesta.

    `ctx.span_tree` son las spans de OpenTelemetry del run — las mismas que
    instrumentaste en la fase 7. Acá se ve por qué tracing y evals van juntos:
    sin spans no hay forma de preguntar qué hizo el agente por dentro.

    Un agente puede acertar la categoría adivinando desde el texto. Eso es
    correcto hoy y frágil mañana.
    """

    def evaluate(self, ctx: EvaluatorContext[Ticket, Triage]) -> bool:
        return ctx.span_tree.any(lambda node: "recent_orders" in node.name)


dataset = Dataset[Ticket, Triage](
    name="triage",
    cases=[
        Case(
            name="envio",
            inputs=Ticket("mi paquete nunca llegó", "cus_ana"),
            expected_output=Triage(
                category="shipping", priority=3, needs_human=False, summary=""
            ),
        ),
        Case(
            name="cobro_duplicado",
            inputs=Ticket("me cobraron dos veces los auriculares", "cus_ana"),
            expected_output=Triage(
                category="billing", priority=4, needs_human=True, summary=""
            ),
        ),
        Case(
            name="producto_roto",
            inputs=Ticket("el monitor llegó con la pantalla partida", "cus_bruno"),
            expected_output=Triage(
                category="technical", priority=4, needs_human=True, summary=""
            ),
        ),
    ],
    evaluators=[
        CategoriaEsperada(),
        ConsultoLasOrdenes(),
        # El juez es otro agente, con los mismos modos de falla que el juzgado.
        # Por eso va último y no solo: es la aserción menos confiable.
        LLMJudge(
            rubric=(
                "El resumen describe el problema concreto del cliente y no "
                "inventa datos que no estén en el ticket."
            ),
            include_input=True,
            # Sin esto el juez usa el default de la librería, que es OpenAI.
            model=settings.AGENT_MODEL,
        ),
    ],
)


async def main() -> None:
    report = await dataset.evaluate(clasificar)
    report.print(include_input=False, include_output=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
