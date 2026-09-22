# 📎 Conceptos — lo que no construimos

Cada entrada: **para qué sirve**, **con qué se agrupa**, un snippet, **cuándo no
usarlo**, y **en P1 esto era** — el ancla contra lo que ya hiciste a mano.

No están construidos porque son forma de API, no decisiones. Lo que sí se
construyó está en [FASES.md](FASES.md) Parte A.

---

## Composición

### `RunnableLambda` — una función tuya como eslabón

**Sirve para:** meter Python normal en el medio de una cadena. Cualquier
callable se convierte solo cuando lo ponés después de un `|`.

**Se agrupa con:** `RunnableParallel` (ramas), `RunnablePassthrough` (pasar sin
tocar).

```python
from langchain_core.runnables import RunnableLambda

chain = retriever | RunnableLambda(formatear) | prompt | modelo
# Equivalente, porque el `|` lo envuelve solo:
chain = retriever | formatear | prompt | modelo
```

**Cuándo NO:** si la función hace I/O bloqueante. Rompe el streaming y bloquea
el event loop. Usá la versión async.

**En P1 esto era:** llamar la función. Sin envoltorio, sin nada.

---

### `RunnableBranch` — un if declarado

**Sirve para:** rutear a cadenas distintas según la entrada. Una pregunta sobre
políticas va al RAG; un saludo va directo al modelo sin recuperar nada.

**Se agrupa con:** `RunnableLambda` para la condición.

```python
from langchain_core.runnables import RunnableBranch

chain = RunnableBranch(
    (lambda x: len(x) < 15, cadena_directa),   # (condición, cadena)
    cadena_rag,                                 # default
)
```

**Cuándo NO:** con más de tres ramas o con estado entre ellas. Eso es LangGraph
(P6): `RunnableBranch` no tiene memoria ni ciclos.

**En P1 esto era:** un `if` en el handler.

---

### `.with_fallbacks()` — plan B ante error

**Sirve para:** que la cadena siga funcionando si un provider se cae.

**Se agrupa con:** `.with_retry()`, que reintenta el mismo en vez de cambiar.

```python
from langchain.chat_models import init_chat_model
from langchain_core.output_parsers import StrOutputParser

parser = StrOutputParser()   # AIMessage → str, el mismo de chain.py

principal = init_chat_model("anthropic:claude-haiku-4-5") | parser
suplente = init_chat_model("openai:gpt-4o-mini") | parser

chain = prompt | principal.with_fallbacks([suplente])
```

El parser va **adentro** de cada rama, no después del `with_fallbacks`. Así las
dos ramas devuelven lo mismo —un string— y quien consume la cadena no se entera
de cuál contestó. Si lo pusieras afuera funcionaría igual acá, pero deja de
funcionar en cuanto las ramas necesiten parsers distintos.

**Cuándo NO:** para rate limits. Ahí querés `.with_retry()` con backoff, no
cambiar de modelo — el fallback te cambia la calidad de la respuesta sin avisar.

**En P1 esto era:** un `try/except` alrededor de la llamada.

**Equivalente en P3:** `FallbackModel(roto, sano)`. Misma idea, otra sintaxis.

---

### `.with_retry()` — reintentar el mismo eslabón

```python
chain = (retriever | formatear).with_retry(
    stop_after_attempt=3,
    wait_exponential_jitter=True,
)
```

**Cuándo NO:** sobre algo que escribe sin idempotencia. Reintentar un `INSERT`
lo duplica — la misma lección de P3 con `refund`.

> ⚠️ Esto existe sobre `Runnable`. **No existe sobre `Embeddings`**: la interfaz
> no es un Runnable, y por eso en [`swap.py`](app/swap.py) el backoff está
> escrito a mano.

---

## Ejecución

### `.batch()` / `.abatch()` — evals en una llamada

**Sirve para:** correr la cadena entera sobre N entradas en paralelo, retrieval
incluido.

**Se agrupa con:** el set de preguntas de [`evals/`](evals/preguntas.json).

```python
preguntas = [p["question"] for p in json.load(open("evals/preguntas.json"))]
respuestas = await chain.abatch(preguntas, config={"max_concurrency": 5})

for p, r in zip(preguntas, respuestas):
    ok = all(any(s.lower() in r.lower() for s in grupo) for grupo in p["expect"])
```

**Cuándo NO:** cuando hace falta ver la trayectoria y no sólo la salida. Para
eso son los evaluadores de spans (P3 fase 14, P8 completo).

