# 🗺️ PROJECT 4 — Plan por fases

> **Estado:** índice del plan. Cada fase se detalla cuando la vamos a hacer.

El README describe 6 fases y 6-8 horas. Este plan las reparte en dos modos, con
una regla explícita:

- **Se construye** lo que implica una *decisión* que vas a tener que volver a
  tomar. Se corre, se rompe, se verifica.
- **Se documenta** en `CONCEPTOS.md` lo que es una *forma de API* que vas a
  buscar cuando la necesites. Snippet corto, para qué sirve, con qué se agrupa,
  cuándo no usarlo, y su equivalente en lo que ya sabés.

La regla viene de P3: los errores que enseñaron algo salieron de **correr**
cosas. Un snippet que no se ejecuta es un snippet que no sabés si está bien —
por eso los snippets van sobre APIs estables, nunca sobre integraciones.

**Presupuesto: 4-5 horas** en vez de 6-8.

---

## El hilo conductor

**Una interfaz y un operador.**

Todo en LangChain —prompts, modelos, retrievers, parsers, una función tuya— es
un `Runnable`, y por eso se puede componer con `|`. Las otras tres ideas del
README (capa de integración, stack de retrieval, lo que sigue siendo tuyo) son
consecuencias de esa.

En Project 1 escribiste el pipeline **ejecutándolo** línea por línea. Acá lo vas
a **declarar**. La pregunta de todas las fases es la misma: *¿qué me dio
declararlo, y qué me costó?*

---

## Fases

### Parte A — Se construye (4-5 h)

| Fase | Tema | Depende de |
|------|------|-----------|
| 0 | Esqueleto: `uv`, Postgres+pgvector, Redis, `.env`, corpus a mano | — |
| 1 | Ingesta: loader → splitter → `init_embeddings` → `PGVector`. Leer las tablas que creó | 0 |
| 2 | La cadena: `RunnableParallel` + prompt + modelo + parser, compuesto con `\|` | 1 |
| 3 | Streaming y citas: `.stream()` end to end, y recuperar qué chunks alimentaron la respuesta | 2 |
| 4 | **El swap test**: cambiar el provider de embeddings, con cronómetro | 2 |
| 5 | Cierre: verificación manual + `APRENDIZAJES.md` | todas |

### Parte B — Se documenta en `CONCEPTOS.md`

| Tema | Por qué no se construye |
|---|---|
| Cache de Redis delante de la cadena | Ya lo construiste en mini-2 y en P1. La conclusión —que LangChain cachea la *llamada al LLM* y no la *query*— se entiende leyéndola. |
| Eval con `chain.batch()` | P8 cubre evals en serio, y en P3 ya viste `Dataset`/evaluadores. Acá sólo cambia que `batch()` paraleliza toda la cadena. |
| Swap de vector store y de LLM | El primer swap (fase 4) ya prueba la tesis. Los otros dos son la misma línea sobre otro constructor. |
| LangSmith | Es Logfire con otro nombre y ya lo instrumentaste en P3. |
| `RunnableLambda`, `RunnableBranch`, `.with_fallbacks()`, `.with_retry()` | APIs estables, se buscan cuando hacen falta. |
| Loaders que no usamos (Notion, S3, HTML) | Catálogo, no concepto. |

**El formato de cada entrada:**

````markdown
### `RunnablePassthrough` — pasar la entrada sin tocarla

**Sirve para:** que un paso posterior reciba el input original además del
resultado de otra rama.

**Se agrupa con:** `RunnableParallel` (ramas concurrentes) y `RunnableLambda`
(meter una función tuya en la cadena).

```python
chain = (
    {"context": retriever, "question": RunnablePassthrough()}
    | prompt | model | StrOutputParser()
)
```

**Cuándo NO:** si el paso siguiente sólo necesita el resultado. Ahí es `|` pelado.
**En P1 esto era:** pasar la variable a mano al `f-string` del prompt.
````

---

## Las decisiones, ya tomadas

| # | Pregunta | Respuesta | Fase |
|---|---|---|---|
| 1 | ¿Embeddings? | **VoyageAI** `voyage-3.5-lite`. Anthropic no tiene embeddings, así que este provider es inevitable. Free tier generoso. | 0 |
| 2 | ¿Modelo de chat? | **Anthropic** `claude-haiku-4-5`, no Groq. Ya tenés la key y cumple el mismo rol. Una cuenta nueva en vez de dos. | 0 |
| 3 | ¿Async o sincrónico? | **Async**, como P3. FastAPI y los `a*` de todo `Runnable`. | 0 |
| 4 | ¿Vector store? | **`PGVector`** de `langchain-postgres`. ⚠️ `postgresql+psycopg://`, no `asyncpg`. | 1 |
| 5 | ¿Qué swap se hace? | **El de embeddings** (Voyage → otro). Es el que obliga a re-indexar, o sea el caro y el que enseña. | 4 |
| 6 | ¿Tests automatizados? | No. Verificación a mano, igual que P2 y P3. | 5 |

> **Pendiente:** el corpus de Project 1 no está versionado en el repo — se subía
> por la API. Hay que tener los archivos a mano para la fase 0. El set de
> preguntas sí está, en `projects/project-1-rag-assistant/evals/preguntas.json`.

---

## Qué vas a aprender

1. **`|` construye un `RunnableSequence`, no ejecuta nada.** La cadena es un
   valor. Por eso `stream`, `batch` y `async` salen gratis: son formas de
   recorrer la misma estructura.

2. **La composición es concurrencia declarada.** `RunnableParallel` corre las
   ramas a la vez. En P1 eso lo hubieras escrito con `asyncio.gather` y a mano.

3. **El provider es un string.** `init_embeddings("voyageai:…")` /
   `init_chat_model("anthropic:…")`. La fase 4 le pone un número a eso —
   y también al costo escondido: re-indexar el corpus entero.

4. **Una cadena esconde los pasos intermedios.** Recuperar las citas (fase 3) es
   *des-abstraer* lo que acabás de abstraer. Ese ida y vuelta es el costo real
   de componer en vez de ejecutar.

5. **LangChain da plomería, no criterio.** Chunk size, umbral de similitud,
   estrategia de cache y "cuándo negarse a contestar" siguen siendo tuyos. El
   `.as_retriever()` devuelve *algo* siempre; si es lo correcto es tu problema.

---

## Lo que este proyecto NO hace

- **No hay agente, ni loop, ni nada que sobreviva al request.** Eso es P5 y P6.
- **No mejora el RAG de P1.** El objetivo no es mejor recall, es ver qué hacía
  la abstracción.
- **No compara líneas de código.** Se comparan decisiones.
- **No monta evals en serio.** Eso es P8.

---

## ⏱️ Timeline

| Parte | Horas |
|---|---|
| A — construir | 4-5 |
| B — documentar | se escribe en paralelo |
| **Total** | **4-5** |

---

## 📊 Tabla de APRENDIZAJES

| Pregunta | Fase |
|---|---|
| Líneas de código de aplicación para el pipeline | 5 |
| Dependencias directas | 5 |
| Tiempo para cambiar el provider de embeddings | 4 |
| Qué se rompió que no se veía desde afuera | 3, 4 |
| Qué tuviste que des-abstraer para poder entregar | 3 |
| Qué hace `\|` realmente, y por qué el streaming atraviesa todo | 2, 3 |

Las dos del medio son las interesantes. Las de tiempo van a dar minutos, y ese
es el punto — pero también lo es lo que costó llegar ahí.
