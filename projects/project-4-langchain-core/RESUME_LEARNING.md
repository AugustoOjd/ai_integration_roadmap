# 📘 Project 4 — Resumen de lo aprendido

LangChain Core: una interfaz (`Runnable`) y un operador (`|`). Lo demás del
ecosistema son esas dos ideas aplicadas a sustantivos más grandes.

---

## 🎯 El resumen en un párrafo

En Project 1 el pipeline de RAG lo **ejecutabas** línea por línea. Acá lo
**declarás**: `armar()` devuelve un valor, no un resultado. De eso salen gratis
`invoke`, `batch`, `stream` y los `a*` — cuatro formas de recorrer la misma
estructura. Lo que el proyecto demuestra es que esa inversión es real para la
plomería (composición, providers, streaming, retrieval) y que **nada de lo que
decide la calidad** —chunking, umbral, cuándo negarse, si el retrieval trajo
ruido— cambió de dueño.

---

## 🗂️ Qué hicimos, por qué, y dónde

| Archivo | Qué hace | Por qué así |
|---|---|---|
| [`app/core/config.py`](app/core/config.py) | Settings | Las keys se exportan a `os.environ`: el `.env` no es el entorno. `CHUNK_SIZE` y `RETRIEVER_K` viven acá para poder variarlos contra el set de preguntas sin tocar código. |
| [`app/core/store.py`](app/core/store.py) | Embeddings + `PGVector` | Único lugar donde se nombra un provider. Una colección por espacio vectorial, con el modelo en el nombre. |
| [`app/ingest.py`](app/ingest.py) | loader → splitter → store | `--dry-run` para iterar chunking sin gastar API ni destruir el índice. |
| [`app/core/chain.py`](app/core/chain.py) | La cadena | Dos versiones: `armar()` devuelve texto; `armar_con_fuentes()` conserva los `Document`. |
| [`app/ask.py`](app/ask.py) | Preguntar | Flags de andamiaje (`--graph`, `--sources`, `--batch`) y de funcionalidad (`--stream`). |
| [`app/tables.py`](app/tables.py) | Inspector | Qué tablas creó LangChain sin que escribieras un `CREATE TABLE`. |
| [`app/swap.py`](app/swap.py) | El experimento | Instrumento de medición, no feature. Se borra sin romper nada. |
| [`corpus/`](corpus/) | 5 políticas de Nordix | Ficticio a propósito: nada es adivinable sin retrieval. |
| [`evals/preguntas.json`](evals/preguntas.json) | 18 preguntas | Con `tipo` y `fuente` esperada, para medir retrieval sin el LLM. |

---

## ✅ Qué casos cubrimos

| Caso | Cómo se resolvió | Dónde |
|---|---|---|
| Indexar un corpus | loader → splitter → embeddings → PGVector | `ingest.py` |
| Iterar el chunking sin gastar | `--dry-run` corta antes de la API | `ingest.py` |
| Responder con contexto | `RunnableParallel` + prompt + modelo + parser | `chain.py` |
| Negarse cuando no sabe | Instrucción en el prompt, no una feature | `chain.py` |
| Citar la fuente | `[archivo.txt]` en el formateador + metadata que sobrevive al chunking | `chain.py` |
| Ver qué chunks alimentaron la respuesta | Reestructurar con `assign` | `armar_con_fuentes()` |
| Streaming end to end | `astream()`, una línea | `ask.py` |
| Varias preguntas a la vez | `abatch()`, una llamada | `ask.py` |
| Comparar dos modelos de embeddings | Colección por modelo + hit rate | `swap.py` |
| Rate limit del provider | Backoff escrito a mano | `swap.py` |

---

## 🔧 Funcionalidad que quedó andando

```bash
docker compose up -d --wait
uv run python -m app.ingest --dry-run          # chunking, sin gastar
uv run python -m app.ingest                    # indexa
uv run python -m app.tables                    # las tablas de LangChain
uv run python -m app.ask "¿…?"                 # una respuesta
uv run python -m app.ask --graph               # qué construyó el `|`
uv run python -m app.ask --stream "¿…?"        # token a token
uv run python -m app.ask --sources "¿…?"       # qué chunks se usaron
uv run python -m app.ask --batch               # tres en paralelo
uv run python -m app.swap --k 1                # el experimento
```

---

## 📈 Los números medidos

| Métrica | Valor |
|---|---|
| Corpus | 5 documentos, ~11 KB, 16 chunks |
| Indexado (voyage-3.5-lite, 1024d) | 2,5 s |
| Búsqueda | 4 ms por consulta (Postgres) |
| Hit rate con k=4 | 17/17 (100%) |
| Hit rate con k=1 | 15/17 (88%) |
| Precisión observada con k=4 | ~1 de 4 chunks relevante |

**El k=4 tapa el problema.** Con `--k 1` aparecen los dos fallos: "reembolso de
150.000" trae devoluciones antes que autorizaciones, y "paquete extraviado" trae
envíos antes que SLA. El chunk correcto está, pero no primero.

---

## 💡 Casos de uso reales de cada pieza

**`Runnable` + `|`** — cuando el pipeline va a tener más de una forma de
ejecutarse. Si sólo vas a llamarlo una vez y de una manera, un `async def` es
más claro.

**`RunnableParallel`** — ramas independientes sobre la misma entrada. Es
`asyncio.gather` declarado.

