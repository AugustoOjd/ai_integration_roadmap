# 🔗 PROJECT 4: LangChain Core

**The base of the ecosystem: what everything else in LangChain is built on.**

Before `create_agent`, before graphs, before harnesses, there is one interface and
one operator. Every LangChain project that follows is those two ideas applied to
bigger nouns — so this is where the ecosystem starts.

RAG is the vehicle, chosen because you've built one by hand and know what's under
every word. The goal isn't a better RAG. It's seeing what the abstraction was
doing all along.

## 📌 When to Start

**Prerequisites:** a RAG pipeline you built from parts — loaders, chunking,
embeddings, vector search, prompt assembly.

Not as a baseline to beat — as **vocabulary**. When this project says "retriever",
you need to already know that underneath it is a cosine-similarity query with a
top-k and a similarity floor you chose. Everything LangChain names here, you
named something yourself first.

This is the first of five, and the order is the point:

```
P4  LangChain Core    ← estás aquí   LCEL, Runnable, retrieval
P5  LangChain Agents                 create_agent, tools, MCP, middleware
P6  LangGraph                        estado durable, interrupt
P7  Deep Agents                      harness, tareas largas
P8  Agent Ops                        evals, monitoring, deploy
```

Each step adds something the previous one couldn't hold. Here there is **no agent,
no loop, nothing that survives the request** — just a call and the retrieval
around it. Every abstraction above is built out of what's on this page.

## 🎯 The Core: the four things LangChain actually gives you

"A framework for LLM apps" explains nothing. There are four ideas. Learn these and
the rest of the library is just the same four applied to more nouns.

### 1. `Runnable` — one interface for every piece

Everything — prompts, chat models, retrievers, output parsers, even a plain
function — implements the same protocol:

```python
component.invoke(x)        # one input,  one output
component.batch([x, y])    # many inputs, parallelized
component.stream(x)        # incremental output
await component.ainvoke(x) # the same three, async
```

This is the load-bearing idea. Not because `invoke` is clever, but because a
uniform interface is what makes composition possible at all.

### 2. LCEL — the `|` operator

Because every piece is a `Runnable`, you can pipe them:

```python
chain = prompt | model | parser
```

That `|` builds a `RunnableSequence`. What you get from it is the part worth
understanding:

- **Streaming end to end.** `chain.stream()` works because *every* link knows how
  to stream. In Project 1 you wired the SSE plumbing by hand, once, for one path.
- **Batching end to end.** `chain.batch([...])` parallelizes across the whole
  pipeline. Your eval script becomes one call instead of a loop.
- **Async for free.** Every `Runnable` has an `a*` twin. No second code path.
- **`RunnableParallel`** runs branches concurrently — which is exactly how a RAG
  chain fetches context and passes the question through at the same time:

```python
from langchain_core.runnables import RunnableParallel, RunnablePassthrough

# Dict-of-runnables = run both branches concurrently, output a dict.
# "context" goes through the retriever; "question" passes through untouched.
chain = (
    RunnableParallel(context=retriever, question=RunnablePassthrough())
    | prompt      # consumes {"context": ..., "question": ...}
    | model
    | StrOutputParser()
)
```

That is the same graph you wrote by hand: fetch context, keep the question, build
the prompt, call the model, take the text. One version is **declared**, the other
is executed line by line. The difference is what streaming and batching cost you.

### 3. The integration layer — providers as configuration

One `Embeddings` interface over every embedding provider. One `VectorStore`
interface over pgvector, Chroma, Pinecone, Qdrant. One chat model interface over
every LLM API.

```python
from langchain.embeddings import init_embeddings
from langchain.chat_models import init_chat_model

# The provider is a string. Nothing downstream in the chain knows or cares.
embeddings = init_embeddings("voyageai:voyage-3.5-lite")
model = init_chat_model("groq:llama-3.3-70b-versatile", temperature=0.2)
```

In Project 1, swapping the LLM meant the OpenAI-compatible base URL trick, and
swapping the vector store meant rewriting SQL. Here both are a constructor
argument. **This is the part that most reliably earns its keep**, and Phase 6
makes you prove it with a stopwatch.

### 4. The retrieval stack — the boring 80%

Document loaders (PDF, HTML, Markdown, Notion, S3...), text splitters, retrievers,
and the glue from "a folder of files" to "chunks in a vector store". It is the
most mature part of the library and the actual reason most people install it.

```python
# Split on paragraph → line → word → character, in that order, backing off only
# when a chunk still doesn't fit. Project 1's chunker did this by hand.
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
```

### ⛔ What LangChain is *not*, despite most tutorials you'll find

Since **1.0 (Oct 2025)**, agents are not in this library. `AgentExecutor`,
`LLMChain`, `RetrievalQA`, `ConversationalRetrievalChain` — all removed or
deprecated. Agents live in `create_agent` (**Project 5**) and in **LangGraph**
(**Project 6**), which is exactly why they get projects of their own.

If a tutorial shows `LLMChain(llm=..., prompt=...)`, it is describing a version
that no longer exists. Close the tab. The modern answer is always `prompt | model`.

## 🛑 What stays yours

This half matters as much as the other, and it's the honest answer to "should I
use a framework".

| Still yours | Why |
|---|---|
| **Cache strategy** | LangChain caches the *LLM call*. The hit ratio lives in a cache keyed on the *query*, before retrieval even runs. That layer is yours. |
| **Chunk size and overlap** | The splitter takes the numbers. It does not choose them. That's still an experiment against an eval set. |
| **Retrieval quality** | `.as_retriever()` returns *something* for every query. Whether it's the right something is your problem — same as `MIN_SIMILARITY` was. |
| **Knowing what was retrieved** | A chain hides intermediate steps by default. Citations and "why did it answer that" need you to open it back up (Phase 3). |
| **Cost and token accounting** | The abstraction makes it easy to stop noticing how many API calls a query makes. |
| **Refusing to answer** | "Answer only from context, refuse when insufficient" is a prompt and an eval, not a feature. |

