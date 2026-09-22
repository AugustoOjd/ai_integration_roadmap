# 📘 Project 3 — Resumen de lo aprendido

Pydantic AI, de punta a punta: el agente tipado a fondo y el resto del ecosistema
por encima. Este archivo es el mapa de qué se construyó, por qué, y dónde mirar.

---

## 🎯 El resumen en un párrafo

En Project 2 el loop del agente era tuyo: registry a mano, JSON Schema escrito
dos veces, contexto propio, serialización propia. Pydantic AI invierte la
dirección: **declarás los tipos y el framework deriva el resto**. Lo que este
proyecto demuestra es que esa inversión es real para el *loop* —schema,
validación, reintentos, pausas, historial— y **no lo es** para el *proceso*:
idempotencia, estado durable, presupuesto entre corridas y autorización siguen
siendo tuyos, exactamente igual que antes.

---

## 🗂️ Qué hicimos, por qué, y dónde

### Base

| Archivo | Qué hace | Por qué así |
|---|---|---|
| [`app/core/config.py`](app/core/config.py) | Settings desde `.env` | Las keys se exportan a `os.environ` porque **el `.env` no es el entorno** y cada SDK mira ahí. Sin eso, `Agent("anthropic:…")` explota al construirse. |
| [`app/core/db.py`](app/core/db.py) | Engine async + `SessionFactory` | Async y no sincrónico como P2: no hay worker, y Pydantic AI es async-first. |
| [`app/core/models.py`](app/core/models.py) | `customers`, `orders`, `conversations` | `Numeric` y no `Float` para plata. `lazy="raise"` porque en async un lazy load implícito tira `MissingGreenlet`. |
| [`app/seed.py`](app/seed.py) | 3 clientes, 7 órdenes | Ids fijos (`cus_ana`, `ord_bruno_1`) para tipearlos a mano. Cada cliente es un caso de prueba, no relleno. |

### El agente

| Archivo | Qué hace | Por qué así |
|---|---|---|
| [`app/agent/deps.py`](app/agent/deps.py) | `Deps(session_factory, customer_id, role)` | Lleva la **fábrica** y no una sesión: el framework corre las tool calls de un turno en paralelo, y una `AsyncSession` compartida revienta. |
| [`app/agent/triage.py`](app/agent/triage.py) | El agente, `Triage`, el toolset, `recent_orders`, `refund` | Las tools viven en un `FunctionToolset` filtrable, no colgadas del agente. |
| [`app/agent/history.py`](app/agent/history.py) | `cargar` / `guardar` con `ModelMessagesTypeAdapter` | No inventamos formato: el del framework es el único que él sabe releer. |
| [`app/cli.py`](app/cli.py) | Punto de entrada: run, aprobación, límites, traza | El ciclo de aprobación es un `while`, no un `if`: un run reanudado puede frenarse otra vez. |

### Instrumentación y demos

| Archivo | Fase | Qué muestra |
|---|---|---|
| [`app/schema.py`](app/schema.py) | 1, 3 | El JSON Schema derivado, por rol. Sin llamar a la API. |
| [`app/retry_demo.py`](app/retry_demo.py) | 2 | `ModelRetry` forzado con `FunctionModel`. |
| [`app/history_dump.py`](app/history_dump.py) | 4 | Qué hay realmente en el historial serializado. |
| [`app/providers.py`](app/providers.py) | 5 | `model.profile` comparado, y `FallbackModel` cayendo. |
| [`app/core/telemetry.py`](app/core/telemetry.py) | 7 | Logfire sobre agente y SQLAlchemy. |
| [`app/inside.py`](app/inside.py) | 8 | El run nodo por nodo con `agent.iter()`. |
| [`app/graph_demo.py`](app/graph_demo.py) | 9 | `pydantic-graph` suelto, con diagrama Mermaid. |
| [`app/embeddings_demo.py`](app/embeddings_demo.py) | 10 | `embed_query` vs `embed_documents`. |
| [`app/mcp_server.py`](app/mcp_server.py) · [`app/mcp_demo.py`](app/mcp_demo.py) | 11 | Una tool que vive en otro proceso. |
| [`app/interfaces.py`](app/interfaces.py) | 12 | El mismo agente en CLI, web y streaming. |
| [`app/image_demo.py`](app/image_demo.py) | 13 | Una capability con fallback entre providers. |
| [`app/evals_demo.py`](app/evals_demo.py) | 14 | Casos, juez y evaluador de **trayectoria**. |

---

## ✅ Qué casos cubrimos

### Seguridad y alcance