**`init_chat_model` / `init_embeddings`** — cuando el provider tiene que ser
config. Ojo: registro cerrado, ver abajo.

**Una colección por modelo** — multi-tenant, versionado de corpus, o convivir
dos modelos durante una migración.

**`--dry-run`** — cualquier script destructivo o que gaste. Separar "calcular"
de "aplicar".

**Hit rate sobre fuente esperada** — medir retrieval sin pagar el LLM. Es la
métrica correcta para cambiar embeddings, chunking o k.

**`astream()`** — el endpoint SSE. Es la única flag de `ask.py` que sobrevive a
producción.

---

## ⚖️ Las conclusiones

### Lo que el framework te dio

1. **El `|` construye un grafo, no ejecuta.** La cadena es un valor; se puede
   inspeccionar antes de correrla (`--graph`: 9 nodos, `RunnableSequence`).
2. **Streaming y batching gratis**, porque todos los eslabones implementan la
   misma interfaz. En P1 el SSE se cableó a mano para un solo camino.
3. **Providers como configuración** — con el asterisco de abajo.
4. **El stack de retrieval es la parte madura.** El splitter recursivo cortó bien
   los 5 documentos sin partir una oración.
5. **Dos tablas que nunca declaraste.** El esquema lo eligió la librería.

### Lo que sigue siendo tuyo

| | Evidencia concreta de este proyecto |
|---|---|
| **Chunk size y overlap** | El splitter toma los números; no los elige. |
| **Calidad del retrieval** | 3 de 4 chunks eran ruido y nadie avisó. |
| **Estrategia de cache** | El cache de LangChain se keyea *después* del retrieval. El que sirve va antes, con la query. |
| **Deduplicación** | `add_documents` no deduplica: correr la ingesta dos veces duplica todo. |
| **Índice vectorial** | El store crea la tabla. La estrategia (IVFFlat, HNSW) es tuya. |
| **Reintentos de embeddings** | `Embeddings` no es un `Runnable`: no hay `.with_retry()`. |
| **Cuándo negarse** | Un prompt y una eval. |

**El patrón:** LangChain da **plomería**, no **criterio**.

---

## 🐛 Los errores que enseñaron algo

| Error | Lo que reveló |
|---|---|
| `ValueError: Provider 'voyageai' is not supported` | `init_embeddings` tiene un **registro cerrado** de 10 providers. `langchain-voyageai` implementa `Embeddings` perfectamente (`issubclass` → `True`) pero no está en la lista. **La interfaz es abierta; la capa de strings es un `if` enumerado.** |
| `AssertionError: _async_engine not found` | `PGVector` construye el engine sync **o** el async, nunca los dos. `async_mode=True` habilita los `a*` y deshabilita los sync. Desde la interfaz `VectorStore` los métodos se ven simétricos; la mitad falla según un flag del constructor. |
| `ImportError: Install grandalf to draw graphs` | `get_graph().print_ascii()` necesita una dependencia extra no declarada. Se reemplazó recorriendo `grafo.nodes` a mano. |
| `RateLimitError: 3 RPM` (Voyage free tier) | Dos cosas: **(a)** la interfaz `Embeddings` tiene `embed_documents` en lote pero **no tiene lote para consultas** — 17 preguntas son 17 requests. Voyage sí lo soporta, pero el método está debajo de la interfaz (`_aembed_regular`). **(b)** No hay reintentos: el error sube crudo y el backoff lo escribís vos. |
| Warning de Hugging Face al indexar | El cliente de Voyage baja un tokenizer de 7 MB para contar tokens localmente. La promesa de "embeddings hosted, sin modelos locales" tiene más piezas de las que anuncia. |
| Hit rate 100% con k=4 | Un número que no informa. Bajar a `--k 1` fue lo que hizo visible el problema real. |

---

## 📊 Tabla de APRENDIZAJES

| Pregunta | Respuesta |
|---|---|
| Líneas de aplicación para el pipeline | ~120 útiles (config, store, ingest, chain). La cadena en sí son 8. |
| Dependencias directas | 12, todas por integración. Nunca el metapaquete. |
| Tiempo para cambiar el provider de embeddings | La config, 1 línea. **El costo real es re-indexar**: 2,5 s con 16 chunks, horas con 500.000 documentos. |
| Qué se rompió que no se veía desde afuera | `async_mode` partiendo la interfaz del store al medio; el registro cerrado de `init_embeddings`; la ausencia de lote para consultas. |
| Qué tuviste que des-abstraer para entregar | Las citas. `armar()` pierde los `Document`; recuperarlos obliga a cambiar la forma de la cadena a un dict acumulado con `assign`. |
| Qué hace `\|` realmente | Un `RunnableSequence`. El streaming atraviesa todo porque cada eslabón implementa `stream`. |
| Si el código es más corto y las respuestas iguales, ¿qué entregaste? | Visibilidad. El retrieval con 25% de precisión estaba ahí desde el primer día y sólo apareció al escribir `--sources` a propósito. |

---

## ⏭️ Qué sigue

**P5 (LangChain Agents)** pone un loop encima de esto: `create_agent`,
middleware y MCP. Lo que devuelve `create_agent` es un **grafo**, no un objeto
con `.run()` — y eso es porque está construido sobre LangGraph, que es P6.

La pregunta que llevás: ya sabés qué te da una cadena. **¿Qué te da un agente
que una cadena no puede, y qué te cobra por eso?**
