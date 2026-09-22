# 🗺️ PROJECT 3 — Plan por fases

> **Estado de este documento:** es el **índice** del plan. Cada fase se detalla
> (concepto, código, verificación) cuando la vamos a hacer, no antes. Si estás
> leyendo esto buscando el paso a paso de la Fase 4, todavía no existe.

El README describe el proyecto **mínimo**: cinco fases, 5-6 horas, una sola capa.
Este plan lo amplía a propósito. La decisión tomada fue:

- **Profundo** en lo que es propio de P3 — el agente tipado. Se construye, se
  rompe a mano, se verifica.
- **Por encima** en lo que solapa con P4-P8 — embeddings, MCP, evals, grafos,
  interfaces. Una pasada de funcionalidad: qué es, qué API tiene, cómo se ve
  andando. Nada de infraestructura.

El motivo de la asimetría: esos temas **tienen su propio proyecto después**, y
ahí se ven con LangChain. Verlos acá por encima es para que cuando lleguen en
serio ya tengas con qué compararlos. No es ampliar el alcance, es sembrar.

---

## El hilo conductor

**El tipo es el contrato.**

En Project 2 escribiste el loop a mano: un registry que convierte funciones en
JSON Schema, un objeto de contexto que lleva dependencias autenticadas más allá
del modelo, serialización de historial que mantiene apareados los tool calls con
sus resultados. Sabés lo que cuesta cada pieza.

Pydantic AI responde lo mismo al revés: **declarás los tipos y el framework
deriva todo lo demás**. Cada fase de la Parte A es la misma pregunta aplicada a
otra pieza: *¿qué me dio el tipo, y qué me sigue tocando a mí?*

La Parte B es otra pregunta: *¿hasta dónde llega el ecosistema?*

---

## Fases

### Parte A — El agente tipado (profundo)

| Fase | Tema | Depende de |
|------|------|-----------|
| 0 | Esqueleto: `uv`, Postgres, seed, `.env`. Nada de agente todavía | — |
| 1 | Un run, un tipo: `deps_type` + `output_type`, e imprimir el schema derivado | 0 |
| 2 | Tools con dientes: `recent_orders` / `refund` contra filas reales, y `ModelRetry` | 1 |
| 3 | Toolsets: qué tools ve **este** usuario, sin un solo `if` adentro de una tool | 2 |
| 4 | Historial: serializar, recargar en otro proceso, continuar | 2 |
| 5 | Modelos y providers: `FallbackModel`, `profile`, cambiar de provider de verdad | 1 |
| 6 | Límites y aprobación: `UsageLimits` + el ciclo diferido completo | 2, 4 |
| 7 | Instrumentación: Logfire sobre la fase 6 | 6 |

### Parte B — El ecosistema (por encima)

| Fase | Tema | Depende de |
|------|------|-----------|
| 8 | Por dentro: `agent.iter()` y el grafo que ya estabas corriendo | 2 |
| 9 | `pydantic-graph` suelto: un grafo propio, chico, con su diagrama | 8 |
| 10 | `Embedder`: `embed_query` vs `embed_documents` | 0 |
| 11 | MCP: tools que no son funciones de tu proceso | 3 |
| 12 | Interfaces: `to_cli_sync()`, `clai web`, y streaming de eventos | 2 |
| 13 | Generación de imágenes: una capability que decide el modelo | 2 |
| 14 | `pydantic-evals`: casos, judge, y evaluar la **trayectoria** | 6 |

### Parte C — Cierre

| Fase | Tema | Depende de |
|------|------|-----------|
| 15 | Verificación manual completa + `APRENDIZAJES.md` | todas |

**Dependencias reales:** la Parte A es casi lineal (0→1→2 y de ahí se abre). La
Parte B cuelga de la 2 salvo la 10, que no necesita agente, y la 14, que necesita
algo que valga la pena evaluar.

---

## Las decisiones, ya tomadas

| # | Pregunta | Respuesta | Fase |
|---|---|---|---|
| 1 | ¿Qué modelo? | `claude-haiku-4-5` — el proyecto es sobre tipos, no sobre calidad del modelo | 1 |
| 2 | ¿Qué paquete? | `pydantic-ai-slim[anthropic]`, no `pydantic-ai` (trae todos los providers) | 0 |
| 3 | ¿Infra? | Postgres y nada más. Sin FastAPI, sin Celery, sin Redis | 0 |
| 4 | ¿Segundo provider para la fase 5? | Se decide en la fase 5 | 5 |
| 5 | ¿Tests automatizados? | No. Verificación a mano, igual que P2 | 15 |

---

## Qué vas a aprender (el mapa conceptual)

