"""The agent: model + tools + prompt. The while-loop is inside create_agent."""

import logging
from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState, HumanInTheLoopMiddleware
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain.chat_models import init_chat_model
from langchain_core.messages import ToolCall
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Checkpointer

from app.core.config import settings
from app.core.context import AgentContext
from app.middleware.audit import AuditMiddleware
from app.middleware.budget import BudgetMiddleware
from app.middleware.ownership import TrackingOwnershipMiddleware
from app.middleware.remote_failure import RemoteToolFailureMiddleware
from app.tools.orders import TOOLS
from app.tools.refunds import issue_refund

logger = logging.getLogger(__name__)


# Runtime[Any], not Runtime[AgentContext]: HITL's description protocol is
# generic per call, so it only accepts a function that takes *any* context.
# We know ours is AgentContext and narrow it by annotation below.
def _describe_refund(tool_call: ToolCall, state: AgentState, runtime: Runtime[Any]) -> str:  # noqa: ARG001 — signature fixed by HITL
    """What the reviewer reads. Sync, no DB: built from the call itself."""
    ctx: AgentContext = runtime.context
    args = tool_call["args"]
    amount = args.get("amount")
    what = f"${amount}" if amount is not None else "the FULL order total"
    # The customer comes from context, not args: the model can't choose it,
    # so the reviewer shouldn't have to trust the model about it either.
    return (
        f"Refund {what} on order {args.get('order_id')} "
        f"for customer {ctx.customer_id} — reason: {args.get('reason')}"
    )

SYSTEM_PROMPT = """\
You are Nordix's customer support assistant. You talk to one authenticated
customer; the tools already know who they are.

- Answer only from tool results. Never invent an order id, status, date or amount.
- If an order isn't found, say so plainly. Don't speculate about why.
- Amounts are Argentine pesos. Dates: say them in words ("3 days ago"), not ISO.
- Keep answers short: this is a support chat, not an email.
- Where a shipment physically is comes from the carrier: call track_shipment
  with the order's tracking_code (from order_status). "stale": true means the
  package is considered lost — say so and offer a refund or replacement.
- Refunds: call issue_refund only when the customer explicitly asks for one.
  If it returns an error (window expired, not delivered…), explain the rule
  in plain words; don't retry with different arguments to get around it.
"""

# LangGraph counts *supersteps* (one per node executed), not model calls.
# Node-style middleware adds nodes: with AuditMiddleware one tool round is
# model → Audit.after_model → tools = 3 steps, and the answer is 2 more.
# 17 ≈ five tool rounds and an answer. (Wrap hooks add no nodes: they run
# inside `model`.) Adding a node-style middleware silently shrinks this bound —
# it was 12 before the audit existed.
# The library default is 10_007 — effectively no bound at all. The cap you
# wrote by hand in P2 doesn't exist here unless you pass this.
RECURSION_LIMIT = 17

# Remote tools we've reviewed, and how each is guarded (tool → the argument
# TrackingOwnershipMiddleware checks; None = nothing customer-specific to check).
# Discovery means the *server* decides the tool list at runtime; this is where
# we decide which of those the model may see. Anything not listed is dropped.
REVIEWED_REMOTE_TOOLS: dict[str, str | None] = {
    "track_shipment": "tracking_code",
    "carrier_contact": None,
}


