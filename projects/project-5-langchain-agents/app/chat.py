"""Talk to the agent as one customer.

    # one-shot: one question, the process ends after the answer
    uv run python -m app.chat "¿dónde está mi pedido A17?"

    # interactive: turns share a thread until you quit
    uv run python -m app.chat --thread ticket-1 --trace
    > /state      show what the checkpointer holds for this thread
    > /quit

In both modes, a call to issue_refund pauses and asks *you* to approve,
edit or reject it before any money moves.
"""

import argparse
import asyncio
import getpass
import json
import logging
import uuid
from typing import Any

from langchain.agents.middleware.human_in_the_loop import Decision, HITLRequest
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command, Interrupt
from psycopg.types.json import Jsonb

from app.agent import RECURSION_LIMIT, build_agent
from app.core.config import ROOT, settings
from app.core.context import AgentContext
from app.db.pool import open_pool
from app.tools.carrier import carrier_tools


def print_trace(messages: list[AnyMessage]) -> None:
    """The loop, made visible: every model call, its cost, and every tool result.

    `spent` replays BudgetMiddleware's arithmetic (its counter is hidden from
    the result), so each model line shows the check it passed *before* running.
    """
    print(f"  budget: {settings.RUN_TOKEN_BUDGET} tokens")
    spent = 0
    for msg in messages:
        if isinstance(msg, AIMessage):
            if msg.response_metadata.get("budget_exceeded"):
                # Not a model call: the middleware answered instead of the model.
                print(f"  ✗ model call REFUSED — spent {spent} >= {settings.RUN_TOKEN_BUDGET}")
                continue
            used = (msg.usage_metadata or {}).get("total_tokens", 0)
            print(f"  ✓ model call allowed (spent before: {spent}) → cost {used}")
            spent += used
            for call in msg.tool_calls:
                print(f"      → {call['name']}({call['args']})")
        elif isinstance(msg, ToolMessage):
            # .text, not str(content): MCP tools return content *blocks*
            # ([{"type": "text", ...}]); local tools return a plain string.
            # status="error" is how an MCP isError result reaches the model.
            mark = "✗" if msg.status == "error" else "←"
            # Truncated: a tool result can be long; the trace is for shape.
            print(f"      {mark} {msg.name}: {msg.text[:120]}")
    print(f"  Σ {spent} tokens")


async def prompt(text: str) -> str:
    # input() blocks; in a thread, so the event loop (and the pool's
    # background tasks) keep running while we wait for the human.
    return (await asyncio.to_thread(input, text)).strip()


async def review(request: HITLRequest) -> list[Decision]:
    """Play the reviewer: one decision per paused action, in the same order.

    HITL checks the count and raises if it doesn't match — a decision can't
    silently go missing and leave a tool call approved by default.
    """
    # Which decisions each action allows, keyed by tool name.
    allowed = {c["action_name"]: c["allowed_decisions"] for c in request["review_configs"]}
    decisions: list[Decision] = []

    for action in request["action_requests"]:
        options = allowed[action["name"]]
        print(f"\n  ⏸  {action.get('description', action['name'])}")
        print(f"     args: {json.dumps(action['args'], ensure_ascii=False)}")

        while True:
            choice = await prompt(f"     {' / '.join(options)}? ")
            if choice == "approve" and "approve" in options:
                decisions.append({"type": "approve"})
            elif choice == "reject" and "reject" in options:
                reason = await prompt("     reason for the customer (optional): ")
                # The message is shown to the model as the tool's result, so
                # it can tell the customer why. Without one, HITL tells the
                # model not to retry unless asked.
                decisions.append({"type": "reject", "message": reason} if reason else {"type": "reject"})
            elif choice == "edit" and "edit" in options:
                raw = await prompt("     new args as JSON (empty = keep): ")
                try:
                    new_args: dict[str, Any] = json.loads(raw) if raw else {}
                except json.JSONDecodeError as e:
                    print(f"     not JSON: {e}")
                    continue
                # Merge onto the model's args: edit one field, keep the rest.
                # The tool name stays fixed — an edit that could swap *which*
                # tool runs is a different, much bigger permission.
                decisions.append({
                    "type": "edit",
                    "edited_action": {"name": action["name"], "args": {**action["args"], **new_args}},
                })
            else:
                print(f"     pick one of: {', '.join(options)}")
                continue
            break

    return decisions