| Caso | Cómo se resolvió | Dónde |
|---|---|---|
| El modelo pide órdenes de otro cliente | No puede nombrarlo: `customer_id` es dependencia, no argumento | `triage.py` · `recent_orders` |
| El modelo inventa un `order_id` ajeno | `order_id` **sí** es nombrable → filtro en el `WHERE`, y una orden ajena responde igual que una inexistente | `triage.py` · `_orden_del_cliente` |
| Un cliente no debería poder reembolsar | La tool **no existe** en ese run: `.filtered()` por `ctx.deps.role` | `triage.py` · `_visible` |
| Una tool sensible no debe correr sola | `requires_approval=True` → el run termina con `DeferredToolRequests` | `triage.py` + `cli.py` |

### Validación

| Caso | Mecanismo | Cuándo actúa |
|---|---|---|
| Monto negativo | `Annotated[Decimal, Field(gt=0)]` | Antes de entrar a la función |
| Monto mayor al total | `ModelRetry` | Vuelve al modelo como un turno |
| Orden cancelada | `ModelRetry` | Ídem |
| `priority` fuera de 1–5 | `Field(ge=1, le=5)` en el `output_type` | Al validar la salida |

### Continuidad

- Conversación que sobrevive al proceso — `--conversation conv_xxx`
- Rechazo humano que el modelo procesa y explica — `--approve none`
- Run cortado por presupuesto — `--max-requests 1`
- Provider caído — `FallbackModel`

---

## 🔧 Qué funcionalidad quedó andando

```bash
uv run python -m app.seed                    # base + datos
uv run python -m app.schema                  # schema derivado, gratis
uv run python -m app.cli "…"                 # un run completo
uv run python -m app.cli --role agent --trace "…"
uv run python -m app.cli --conversation conv_xxx "…"
uv run python -m app.history_dump conv_xxx --raw
uv run python -m app.retry_demo              # ModelRetry determinista
uv run python -m app.providers               # perfiles de modelos
uv run python -m app.inside "…"              # el grafo por dentro
uv run python -m app.graph_demo              # pydantic-graph suelto
uv run python -m app.embeddings_demo
uv run python -m app.mcp_demo "…"
uv run python -m app.interfaces cli|web|stream
uv run python -m app.evals_demo
uv run python -m app.image_demo              # requiere OPENAI_API_KEY
```

---

## 💡 Casos de uso reales de cada pieza

**`output_type` tipado** — cuando la salida del agente va a un `INSERT` o a un
`if`. Elimina el `try: json.loads(...)` defensivo y el "por favor respondé JSON".

**`RunContext[Deps]`** — todo sistema multi-tenant. La identidad del que llama
nunca debe ser un parámetro que el modelo pueda escribir.

**Toolsets filtrados** — planes con features distintos, roles, permisos.
Cambiar qué tools existen por request en vez de rechazar llamadas.

**`ModelRetry`** — APIs con reglas de negocio que el modelo no puede conocer de
antemano (stock, cupos, límites). Ojo: presupuesto default de **1** reintento, y
un retry insatisfacible es un deadlock caro.

**`requires_approval`** — cualquier acción con plata, datos personales o efectos
externos. **No autoriza**: frena al modelo. La autorización va en la función.

**Historial serializado** — soporte multi-turno, handoff a humano, auditoría.

**`FallbackModel`** — continuidad ante caída del provider.

**Logfire** — post-mortem de "contestó mal" (que no genera ninguna excepción),
costo desagregado, alertas sobre tasa de reintentos, latencia con culpables.

**`agent.iter()`** — progreso incremental, cortes propios, interceptar tool
calls antes de que corran, debuggear una decisión rara.

**`pydantic-graph`** — flujos donde los pasos los decidís vos y no el modelo.

**MCP** — tools que mantiene otro equipo u otra empresa, sin importarlas.

**`pydantic-evals`** — regresiones de prompt, y evaluar la **trayectoria**: que
el agente haya consultado la base en vez de acertar adivinando.

---

## ⚖️ Las conclusiones

### Lo que el framework te dio

1. **El schema se deriva de la firma y el docstring.** Nada escrito dos veces,
   nada que pueda driftear.
2. **`ctx` no aparece en el schema.** No es una puerta cerrada, es una pared: el
   modelo no puede pedir lo que no puede nombrar.
3. **Un argumento inválido es un turno, no una excepción.**
4. **El toolset es un valor componible**, no una lista fija.
5. **Una pausa es un valor en el sistema de tipos**, no un flag en una tabla.
6. **El `output_type` es una tool más** — `final_result` en la traza. La salida
   tipada y las tools son el mismo mecanismo.
