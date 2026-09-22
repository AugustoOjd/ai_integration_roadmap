# Sources

**No LangChain Academy courses for this one.** Pydantic AI is a competing
ecosystem — everything you need is in its own documentation, which is good.

> ⚠️ The docs moved: `ai.pydantic.dev` now 301s to `pydantic.dev/docs/ai/`.
> Old links still work, but the section layout changed — what used to be
> `/agents/` is now `/core-concepts/agent/`.

## Part A — the typed agent

| Resource | Covers |
|---|---|
| [Core Concepts](https://pydantic.dev/docs/ai/core-concepts/agent/) | The `Agent`, the five ways to run it, instructions vs system prompts, `ModelRetry`, `UsageLimits`, model settings, conversations |
| [Dependencies](https://pydantic.dev/docs/ai/core-concepts/dependencies/) | `deps_type`, `RunContext[Deps]` — phase 1 |
| [Output](https://pydantic.dev/docs/ai/core-concepts/output/) | `output_type`, validated results — phase 1 |
| [Tools & Toolsets](https://pydantic.dev/docs/ai/tools-toolsets/) | Function tools, schema derivation from docstrings, `@agent.tool` vs `@agent.tool_plain` — phase 2 |
| [Toolsets](https://pydantic.dev/docs/ai/tools-toolsets/toolsets/) | `FunctionToolset`, `.filtered()`, `.prefixed()`, `CombinedToolset`, `WrapperToolset` — phase 3 |
| [Message History](https://pydantic.dev/docs/ai/core-concepts/message-history/) | Serializing and reloading conversations — phase 4 |
| [Models & Providers](https://pydantic.dev/docs/ai/models/) | Model vs Provider vs Profile, `FallbackModel` — phase 5 |
| [Deferred Tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/) | `requires_approval`, `DeferredToolRequests`, `ToolApproved`/`ToolDenied`, `CallDeferred` — phase 6 |
| [Logfire](https://pydantic.dev/docs/logfire/) | OpenTelemetry-native instrumentation — phase 7 |

## Part B — the shallow pass

| Resource | Covers |
|---|---|
| [Graph](https://pydantic.dev/docs/ai/graph/) | `BaseNode`, `GraphRunContext`, `End`, Mermaid rendering — phases 8-9 |
| [Embeddings](https://pydantic.dev/docs/ai/embeddings/) | `Embedder`, `embed_query` vs `embed_documents`, `EmbeddingSettings` — phase 10 |
| [MCP](https://pydantic.dev/docs/ai/capabilities/mcp/) | The `MCP` capability, `MCPToolset`, native vs local — phase 11 |
| [Interfaces](https://pydantic.dev/docs/ai/interfaces/) | CLI (`clai`), web chat UI, AG-UI, Vercel AI, ACP, A2A — phase 12 |
| [Image Generation](https://pydantic.dev/docs/ai/capabilities/image-generation/) | The `ImageGeneration` capability, fallback strategies, `BinaryImage` — phase 13 |
| [Evals](https://pydantic.dev/docs/ai/evals/) | `Case`, `Dataset`, `LLMJudge`, custom and trajectory evaluators — phase 14 |

## Reading the docs with an agent

| Resource | Covers |
|---|---|
| [pydantic.dev/docs/ai/llms.txt](https://pydantic.dev/docs/ai/llms.txt) | The full doc index in llms.txt format |

Every page also has a `.md` twin: append `index.md` to any section URL
(`.../core-concepts/agent/index.md`) to get the raw Markdown.