The pattern: LangChain gives you **plumbing**. It does not give you **judgment**.

## ☁️ No local model, on purpose

Project 1 ran embeddings locally: `sentence-transformers` + `torch`, a 1.1 GB
venv, and a model loaded into the host's RAM for the life of the process.
Reasonable there — it made the vector math concrete and nothing left the machine.

Here embeddings are a **hosted API**. The reasons are operational:

- No `torch`, no CUDA wheels, no 1.1 GB virtualenv.
- No model held in memory, so the container is small and starts instantly.
- Ingestion is I/O-bound instead of CPU-bound — it stops competing with the web
  process for the host.
- Hosted retrieval models are simply better than a 384-D MiniLM, and they are
  batched and rate-limited for you.

And this swap is itself the lesson: **the chain does not change**. `Embeddings` is
an interface; local and hosted are two implementations of it. That is point 3
above, demonstrated on day one rather than asserted.

> Note this makes the index incompatible with Project 1's — different model,
> different dimensionality, different vector space. That's expected. `PGVector`
> creates its own tables and its own collection, so both can live in the same
> database without touching each other.

## 🏗️ Architecture

```
POST /documents/upload → loader → splitter → embeddings API → PGVector
POST /chat            → retriever → prompt → chat model → stream
                             ↑
                    Redis cache (still yours)
```

Same shape as Project 1 — deliberately. Only the middle changes.

## 📚 Tech Stack

- **langchain-core** — `Runnable`, LCEL, prompts, messages, output parsers
- **langchain** — `init_chat_model` / `init_embeddings`, the provider-string layer
- **langchain-voyageai** — `voyage-3.5-lite`, hosted, retrieval-tuned. Free tier is
  generous; `output_dimension` is configurable (2048/1024/512/256)
- **langchain-groq** — `ChatGroq`, the same model Project 1 used
- **langchain-postgres** — `PGVector`. ⚠️ **psycopg3 only**: the URL is
  `postgresql+psycopg://`, not Project 1's `postgresql+asyncpg://`
- **langchain-text-splitters** — `RecursiveCharacterTextSplitter`
- **FastAPI**, **Redis**, **PostgreSQL + pgvector** — unchanged
- **LangSmith** — optional, worth one afternoon: it shows the intermediate steps a
  chain hides, which is otherwise the main cost of composing instead of executing

Install per-integration packages, never the old `langchain` metapackage habit. The
split is the library telling you what you actually depend on.

## 🚀 Quick Start

```bash
uv sync
cp .env.example .env          # VOYAGE_API_KEY, GROQ_API_KEY, DATABASE_URL
docker compose up -d
uv run uvicorn app.main:app --reload
```

Use the same corpus as Project 1: a rulebook the base model doesn't know, with
verifiable answers. Same reasons as before — see Project 1's README.

## 🗺️ Phases

1. **Ingestion on LangChain** — loader → splitter → hosted embeddings → `PGVector`.
   Index the corpus and read the tables LangChain created for you.
2. **The chain** — retriever + prompt + model composed with `|`. Get an answer out
   of five lines and then go read what `RunnableParallel` did with them.
3. **Streaming and citations** — `.stream()` on the whole chain, then get back what
   the chain hid: which chunks fed the answer.
4. **The cache** — put the Redis query-level layer back in front. Note what
   LangChain's own caching does *not* cover.
5. **Eval** — port the question set and score it with `chain.batch()`. Separate
   retrieval failures from generation failures, same as Project 1.
6. **The swap test** — change the embedding provider, then the vector store, then
   the LLM. Time each one. This is the experiment that puts a number on the
   integration layer, and it's the real payoff of the project.

## 📊 What to record in APRENDIZAJES.md

Not a scoreboard against Project 1 — a description of the trade you made:

| Question | Your answer |
|---|---|
| Lines of application code for the pipeline | |
| Direct dependencies | |
| Time to swap the embedding provider | |
| Time to swap the vector store | |
| Time to swap the LLM provider | |
| What broke that you couldn't see from the outside | |
| What you had to un-abstract to ship (citations, cache, ...) | |

The last two rows are the interesting ones. The swap rows will be minutes, and
that's the point — but so is whatever it cost you to get them.

## ⏱️ Timeline

6-8 hours. It's a pipeline you already understand, which is exactly why it's fast
and exactly why it teaches.

## ✅ Completion Checklist

- [ ] Corpus indexed through LangChain into `PGVector`
- [ ] Chat endpoint answering, streaming, with citations
- [ ] Redis cache in front
- [ ] Eval set ported and run via `chain.batch()`
- [ ] Embedding provider swapped once, timed
- [ ] Vector store swapped once, timed
- [ ] LLM provider swapped once, timed
- [ ] `APRENDIZAJES.md` with the table above filled in

## 🎓 You're done when you can answer

- What does `|` actually build, and why does streaming work through all of it?
- Which pieces of a hand-built pipeline does LangChain genuinely replace, and
  which does it only rename?
- What does a chain hide that you needed back, and what did getting it back cost?
- If the code is shorter and the answers are the same, what did you give up?
- When would you *not* reach for this — and is "we only ever use one provider" a
  good enough reason?
- Everything in Projects 5 to 8 is built on `Runnable`. Which of the four ideas
  above do you expect to see again, and where?

See **[SOURCES.md](./SOURCES.md)** for official docs and related material.

---

**Made as part of Sr Backend Roadmap** 🚀

Duration: 6-8 h · Result: knowing what a framework does for you, from having done
it yourself first — and the vocabulary the next four projects assume