**En P1 esto era:** [`scripts/evaluate.py`](../project-1-rag-assistant/scripts/evaluate.py),
un `for` con `asyncio.gather`.

> `max_concurrency` importa: sin límite, 18 preguntas son 18 llamadas
> simultáneas y el rate limit te corta. Ya lo viste con Voyage a 3 RPM.

---

### `.astream_events()` — el streaming con detalle

**Sirve para:** ver qué eslabón está emitiendo, no sólo los tokens finales.
Permite mandar al frontend "buscando…" y después los tokens.

```python
async for ev in chain.astream_events(pregunta, version="v2"):
    if ev["event"] == "on_retriever_end":
        yield {"tipo": "fuentes", "docs": ev["data"]["output"]}
    elif ev["event"] == "on_chat_model_stream":
        yield {"tipo": "token", "texto": ev["data"]["chunk"].content}
```

**Cuándo NO:** si sólo querés el texto. `astream()` es más simple.

**Ojo:** esto resuelve el problema de la fase 3 —recuperar las fuentes— **sin**
reestructurar la cadena con `assign`. Dos caminos al mismo lugar: uno cambia la
forma de la cadena, el otro la observa desde afuera.

---

## Cache

### El cache de LangChain **no** es el que te hace falta

**Sirve para:** evitar llamadas repetidas al LLM con exactamente el mismo
prompt.

```python
from langchain_core.globals import set_llm_cache
from langchain_community.cache import RedisCache

set_llm_cache(RedisCache(redis_client))
```

**Cuándo NO:** para lo que realmente querés cachear. La clave de ese cache es el
**prompt armado**, o sea *después* del retrieval. Dos usuarios que preguntan lo
mismo con otras palabras recuperan chunks distintos, arman prompts distintos y
no comparten cache — aunque la respuesta sea la misma.

El cache que mueve el hit ratio va **antes de la cadena**, con la query como
clave:

```python
async def responder(pregunta: str) -> str:
    clave = f"rag:{hashlib.sha256(pregunta.lower().strip().encode()).hexdigest()}"
    if (hit := await redis.get(clave)):
        return hit
    r = await chain.ainvoke(pregunta)
    await redis.setex(clave, 3600, r)
    return r
```

**En P1 esto era:** exactamente eso, y sigue siendo tuyo. Es la primera fila de
"lo que sigue siendo tuyo" del README, y la más fácil de pasar por alto porque
la librería *tiene* algo llamado cache.

---

## Los swaps que no hicimos

### Cambiar el vector store

```python
# Postgres
from langchain_postgres import PGVector
vs = PGVector(embeddings=emb, connection=url, collection_name=col)

# Qdrant — la cadena no se entera
from langchain_qdrant import QdrantVectorStore
vs = QdrantVectorStore.from_existing_collection(embedding=emb, url=..., collection_name=col)
```

Lo que **no** cambia: `as_retriever()`, la cadena, el prompt, el formateador.

Lo que **sí** cambia y nadie migra por vos: los datos. Hay que re-indexar, y la
metadata filtrable puede no soportar los mismos operadores.

**En P1 esto era:** reescribir el SQL del `<=>` y el `ORDER BY`.

---

### Cambiar el LLM

```python
# .env
CHAT_MODEL=openai:gpt-4o-mini
```

Una línea, cero re-indexado — es el swap **barato**, y por eso es el menos
informativo. El caro es el de embeddings, que es el que sí medimos en la fase 4.

**Lo que cambia sin avisar:** el prompt de negativa. *"Decí exactamente: No
encuentro esa información"* lo obedece cada modelo a su manera. Un swap de LLM
sin correr el set de preguntas es un cambio a ciegas.

---

## Observabilidad

### LangSmith

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
```

Sin una línea de código: toda cadena se traza sola. Se ven los pasos
intermedios que la cadena esconde — qué chunks trajo el retriever, qué prompt
salió armado, cuántos tokens.

**Cuándo NO:** si ya tenés OpenTelemetry. LangSmith es su propio backend.

**Equivalente en P3:** Logfire. Misma función, y las mismas dos preguntas que
sólo el tracing contesta: por qué contestó eso, y cuánto costó.

---

## La regla que queda

Todo lo de este archivo es **plomería**: composición, ejecución, reintentos,
providers. LangChain lo hace bien y te ahorra escribirlo.

Nada de esto elige el `chunk_size`, decide cuándo negarse a contestar, ni te
avisa que el retrieval trajo 3 de 4 chunks de ruido. Eso es criterio, y no hay
import que lo traiga.
