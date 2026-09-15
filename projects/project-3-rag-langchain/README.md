# 🔗 PROJECT 3: RAG on LangChain

**Project 1, rebuilt on the framework — and measured against it.**

Project 1 built a RAG pipeline by hand: loaders, chunking, embeddings, pgvector
search, prompt assembly. This project rebuilds the same pipeline on LangChain and
runs it against **the same eval set**, so the comparison produces a number
instead of an opinion.

## 📌 When to Start

**Prerequisites:** Project 1 complete, with its eval set passing.

```
Mini 1-5 → PROJECT 1 (by hand) ✅
                    ↓
              PROJECT 3 ← You are here
```

You need Project 1 finished first. Not as background reading — as the **baseline**.
Without it this project is a LangChain tutorial; with it, it's a measurement.

## 🎯 The Core: what LangChain actually is

LangChain is often described as "a framework for LLM apps", which explains
nothing. Aim at these three things and ignore the rest:

**1. An integration layer.** One `VectorStore` interface over pgvector, Chroma,
Pinecone, Qdrant. One `Embeddings` interface over local models and hosted APIs.
One chat model interface over every provider. Swapping any of them is a
constructor change, not a rewrite. This is the part that earns its keep.

**2. A composition primitive.** Everything — prompts, models, retrievers, parsers
— implements the same `Runnable` interface: `invoke`, `batch`, `stream`, and the
`|` operator to chain them. You get batching and streaming across the whole
pipeline for free because every link supports them.

**3. The retrieval stack.** Document loaders, text splitters, retrievers, and the
glue that turns "a folder of PDFs" into "chunks in a vector store". This is the
most mature part of the library and the reason most people install it.

**What LangChain is not, despite the docs you'll find:** the agent framework. That
moved to LangGraph — which is Project 4. Any tutorial showing `AgentExecutor` is
describing a deprecated path.

## 🔁 What it replaces from Project 1

| Project 1 (by hand) | LangChain |
|---|---|
| `pypdf` extraction + custom chunker (Mini 5) | Document loaders + `RecursiveCharacterTextSplitter` |
| `sentence-transformers` called directly (Mini 3) | `Embeddings` interface, same local model underneath |
| Hand-written pgvector SQL (Mini 4) | `PGVector` store + `.as_retriever()` |
| Manual prompt assembly + context injection | Prompt templates composed with `|` |
| Custom streaming plumbing | `.stream()` on the whole chain |
| Provider locked into the Anthropic SDK | Provider as a config string |

## 🛑 What it does NOT replace

This half matters more, and it's what the project is really testing.

| Still yours | Why |
|---|---|
| **The Redis cache (Mini 2)** | LangChain has caching, but keyed on the LLM call. Your cache is keyed on the *query*, which is where the hit ratio lives. |
| **Chunk size and overlap** | The splitter takes the numbers; it doesn't choose them. That decision is still measured against your eval set. |
| **Retrieval quality** | `as_retriever()` returns *something* for every query. Whether it's the right something is your problem. |
| **Knowing what was retrieved** | A chain hides the intermediate steps by default. Citations and "why did it answer that" need you to open it back up. |
| **Cost and token accounting** | The abstraction makes it easy to stop noticing how many calls a query makes. |
| **Refusing to answer** | "Answer only from context, refuse when insufficient" is a prompt and an eval, not a feature. |

## 🏗️ Architecture

Same shape as Project 1 — deliberately. Only the middle changes.

```
POST /documents/upload → loader → splitter → embeddings → PGVector
POST /chat            → retriever → prompt → ChatAnthropic → stream
                             ↑
                    Redis cache (still yours)
```

## 📚 Tech Stack

- **langchain-core** — the `Runnable` interface and base abstractions
- **langchain-anthropic** — `ChatAnthropic` (`claude-opus-5`, same as Project 1)
- **langchain-postgres** — `PGVector` over the same database
- **langchain-huggingface** — the same local `all-MiniLM-L6-v2`, 384-D
- **langchain-text-splitters** — chunking
- **FastAPI**, **Redis**, **PostgreSQL + pgvector** — unchanged from Project 1
- **LangSmith** — optional, and worth one afternoon: it shows the intermediate
  steps a chain hides

Install per-integration packages, not the `langchain` metapackage. The split is
the library telling you what you actually depend on.

## 🚀 Quick Start

```bash
uv sync
cp ../project-1-rag-assistant/.env .env     # same DB, same corpus, same key
docker compose up -d
uv run uvicorn app.main:app --reload
```

The corpus is the same one Project 1 indexed: a rulebook the base model doesn't
know, with verifiable answers. Same reasons as before — see Project 1's README.

## 🗺️ Phases

1. **Ingestion on LangChain** — loader, splitter, `PGVector`. Index the same
   corpus into a separate collection and diff the chunks against Project 1's.
2. **Retrieval and the chain** — retriever + prompt + model composed with `|`.
3. **Streaming and citations** — get back what the chain hid: which chunks fed
   the answer.
4. **Plugging the cache back in** — the Redis layer LangChain doesn't cover.
5. **Run the eval** — the same set, the same metric, both implementations.
6. **The swap test** — change the vector store, then the provider, and time it.
   This is the one experiment that isolates what you're actually paying for.

## 📊 How you measure

The eval set from Project 1 is the instrument. Fill this in:

| | Project 1 | Project 3 |
|---|---|---|
| Lines of application code | | |
| Direct dependencies | | |
| Eval accuracy | | |
| p50 latency | | |
| Tokens per query | | |
| Time to swap vector store | | |
| Time to swap LLM provider | | |

Two rows are the whole point. **Accuracy** should come out roughly equal — if
LangChain is much worse, you configured the splitter differently; if it's much
better, Project 1 has a bug worth finding. The swap rows are where the framework
wins, and by a lot.

## ⏱️ Timeline

6-8 hours. It is a rebuild of something you already understand, which is exactly
why it's fast and exactly why it teaches.

## ✅ Completion Checklist

- [ ] Same corpus indexed through LangChain
- [ ] Chat endpoint answering with citations
- [ ] Redis cache still in front
- [ ] Eval run on both implementations, results recorded
- [ ] Vector store swapped once, timed
- [ ] Provider swapped once, timed
- [ ] `APRENDIZAJES.md` with the comparison table filled in

## 🎓 You're done when you can answer

- Which part of Project 1 did LangChain genuinely replace, and which part did it
  only rename?
- What does a chain hide that you needed back, and what did getting it back cost?
- If accuracy is identical and the code is shorter, what did you give up?
- When would you *not* reach for this — and is "we only ever use one provider" a
  good enough reason?

---

**Made as part of Sr Backend Roadmap** 🚀

Start: after Project 1 · Duration: 6-8 h · Result: a measured opinion about a
framework everyone has an unmeasured one about