# No return annotation: it's CompiledStateGraph[AgentState, AgentContext, …]
# with four type params, and inference already gets it right.
#
# The checkpointer is injected, not created here: *where* memory lives is the
# caller's decision. The CLI passes an InMemorySaver; P6 passes a Postgres one
# and this function doesn't change.
#
# remote_tools: the MCP tools only exist while their connection is open, so
# they can't be a module constant like TOOLS — the caller discovers them and
# passes them in.
def build_agent(remote_tools: Sequence[BaseTool] = (), checkpointer: Checkpointer = None):
    # init_chat_model instead of passing the string straight to create_agent:
    # same "<provider>:<model>" format, but it lets us set the knobs a
    # production call needs. A string alone gets the provider's defaults.
    model = init_chat_model(
        settings.CHAT_MODEL,
        temperature=0,     # support answers should be reproducible, not creative
        max_tokens=1024,   # bounds cost and latency per call
        timeout=30,        # seconds; the SDK default is 10 minutes
        max_retries=2,     # retries 429/5xx with backoff inside the SDK
    )

    # Order matters: the first middleware is the outermost layer, like
    # FastAPI/ASGI. Budget goes outside so nothing inside it can spend
    # without being counted. before_* hooks run in list order, after_*
    # in reverse (the onion) — Audit has no wrap hook, so here order only
    # affects which after_model node runs first.
    #
    # The explicit type: each middleware declares its own state schema
    # (BudgetState, AgentState…) and create_agent merges them at runtime. The
    # type system can't express that merge, so state is Any here; the context
    # type is still checked.
    middleware: list[AgentMiddleware[Any, AgentContext]] = [
        BudgetMiddleware(settings.RUN_TOKEN_BUDGET),
        AuditMiddleware(),
        # HITL has an after_model hook (pause + collect decisions) AND a
        # wrap_tool_call hook (apply a reviewer's edit to the call). Its place
        # in this list matters for the second one: it rewrites the request and
        # then calls handler(), so every middleware *after* it here sees the
        # edited args, and every one before it sees the model's originals.
        # It goes before TrackingOwnershipMiddleware so that guards check what
        # will actually run — an edit must never skip authorization.
        # [AgentState, AgentContext]: HITL is generic over context like Budget;
        # the constructor has no argument to infer it from, so it's explicit.
        HumanInTheLoopMiddleware[AgentState, AgentContext](
            interrupt_on={
                "issue_refund": InterruptOnConfig(
                    # No "respond": it returns a fake tool result without
                    # running the tool. For a refund that means the model is
                    # told money moved when it didn't.
                    allowed_decisions=["approve", "edit", "reject"],
                    description=_describe_refund,
                ),
            },
        ),
        # Keyed by tool *name*: a guard like this fails open if the server
        # renames the tool or adds a new one. The allowlist below closes that.
        TrackingOwnershipMiddleware(
            {name: arg for name, arg in REVIEWED_REMOTE_TOOLS.items() if arg is not None}
        ),
        # Innermost: it wraps only the actual network call. Anything refused
        # above (ownership, a HITL reject) never reaches it, and never counts
        # as the carrier's failure.
        RemoteToolFailureMiddleware(REVIEWED_REMOTE_TOOLS, settings.REMOTE_TOOL_TIMEOUT_S),
    ]

    # Fail closed on discovery: an unreviewed remote tool is dropped, not
    # trusted. Its description would go straight into our prompt, and no
    # guard knows about it. Logged loudly, because a silent drop hides drift.
    accepted = [t for t in remote_tools if t.name in REVIEWED_REMOTE_TOOLS]
    for t in remote_tools:
        if t.name not in REVIEWED_REMOTE_TOOLS:
            logger.warning("dropping unreviewed remote tool %r", t.name)

    # One flat namespace: the model can't tell a local tool from a remote one,
    # and a remote tool named "order_status" would collide with ours. Fail at
    # startup, not with a model calling the wrong one.
    # issue_refund is local and writes money. Step 2 of phase 5 puts a human
    # in front of it; until then the model can call it on its own judgment.
    tools = [*TOOLS, issue_refund, *accepted]
    names = [t.name for t in tools]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate tool names: {sorted(names)}")

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        # Declares the type of `context=` at invoke time, and what tools get in
        # `runtime.context`. It isn't state: it isn't saved, and the model
        # never sees it.
        context_schema=AgentContext,
        # None → every invoke starts from an empty state (phase 1 behavior).
        # With one, the graph saves its state after every step, keyed by
        # config["configurable"]["thread_id"], and loads it on the next invoke.
        checkpointer=checkpointer,
    )