async def record_decisions(
    context: AgentContext,
    thread_id: str,
    interrupt: Interrupt,
    decisions: list[Decision],
    reviewer: str,
) -> None:
    """Persist who decided what, *before* the run resumes.

    Write-ahead: if this insert fails, the caller never resumes, so no refund
    runs without its decision on record. Same fail-closed choice as
    AuditMiddleware. In an HTTP app this is the approval endpoint's job —
    it's the only layer that knows who the reviewer is.
    """
    request: HITLRequest = interrupt.value
    async with context.pool.connection() as conn, conn.transaction():
        # zip(strict=True): HITL requires one decision per action; if the
        # counts ever differ, fail here rather than record a misaligned pair.
        for i, (action, d) in enumerate(zip(request["action_requests"], decisions, strict=True)):
            final_args = (
                None if d["type"] == "reject"
                else d["edited_action"]["args"] if d["type"] == "edit"
                else action["args"]
            )
            await conn.execute(
                """
                INSERT INTO review_decisions (interrupt_id, action_index, customer_id,
                    thread_id, tool_name, proposed_args, decision, final_args, message, reviewer)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    interrupt.id, i, context.customer_id, thread_id, action["name"],
                    Jsonb(action["args"]), d["type"],
                    None if final_args is None else Jsonb(final_args),
                    d.get("message"), reviewer,
                ),
            )


async def ask(
    agent,
    question: str,
    config: RunnableConfig,
    context: AgentContext,
    trace: bool,
    reviewer: str,
) -> None:
    """One turn: send the question, print the answer (and the loop, if asked)."""
    # Only the *new* message. The graph loads the thread's saved messages and
    # appends this one — you never resend history.
    payload: Any = {"messages": [{"role": "user", "content": question}]}
    try:
        while True:
            result = await agent.ainvoke(payload, config=config, context=context)

            # A paused run doesn't raise: ainvoke *returns*, with the pending
            # interrupts under "__interrupt__". The state up to the pause is in
            # the checkpointer, keyed by this thread_id.
            interrupts: list[Interrupt] = result.get("__interrupt__", [])
            if not interrupts:
                break

            # Resume = invoke again, same thread, with a Command instead of
            # input. Keyed by interrupt id, so it's unambiguous even if several
            # nodes paused at once. The graph re-runs the paused node from its
            # start, and interrupt() returns our value this time.
            thread_id = str(config.get("configurable", {}).get("thread_id"))
            resume: dict[str, Any] = {}
            for intr in interrupts:
                decisions = await review(intr.value)
                await record_decisions(context, thread_id, intr, decisions, reviewer)
                resume[intr.id] = {"decisions": decisions}
            payload = Command(resume=resume)
    except GraphRecursionError:
        # The loop hit its bound. Whoever asked gets an answer, not a traceback.
        print("Couldn't resolve that in a reasonable number of steps. Please rephrase.")
        return

    # `result` is the thread's full state, every earlier turn included. This
    # turn's messages are the ones after our question.
    messages: list[AnyMessage] = result["messages"]
    last_question = max(i for i, m in enumerate(messages) if m.type == "human")
    if trace:
        print_trace(messages[last_question + 1 :])
    print(messages[-1].text)


async def print_state(agent, config: RunnableConfig) -> None:
    """What the checkpointer holds for this thread — memory is just this."""
    snapshot = await agent.aget_state(config)
    messages = snapshot.values.get("messages", [])
    # .get: `configurable` is an optional key of the RunnableConfig TypedDict.
    print(f"  thread:     {config.get('configurable', {}).get('thread_id')}")
    # Each step saves a new checkpoint; this id changes after every turn.
    print(f"  checkpoint: {snapshot.config.get('configurable', {}).get('checkpoint_id')}")
    print(f"  messages:   {len(messages)} ({', '.join(m.type for m in messages)})")


async def main() -> None:
    # Our logs (remote failures, dropped tools) go to a file, like the
    # carrier's: the terminal is the customer's view, not the operator's.
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        filename=ROOT / "logs" / "agent.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", help="omit for interactive mode")
    # Stands in for authentication: in a real app this comes from the session,
    # never from anything the customer typed.
    parser.add_argument("--customer", default="C-1001")
    parser.add_argument("--thread", help="conversation id; default: a new one")
    parser.add_argument("--trace", action="store_true", help="print tool calls and results")
    # The human approving refunds. Not the customer: in a real system these are
    # two different authenticated sessions. Here, your OS user by default.
    parser.add_argument("--reviewer", default=getpass.getuser())
    args = parser.parse_args()

    interactive = args.question is None
    thread = args.thread or uuid.uuid4().hex[:8]
    config: RunnableConfig = {
        # The thread_id is namespaced by customer. A bare client-supplied id
        # would let C-1002 pass "ticket-1" and load C-1001's history: a
        # thread id is a key into someone's data, and needs an owner.
        "configurable": {"thread_id": f"{args.customer}:{thread}"},
        "recursion_limit": RECURSION_LIMIT,
    }

    # Two dependencies with a lifetime, opened together and closed in reverse:
    # the DB pool, and the carrier's MCP connection (a subprocess).
    async with open_pool() as pool, carrier_tools() as remote_tools:
        # A checkpointer in *both* modes now. Phase 2 used it for memory; HITL
        # needs it for the pause itself: interrupt() saves the run's state and
        # returns, and resuming loads it back by thread_id. Without one, the
        # pause still happens (the refund doesn't run) but the resume fails:
        # "Cannot use Command(resume=...) without checkpointer". Safe, and
        # useless — a pause with nowhere to live can never be approved.
        # InMemorySaver is a dict in this process: kill the process while a
        # refund waits for approval, and the pending refund is simply gone.
        agent = build_agent(remote_tools, checkpointer=InMemorySaver())
        context = AgentContext(pool=pool, customer_id=args.customer)

        if not interactive:
            await ask(agent, args.question, config, context, args.trace, args.reviewer)
            return

        print(f"thread {thread} as {args.customer} — /state, /quit")
        while True:
            try:
                line = await prompt("> ")
            except EOFError:  # Ctrl-D
                break
            if not line:
                continue
            if line == "/quit":
                break
            if line == "/state":
                await print_state(agent, config)
                continue
            await ask(agent, line, config, context, args.trace, args.reviewer)


if __name__ == "__main__":
    asyncio.run(main())