7. **El `Agent` es un `pydantic-graph`.** `ModelRequestNode` ⇄ `CallToolsNode`
   es literalmente tu `while` de P2.

### Lo que sigue siendo tuyo

| | Por qué |
|---|---|
| **El proceso** | Corre en el tuyo. Que lo invoque un worker le es invisible. |
| **Idempotencia** | `refund` corrido dos veces reembolsa dos veces. Lo vimos fallar en vivo. |
| **Presupuesto entre runs** | `UsageLimits` es por run y en memoria. |
| **Autorización** | Aprobar frena al modelo; no autoriza nada. |
| **Qué tool es sensible** | `requires_approval=True` es un interruptor, no una política. |
| **Durabilidad de la pausa** | `DeferredToolRequests` vive en memoria. Serializarlo es tuyo. |

### El trade que hay que decidir

El historial es **la representación de Pydantic AI**, no los bloques del
provider. Ganás poder continuar un hilo con otro modelo sin tocar nada. Perdés
poder reproducir la llamada original contra la API cruda desde tu tabla: hay un
traductor en el medio, y lo mantiene otro.

---

## 🐛 Los errores que enseñaron algo

Vale la pena que queden anotados: ninguno fue un typo.

| Error | Lo que reveló |
|---|---|
| `UserError: Set ANTHROPIC_API_KEY` | El string `"anthropic:…"` se resuelve **al construir el Agent**, y el `.env` no es `os.environ`. |
| `InvalidRequestError: concurrent operations` | El framework **paraleliza las tool calls** de un turno. Una sesión viva en `Deps` es un bug latente. |
| `Tool 'refund' exceeded max retries count of 1` (en `app.schema`) | `TestModel` ejecuta todas las tools con argumentos inventados. Tus defensas funcionaban demasiado bien. |
| `Tool 'refund' exceeded max retries` (en `retry_demo`) | El demo **no era idempotente**: estado de una corrida anterior. La fila de la tabla, en vivo. |
| El modelo nunca disparó el `ModelRetry` | Un buen tipo de retorno (`total` en `OrderView`) le evita el error al modelo. `ModelRetry` es red, no flujo. |
| `logfire.instrument_sqlalchemy()` sin el extra | Cada integración de OTel es un paquete aparte. Pydantic AI no lo necesita porque emite OTel de fábrica. |
| `override(toolsets=…)` reemplaza | No suma. Componer requiere pasar el propio también. |
| `LLMJudge` pidiendo `OPENAI_API_KEY` | El juez tiene su propio modelo, con default distinto al de tu agente. |
| `span_tree` vacío | Los evaluadores de trayectoria **dependen** de la instrumentación. Tracing y evals son la misma pieza. |

---

## 📊 Tabla de APRENDIZAJES

| Pregunta | Respuesta |
|---|---|
| Qué hay en el schema derivado, y qué no | Solo los argumentos del modelo (`limit`, `order_id`, `amount`) con descripciones del docstring. **No** está `ctx`. |
| Qué pasó con argumentos inválidos | `ModelRetry` los devuelve como turno. Con presupuesto de 1 por default. |
| Cómo decidís qué tools ve cada quien | `.filtered(pred)` sobre el toolset, evaluado por run. La tool no existe, no es rechazada. |
| Qué contiene el historial serializado | La representación propia del framework: `kind` request/response, `part_kind` por parte. No los bloques del provider. |
| Cuánto tardaste en cambiar de provider | Dos líneas (extra del paquete + `AGENT_MODEL`). Lo no previsto: la credencial del provider nuevo. |
| Cómo se representa una pausa | `DeferredToolRequests` como valor de retorno, en memoria. |
| Cuánto tardaste en agregar una tool | Una función con type hints y docstring. Cero schema. |
| Qué faltaría para correrlo en un worker | Idempotencia por `tool_call_id`, persistir la pausa, presupuesto en base, estado de tarea, reintentos del job. |
| Qué te ató el ecosistema | El formato del historial y las *capabilities*. Lo que NO te ata: tipos y tools son Python normal. |

---

## ⏭️ Qué sigue

**P4 (LangChain Core)** vuelve sobre embeddings y retrieval; **P5** sobre MCP;
**P6 (LangGraph)** sobre grafos y estado durable; **P8** sobre evals. Todos con
el otro ecosistema.

La pregunta con la que llegás a P4 ya no es "¿cómo se hace un agente?" sino
**"¿qué me está dando esto que Pydantic AI no me daba, y qué me cobra a cambio?"**
