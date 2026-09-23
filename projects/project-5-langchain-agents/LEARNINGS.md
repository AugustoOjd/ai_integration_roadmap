# 📘 Project 5 — Learnings

LangChain Agents: a loop you don't own, and the doors back into it.

> ✍️ = fill in from your own runs. Everything else was observed in this
> project (a measured number, the installed source, or a wire trace).

---

## 📊 The table

| Question | Answer |
|---|---|
| **What the derived tool schema contains, and what it omits** | *Contains:* name, description (the docstring summary), and per-argument type + description from `Args:` (`parse_docstring=True`). Pydantic `Field` constraints become schema: `issue_refund.amount` carries `exclusiveMinimum: 0` and a 2-decimal pattern; `reason` becomes an `enum`. *Omits:* the `runtime: ToolRuntime` parameter (so the model can't see or fill the pool or `customer_id`), and the **return type**: the model learns nothing about a result until it calls the tool. MCP tools do carry an `outputSchema`; LangChain `@tool` doesn't. Without `parse_docstring`, the raw `__doc__` is sent verbatim, source indentation included. |
| **Which of your hand-written loop's concerns became middleware** | Iteration cap → *not* middleware: `recursion_limit` in config (default **10 007**, effectively unbounded). Cost ceiling → `BudgetMiddleware`. Logging decisions → `AuditMiddleware`. Authorization on tools you don't own → `TrackingOwnershipMiddleware`. Approval → `HumanInTheLoopMiddleware`. Timeouts / failure handling on a dependency → `RemoteToolFailureMiddleware`. What did **not** move: authorization inside our own tools (it stays in the SQL), idempotency (in `issue_refund` + a `UNIQUE`), and who the reviewer is (in the UI layer). |
| **Which hook you reached for, and why that one** | `wrap_model_call` for the budget: it's the only hook that can **prevent** the call (and not pay for it). `after_model` for the audit: it only needs to *see* the decision, and it sees the budget's refusal too. `wrap_tool_call` for ownership and remote failures: it can refuse or replace a tool call and still answer with a `ToolMessage` carrying the right `tool_call_id`. |
| **What the raw MCP exchange looks like before any client** | `initialize` → result (`protocolVersion`, `capabilities`, `serverInfo`) → `notifications/initialized`; then `tools/list` and `tools/call`, one JSON object per line on stdio. Two error layers: a tool refusing is a **successful** response with `isError: true`; an unknown *method* is a JSON-RPC `error` (`-32601`). Where an unknown *tool* lands is the server's choice (fastmcp: `isError`; the spec's example: `-32602`). Closing stdin = shutdown; a call still in flight gets `-32000 Connection closed`. |
| **Where a paused run lives, and what kills it** | In the checkpointer, under the `thread_id`. `interrupt()` saves state and `ainvoke` *returns* with `__interrupt__`; resuming is `ainvoke(Command(resume=…))` on the same thread. With `InMemorySaver` it's a dict in the process: Ctrl-C while a refund waits, and the pending refund is gone, neither approved nor rejected. Without any checkpointer the pause still happens, but resuming raises `Cannot use Command(resume=...) without checkpointer`. |
| **What broke when the MCP server went away** | *Dead:* `MCPError: Connection closed` in 0.0 s, on every later call too: the adapter never reconnects. Before `RemoteToolFailureMiddleware`, it escaped the adapter and **ended the whole run**. After: the model gets a tool error and answers from order data. *Frozen:* ✍️ how long the first call waited, and what the customer saw. |

---

## 🔢 Numbers

| Metric | Value |
|---|---|
| Fixed cost of one run (system prompt + 2 tool schemas + question) | **858 tokens**, first model call |
| Second call of the same run (history + tool result resent) | 1 142 tokens |
| Budget overshoot by design (pre-call check) | up to one full call: 858 spent against a 500 budget |
| Steps per tool round | 2 without node middleware, **3** with `AuditMiddleware`; `recursion_limit` 12 → 17 |
| Dead MCP server: time to fail | ~0.0 s |
| Frozen MCP server: time to fail | ✍️ (expected ≈ `REMOTE_TOOL_TIMEOUT_S` = 5 s) |

---

## 🧭 Decisions worth remembering

1. **Budget per run, not on `self`.** One middleware instance serves every run in the process. The counter lives in state (`UntrackedValue` + `PrivateStateAttr`).
2. **The budget is a soft ceiling.** It checks what's already spent; nobody knows a call's cost until it's made.
3. **Fail closed on audit and on review records.** If the insert fails, the run doesn't continue. Money is involved.
4. **Tool or middleware? If you own the tool's body, authorize inside it. If you don't, wrap it.**
5. **A guard keyed by tool name fails open** when the server renames or adds tools. Hence `REVIEWED_REMOTE_TOOLS`: discovery proposes, we decide.
6. **Middleware order is semantics.** HITL rewrites the call inside its wrap, so guards go *after* it and check what actually runs.
7. **No `respond` for refunds.** It fakes a tool result without running the tool.
8. **Approval isn't authorization.** `issue_refund` validates ownership, window, amount and idempotency as if nobody had looked.
9. **Idempotency key = what, not which call.** `refund:{order_id}`, never `tool_call_id`, which changes on every retry.
10. **Three audit tables, three truths:** `model_audit` (what the model asked), `review_decisions` (what a person allowed), `refunds` (what moved). After an edit, the first two differ.

---

## 🎓 The README's closing questions

- **`create_agent` returns a graph. What follows?** `invoke`/`stream`, the checkpointer, `thread_id`, `interrupt` and `recursion_limit` are all LangGraph. P6 isn't optional: every limit in this project (in-memory pauses, amnesia on restart) is a LangGraph setting we left at the toy value.
- **`wrap_model_call` vs `before_model`?** When you need to decide *whether* the call happens and see what it cost: both sides of the call. `before_model` can only look at the state before, and jumping to the end from there skips the call without an answer.
- **Middleware or tool: what's the test?** Whether the concern belongs to *one action* (tool) or to *every call of a kind* (middleware), and whether you own the code you'd have to change.
- **What did the raw MCP messages teach that the adapter hides?** The two error layers, the handshake, that stdout is the protocol, and that `structuredContent` exists: the adapter puts it in the artifact, where the model never sees it.
- **Approval as middleware: what does it buy, and what does it fail to protect against?** It buys a gate without touching the loop or the tool. It doesn't protect against a wrong approval, a double approval, or a lost pause. That's why the tool validates, the key is idempotent, and P6 exists.

---

## ✅ Completion checklist

- [x] Agent answering with two local tools
- [x] Multi-turn conversation over a `thread_id`
- [x] Two custom middleware, one wrap-style and one node-style (four in total)
- [x] MCP server written with fastmcp, exercised over the raw protocol by a hand-written client
- [x] The same server consumed through `MCPAdapter`
- [ ] ✍️ A refund approved, one rejected, one edited: against the real DB, from your runs
- [ ] ✍️ Phase 6 experiments run and the frozen row filled in
