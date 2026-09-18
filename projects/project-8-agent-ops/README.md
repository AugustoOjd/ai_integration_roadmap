# 📉 PROJECT 8: Agent Ops

**The agent is bad on purpose. The project is making it good — and proving it.**

Every project before this one ends the same way: it works when you try it. That
sentence is doing an enormous amount of unearned work. Works on which inputs? Was
it better than last week? Is it getting worse right now, and would you know?

This project inverts the usual shape. You build a small agent **deliberately
mediocre** — a weak prompt, a vague tool, no guardrails — and then spend the whole
project turning it into something you'd defend in a review. The agent is the
material. The discipline is the deliverable.

## 📌 When to Start

**Prerequisites:** any of Projects 5-7. You need an agent you've shipped and a
moment where you changed a prompt and couldn't tell whether you'd made it better.
That moment is what this project is for.

```
P4  LangChain Core                   LCEL, Runnable, retrieval
P5  LangChain Agents                 create_agent, tools, MCP, middleware
P6  LangGraph                        estado durable, interrupt
P7  Deep Agents                      harness, tareas largas
P8  Agent Ops         ← estás aquí   evals, monitoring, deploy
```

This is last because it's the only one that needs something to operate. It is
also the one that most resembles the job.

## 🎯 The Core

### 1. An eval is a test suite whose assertions are fuzzy

You've probably written a script that runs twenty questions and prints how many
looked right. That's the seed of the idea and it stops scaling almost
immediately: no history, no comparison between runs, no way to tell a regression
from noise.

The discipline version has four parts:

- **A dataset** — inputs with expected outputs, versioned, that grows every time
  production surprises you
- **Evaluators** — the assertion. Exact match where you can; a model-as-judge
  where you can't; a heuristic in between
- **Experiments** — one run of the dataset against one version of the agent,
  stored and comparable
- **Regression detection** — did this change break something that used to work?

The fourth is the one that makes the other three worth building.

### 2. Separate the failures, or you'll tune the wrong thing

The single most useful habit in this whole roadmap: **never score an agent with
one number**. A RAG answer can be wrong because retrieval missed, or because
generation ignored what it found. An agent can fail because it picked the wrong
tool, or called the right one with bad arguments, or got a good result and
summarized it badly.

```
RETR  TOOL  ANSW   question
 ok    ok    ok    ¿cuál es el estado de A17?
 ok    ok    NO    ¿cuánto gasté este trimestre?     ← generation
 NO    --    NO    ¿qué política aplica a envíos?    ← retrieval
```

Each column points at a different fix. One aggregate number points at nothing.

### 3. A trace is the primary source

Logs tell you what your code did. A trace tells you what the *agent* did: every
turn, every tool call, every retry, nested, with timings and token counts. For a
multi-step agent this isn't a nice-to-have — reading a sub-agent's reasoning out
of stdout is not a thing anyone does twice.

The operational loop the whole project builds toward:

```
traza en producción → hipótesis → experimento contra el dataset
        ↑                                      ↓
   monitorizar  ←──────────  desplegar si mejora sin regresiones
```

### 4. Cost and latency are product decisions

Tokens per run, calls per run, p50 and p95. A change that improves accuracy two
points and triples cost is a decision someone has to make — and they can't make it
if nobody measured.

## 🛑 What stays yours

| Still yours | Why |
|---|---|
| **What "correct" means** | An evaluator encodes a judgment you made. The tool runs it; it doesn't have it. |
| **The dataset** | This is the actual asset. It's the accumulated memory of everything that went wrong. |
| **The threshold to ship** | "95% and no regressions" is a policy, not a metric. |
| **Judging the judge** | A model-as-judge is an agent with the same failure modes as the one it's grading. It needs its own eval. |
| **Acting on the alert** | Monitoring tells you quality dropped. Nothing tells you to care. |

## 🏗️ Architecture

```
agente (malo a propósito)
    ├─ instrumentado    → trazas → LangSmith
    ├─ dataset          → casos, versionados, que crecen desde producción
    ├─ evaluadores      → exact match · heurística · model-as-judge
    └─ experimentos     → una corrida = una versión, comparable
                              ↓
                     ¿mejor, sin regresiones?  →  deploy
                              ↑
                        monitoring: calidad, coste, latencia
```

## 📚 Tech Stack

- **langsmith** — trazas, datasets, evaluadores, experimentos
- **langchain** / **langgraph** — el agente de prueba, pequeño
- **openevals** — evaluadores ya escritos, para no empezar de cero
- **pytest** — los evals corren en CI como cualquier otro test que puede fallar
- **GitHub Actions** — porque un eval que solo corres a mano no existe

## 🚀 Quick Start

```bash
uv sync
cp .env.example .env          # LANGSMITH_API_KEY, ANTHROPIC_API_KEY
uv run python -m app.agent "¿cuál es el estado de mi pedido?"   # sí, es malo
uv run python -m evals.run --experiment baseline
```

## 🗺️ Phases

1. **Baseline.** Ship the mediocre agent instrumented. Collect twenty real runs
   and read the traces. Do not fix anything yet — the discipline of looking before
   touching is half the point.
2. **The dataset.** Twenty cases from those traces, including the ugly ones.
   Versioned, in the repo, not in a notebook.
3. **Evaluators.** One exact-match, one heuristic, one model-as-judge. Then grade
   the judge against cases you labelled yourself, and find out how much you trust
   it.
4. **Separate the columns.** Score retrieval, tool choice and answer
   independently. Now the number tells you where to go.
5. **Experiments.** Change one thing — the prompt, the model, a tool description.
   Run it. Compare. Keep it or throw it away **on the evidence**.
6. **Regressions in CI.** Evals on every PR. Break something on purpose and watch
   the build catch it.
7. **Production monitoring.** Cost, latency, quality over time. Set a threshold
   that would actually page you.
8. **Deploy and close the loop.** Ship it, find a failure in a production trace,
   add it to the dataset, fix it, prove the fix. That full circle is the project.

## 📊 What to record in APRENDIZAJES.md

| Question | Your answer |
|---|---|
| Baseline score, per column | |
| Final score, per column | |
| A change that helped one column and hurt another | |
| How often the model-as-judge disagreed with you | |
| A regression CI caught that you would have shipped | |
| Cost and p95, before and after | |
| The first case that came from production | |

That last row is the one that means the loop is closed.

## ⏱️ Timeline

10-12 hours. The longest of the track, and the only one whose output is a habit
rather than a codebase.

## ✅ Completion Checklist

- [ ] Agent instrumented, twenty production traces read
- [ ] Versioned dataset in the repo
- [ ] Three evaluators, including a judge you validated
- [ ] Scoring split by failure type
- [ ] Two experiments compared, one of them rejected on the evidence
- [ ] Evals running in CI, with a deliberate regression caught
- [ ] Monitoring on cost, latency and quality
- [ ] One production failure added to the dataset and fixed
- [ ] `APRENDIZAJES.md` with the table filled in

## 🎓 You're done when you can answer

- Why is one aggregate score worse than useless?
- How much do you trust your model-as-judge, and what's the number behind that?
- Which change did you reject despite believing in it, and what convinced you?
- What would you have shipped if CI hadn't stopped you?
- If quality dropped 10% tonight, how long until you knew?

See **[SOURCES.md](./SOURCES.md)** for official docs and related material —
this is the full LangSmith track, the one fewest people do.

---

**Made as part of Sr Backend Roadmap** 🚀

Duration: 10-12 h · Result: the ability to say "this is better" and be believed
