"""Stop a run that has spent too many tokens. The agent never knows this exists."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
)
from langchain.agents.middleware.types import ContextT, PrivateStateAttr
from langchain_core.messages import AIMessage
from langgraph.channels.untracked_value import UntrackedValue
from langgraph.types import Command
from typing_extensions import NotRequired


class BudgetState(AgentState):
    """The agent's state, plus this middleware's counter.

    Middleware can extend the state: create_agent merges every middleware's
    `state_schema` into one. The annotations decide the counter's lifetime:

    - UntrackedValue: never written to the checkpointer. Each invoke starts
      without it — so this is a budget *per run*, not per thread.
    - PrivateStateAttr: omitted from the graph's input and output schemas.
      Callers can't pass it in, and it doesn't show up in the result.
    """

    run_tokens: NotRequired[Annotated[int, UntrackedValue, PrivateStateAttr]]


# Generic over ContextT (the same TypeVar the built-ins use): budgeting doesn't
# care what the run's context is, so it works with any agent. Pinning it to
# AgentContext would couple a cross-cutting concern to one app's types.
class BudgetMiddleware(AgentMiddleware[BudgetState, ContextT]):
    """Caps total tokens (input + output) across all model calls of one run.

    Why the count lives in state and not in `self.spent` (as in the README):
    one agent — so one middleware instance — serves every run in the process.
    A counter on `self` would be shared by concurrent runs, and it would never
    reset. State is per run by construction.
    """

    state_schema = BudgetState

    def __init__(self, max_tokens_per_run: int) -> None:
        super().__init__()
        self.max_tokens = max_tokens_per_run

    # Only the async hook: the agent always runs via ainvoke. If someone calls
    # invoke(), the base class raises a NotImplementedError that says exactly this.
    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse]],
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        spent = request.state.get("run_tokens", 0)

        # Side 1, before the call: we decide whether it happens at all.
        if spent >= self.max_tokens:
            # Short-circuit: `handler` is never called, so the model is never
            # billed. We return an AIMessage *without* tool_calls; to the loop
            # that looks like a final answer, so the run ends cleanly and the
            # conversation stays valid (no tool_call left without its result).
            return AIMessage(
                content="I couldn't finish this within the allowed budget. "
                "Please narrow the question or contact a human agent.",
                # Marks the message so logs/UI can tell it apart from a real answer.
                response_metadata={"budget_exceeded": True, "run_tokens": spent},
            )

        # The real model call. Everything above and below is ours.
        response = await handler(request)

        # Side 2, after the call: we see what it cost. Anthropic reports usage
        # per call; total = input + output, and input grows every round because
        # the whole conversation is resent — that growth is the real cost curve.
        used = sum(
            (msg.usage_metadata or {}).get("total_tokens", 0)
            for msg in response.result
            if isinstance(msg, AIMessage)
        )

        # A wrap hook doesn't return a state dict like before/after_model do.
        # To write state it returns the response *plus* a Command, applied as
        # an extra update once the model node finishes.
        update: dict[str, Any] = {"run_tokens": spent + used}
        return ExtendedModelResponse(model_response=response, command=Command(update=update))