### De la Parte A

1. **Lo que el modelo puede nombrar, puede mentirlo.** `RunContext[Deps]` no
   aparece en el schema derivado. `customer_id` no es un argumento: es una
   dependencia que inyectaste. Esa ausencia en el JSON Schema **es** la propiedad
   de seguridad, y en la fase 1 la vas a ver impresa en pantalla.

2. **Un argumento inválido es un turno, no una excepción.** `ModelRetry` manda el
   error de vuelta al modelo. Tu registry a mano trataba eso como falla
   permanente. La diferencia entre `raise ModelRetry(...)` y `raise` cualquier
   otra cosa es la fase 2 entera.

3. **Un toolset es un valor, no una lista.** `FilteredToolset`, `WrapperToolset`,
   `CombinedToolset`: el conjunto de tools se **compone por request** según quién
   llama. Es la mejor idea de la librería y el README no la menciona.

4. **El historial es su representación, no los bloques del provider.** Eso es lo
   que lo hace provider-agnostic, y significa que lo que persistís ya no es lo
   que vio la API. No podés replayear un run contra la API cruda desde tu tabla.
   Decidir si ese trade vale la pena es el output real del proyecto.

5. **Una pausa es un valor en el sistema de tipos.** `DeferredToolRequests` sale
   como resultado del run — no es un flag en una tabla. Comparalo con lo que
   hiciste en P2. Y ojo: aprobar frena al *modelo*, no autoriza nada. El cuerpo
   de la tool sigue corriendo cuando la llamada llega, así que la autorización
   sigue yendo adentro de la función.

6. **Lo que sigue siendo tuyo.** El proceso, el estado de la tarea, la
   idempotencia, el presupuesto entre runs, y qué tool es sensible. Reintenta al
   modelo; no reintenta tu trabajo.

### De la Parte B

7. **El `Agent` es un grafo preconfigurado.** `UserPromptNode` →
   `ModelRequestNode` → `CallToolsNode` → `End`. El while-loop que escribiste a
   mano, reificado como nodos que podés interceptar con `agent.iter()`.

8. **Pregunta y documento no se embeben igual.** `embed_query` vs
   `embed_documents` existen porque los modelos asimétricos los codifican
   distinto. Si en P1 usaste la misma llamada para los dos, acá está el porqué.

9. **Capabilities es una tercera categoría.** No son tools ni toolsets:
   `MCP(...)`, `ImageGeneration(...)` son features que el framework resuelve
   nativo-o-fallback según el provider. Es la abstracción más opinada de la
   librería, y la que más te ata.

10. **Evaluar la salida no es evaluar el agente.** `pydantic-evals` puede
    calificar la **trayectoria** — la secuencia de tool calls — y no solo la
    respuesta final. Esa distinción es el puente a P8.

---

## Lo que este proyecto NO hace

Explícito para que no se filtre:

- **No lo corre en un worker.** Sin Celery, sin colas, sin estado de tarea. Eso
  fue P2 y sigue siendo tuyo.
- **No construye un RAG.** La fase 10 llama al `Embedder` y mira el vector. No
  hay pgvector, no hay chunking, no hay retrieval. Eso es P1 y P4.
- **No monta un server MCP.** La fase 11 consume uno.
- **No arma una suite de evals.** La fase 14 corre un dataset de tres casos para
  ver la forma de la API. La suite en serio es P8.
- **No compara líneas de código con P2.** La comparación es de filosofía.

---

## ⏱️ Timeline

| Parte | Horas |
|---|---|
| A — El agente tipado | 6-7 |
| B — El ecosistema | 4-5 |
| C — Cierre | 1 |
| **Total** | **11-13** |

Más largo que las 5-6 h del README, y a sabiendas. Las 6-7 h de la Parte A son el
proyecto tal como está especificado; la Parte B es el recorrido agregado.

---

## 📊 La tabla de APRENDIZAJES

Del README, con las filas que agrega este plan:

| Pregunta | Fase que la contesta |
|---|---|
| Qué hay en el schema derivado de cada tool, y qué no | 1 |
| Qué pasó cuando el modelo mandó argumentos inválidos | 2 |
| Cómo decidís qué tools ve cada usuario | 3 |
| Qué contiene realmente el historial serializado | 4 |
| Cuánto tardaste en cambiar de provider | 5 |
| Cómo se representa una pausa, y dónde vive | 6 |
| Cuánto tardaste en agregar una tool nueva | 2, 3 |
| Qué te faltaría construir para correr esto en un worker | 15 |
| Qué te ató el ecosistema, y qué te ahorró | 15 |

La anteúltima es la fila honesta. Todo lo de arriba es lo que te dieron.
