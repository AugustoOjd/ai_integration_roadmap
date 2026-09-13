# 🔁 Mini 9: Agent Loop — sesiones, permisos y presupuesto

Un agente que **recuerda**, que sabe **de quién** es el trabajo que hace, que
**pide permiso** antes de romper algo, y que no se gasta tu presupuesto.

> Escrito en castellano, como `FASES.md` y `CHECK_LEARNING.md` de los minis
> anteriores.

---

## ⚠️ Lo que este mini NO es

**No es "ahora sí, el agent loop de verdad".** Ese ya lo escribiste, en el mini 8:

| Tema | Dónde ya está |
|---|---|
| El loop `while stop_reason == "tool_use"` | mini 8, Fase 3 |
| Condiciones de parada | Fase 3 |
| Razonamiento multi-paso y encadenar tools | Fase 3 |
| `max_iterations` | Fase 3 (`MaxIterationsError`) |
| Recuperación de errores de tools | Fase 6 (`is_error` + mensaje genérico) |
| Ejecución en paralelo | Fase 6 |

Repetir eso no te enseña nada nuevo. Este mini **parte de ese loop** y le agrega
las cinco cosas que lo separan de algo que puede recibir tráfico real.

El loop sigue siendo **tuyo**, no de un framework, por una razón concreta: el
paso siguiente es PROJECT 2 (Celery + agentes), y ahí vas a necesitar meterte
adentro del loop — persistir estado vuelta a vuelta, reportar progreso, cancelar
a mitad de camino, sobrevivir al reinicio de un worker. Un framework dueño del
loop complica exactamente eso.

---

## 🎯 Qué se aprende

- ✅ **Sesiones multi-turno**: el historial persistido *entre* requests
- ✅ **Inyección de dependencias en tools**: de quién es el dato que la tool toca
- ✅ **Aprobación humana** para tools destructivas
- ✅ **Presupuesto**: topes de tokens y de dinero, no sólo de iteraciones
- ✅ **Crecimiento del contexto**: qué hacés cuando la conversación no entra
- ✅ **`execution_log` persistido**: la traza como dato, no como `print`

Los seis salen del mismo lugar: en el mini 8 cada request era un universo
aislado y sin usuario. Acá hay conversaciones, hay dueños, y hay plata.

---

## 🏗️ Arquitectura

```
POST /sessions/{id}/messages
        │
        ▼
  cargar historial de la sesión desde la DB      ← NUEVO: memoria
        │
        ▼
  ┌─ loop (el del mini 8) ──────────────────────┐
  │   llamar al modelo                          │
  │   ¿pide tools?                              │
  │      ├─ tool sensible -> PAUSAR y pedir OK  │  ← NUEVO: aprobación
  │      └─ tool normal   -> ejecutar con deps  │  ← NUEVO: deps
  │   guardar la vuelta en execution_log        │  ← NUEVO: traza
  │   ¿queda presupuesto?                       │  ← NUEVO: budget
  └─────────────────────────────────────────────┘
        │
        ▼
  guardar el historial actualizado
```

---

## 🧩 Qué escribís vos y qué te cubre Pydantic AI

Este mini es el revés de la Fase 8 del mini 8: allá el framework era el objeto
de estudio; acá es una herramienta que se usa **sólo donde escribirlo a mano no
enseña nada**.

| Pieza | Quién |
|---|---|
| El loop, el historial de una corrida, `max_iterations` | **vos** (mini 8) |
| Qué tools existen y su seguridad | **vos** (mini 8, Fase 5) |
| Persistir la sesión entre requests | **vos** — es tu modelo de datos |
| Decidir qué tool necesita aprobación | **vos** — es política, no técnica |
| Pasarle el usuario autenticado a una tool | **vos** (patrón: `RunContext`) |
| Política de presupuesto y qué hacer al agotarlo | **vos** |
| Recortar el historial cuando no entra | **vos** |
| Contar tokens de un historial | `messages.count_tokens` del SDK |
| Modelo falso para tests | **Pydantic AI** (`TestModel`) o tu fake del mini 8 |
| Streaming del progreso al cliente | SDK (`client.messages.stream`) |

La regla que sale de acá, y que vale más que el mini: **un framework te cubre el
transporte y el contrato; las decisiones son siempre tuyas.** Todo lo que dice
"vos" en esa tabla es política de negocio disfrazada de código.

---

## 📚 Stack

- **FastAPI** — la API
- **Anthropic Claude** (`claude-haiku-4-5`) — el modelo
- **PostgreSQL + SQLAlchemy** — sesiones y `execution_log`
- **Pydantic AI** — sólo `TestModel` en los tests
- Registry, tools y loop **del mini 8**

---

## 🚀 Quick Start

```bash
cp .env.example .env        # y poné tu ANTHROPIC_API_KEY
docker compose up -d        # postgres
uv sync
uv run uvicorn app.main:app --reload
```

---

## 📝 Endpoints

```bash
# 1. Abrir una conversación
POST /sessions
{"user_id": "u_42"}
-> {"session_id": "s_abc", "budget_tokens": 50000}

# 2. Mandar un mensaje (el agente recuerda lo anterior)
POST /sessions/s_abc/messages
{"prompt": "¿Cuánto gasté este mes?"}
-> {
     "answer": "Gastaste $1.240 en 8 pedidos.",
     "iterations": 2,
     "tools_used": ["get_my_orders", "calculate"],
     "usage": {"input_tokens": 1830, "output_tokens": 210},
     "budget_remaining": 47960
   }

# 3. Seguir la conversación: "esos" se resuelve con el historial
POST /sessions/s_abc/messages
{"prompt": "¿Y cuántos de esos fueron con descuento?"}

# 4. El agente quiere hacer algo destructivo: se frena
POST /sessions/s_abc/messages
{"prompt": "Cancelá el pedido 991"}
-> 202 {
     "status": "pending_approval",
     "pending": {"id": "toolu_7", "tool": "cancel_order",
                 "input": {"order_id": 991}}
   }

# 5. Vos decidís
POST /sessions/s_abc/approvals/toolu_7
{"approved": true}
-> {"answer": "Listo, cancelé el pedido 991."}

# 6. La traza completa, para auditar
GET /sessions/s_abc/log
```

---

## 🧠 Los cinco conceptos

### 1. Memoria: la sesión es tu tabla, no del modelo

La API **no guarda nada**. Eso ya lo sabías del mini 8; la consecuencia recién
aparece acá: si querés que el agente recuerde, el historial lo guardás **vos**.

```python
# el loop del mini 8 arrancaba siempre así:
messages = [{"role": "user", "content": prompt}]

# acá arranca así:
messages = await load_history(session_id) + [{"role": "user", "content": prompt}]
```

Y al terminar, guardás. Todo el mini 9 cabe en esa diferencia.

**Lo que se rompe**: los bloques `tool_use` y `tool_result` son parte del
historial y hay que persistirlos tal cual. Si guardás sólo los textos —que es la
tentación, porque es lo legible— rompés la correlación por `tool_use_id` y la
API te rechaza el request siguiente.

### 2. Dependencias: el modelo no puede decir de quién son los datos

Ésta es la pregunta 48 de tu `CHECK_LEARNING.md` del mini 8, y acá se responde.

```python
# ❌ el user_id como parámetro de la tool
def get_my_orders(user_id: str) -> list[dict]: ...
```

Si el `user_id` está en el schema, **lo elige el modelo** — y el modelo lo toma
del texto del usuario. Alguien escribe *"mostrame los pedidos del usuario 7"* y
tu tool obedece. Es un IDOR con un LLM en el medio.

```python
# ✅ el user_id viaja por afuera del modelo
def get_my_orders(ctx: RunContext[Deps]) -> list[dict]:
    return db.orders_for(ctx.deps.user_id)   # del token, no del prompt
```

La regla: **lo que define permisos nunca va en el `input_schema`.** El modelo
elige *qué hacer*; el contexto autenticado define *sobre qué*.

### 3. Aprobación: "el modelo pide, vos ejecutás" en serio

En el mini 8 esa frase era teoría: ejecutabas todo. Acá se vuelve código.

```python
REQUIEREN_APROBACION = {"cancel_order", "send_email", "refund"}
```

El loop se **pausa**: guarda el estado, devuelve 202 con el pedido pendiente, y
espera. Cuando llega la decisión, retoma — y si fue rechazada, le manda un
`tool_result` con `is_error` diciendo que el usuario no autorizó. El modelo lo
entiende y sigue.

**El detalle difícil**: un loop pausado es estado que sobrevive al request. No
podés tener el `for` corriendo mientras esperás. Hay que poder reconstruir la
corrida desde la base — que es, casualmente, el mismo problema que te va a
plantear Celery en PROJECT 2.

### 4. Presupuesto: `max_iterations` no alcanza

Cinco iteraciones con historiales chicos son centavos; cinco con un historial de
100 KB, no. El tope real se cuenta en tokens:

```python
if session.tokens_used + estimado > session.budget_tokens:
    raise BudgetExceededError
```

Y se estima **antes** de mandar, con `client.messages.count_tokens(...)` — que es
gratis. Contar después sirve para la factura, no para evitarla.

### 5. Contexto: toda conversación larga se rompe sola

Haiku 4.5 tiene 200K de ventana. Una sesión larga llega. Las tres salidas, de
peor a mejor:

| Estrategia | Qué hace | Costo |
|---|---|---|
| Ventana deslizante | tira los mensajes viejos | el agente "olvida" de golpe |
| Resumen | pide al modelo que resuma y reemplaza | una llamada extra, pérdida de detalle |
| Recorte selectivo | tira los `tool_result` viejos, guarda el texto | barato y suele alcanzar |

**La trampa**: no podés borrar un `tool_use` sin borrar su `tool_result`, ni al
revés. Vienen de a pares.

---

## 📂 Estructura

```
mini-9-agent-loop/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py                    # NUEVO: engine + sesión de SQLAlchemy
│   ├── models.py                # NUEVO: Session, Message, ExecutionStep
│   ├── agent.py                 # del mini 8 + memoria, deps, aprobación
│   ├── deps.py                  # NUEVO: el contexto autenticado
│   ├── budget.py                # NUEVO: estimación y topes
│   ├── context.py               # NUEVO: recorte del historial
│   ├── tools/                   # del mini 8 + tools con deps y sensibles
│   ├── schemas/
│   └── routes/
│       ├── sessions.py          # NUEVO
│       └── approvals.py         # NUEVO
└── tests/
```

---

## 🧪 Testing

Misma regla que el mini 8: **ningún test llama al modelo**. Lo nuevo a cubrir:

```bash
uv run pytest -v
```

- El historial se persiste y se recarga **con** los bloques `tool_use`/`tool_result`
- Una tool con deps usa el `user_id` del contexto y **no** uno del prompt
- Un prompt que pide datos de otro usuario no accede a nada
- Una tool sensible pausa el loop en vez de ejecutarse
- Rechazar la aprobación produce un `tool_result` con `is_error`
- El presupuesto corta **antes** de la llamada, no después
- El recorte de contexto nunca deja un `tool_use` huérfano

`TestModel` de Pydantic AI sirve acá para guionar corridas sin escribir fakes a
mano; tu fixture `fake_model` del mini 8 también.

---

## ❓ Troubleshooting

**"messages.N: tool_use ids were found without tool_result blocks"**
Tu persistencia o tu recorte de contexto partió un par. Los bloques `tool_use` y
su `tool_result` viajan juntos o no viajan.

**El agente no recuerda el mensaje anterior**
No estás cargando el historial, o lo estás guardando después de responder y
falla en el medio. Guardá el turno completo en una transacción.

**Una tool devuelve datos de otro usuario**
El `user_id` está en el `input_schema`. Sacalo y pasalo por `deps`.

**El costo se disparó**
Mirá `input_tokens` por vuelta: si crece rápido, el problema es el historial, no
el modelo. Ahí entra el recorte de contexto.

---

## ✅ Checklist

- [ ] Persistir sesiones y mensajes (con los bloques de tools intactos)
- [ ] Cargar el historial al arrancar el loop
- [ ] Pasar el contexto autenticado a las tools por `deps`
- [ ] Una tool que use `deps` y ningún `user_id` en su schema
- [ ] Marcar tools sensibles y pausar el loop
- [ ] Endpoint de aprobación que retoma la corrida
- [ ] Presupuesto en tokens, chequeado antes de llamar
- [ ] Estrategia de recorte de contexto que respete los pares
- [ ] `execution_log` consultable por endpoint
- [ ] Tests de los ocho puntos de arriba

---

## 📚 Recursos

- [ReAct Pattern](https://arxiv.org/abs/2210.03629) — el paper del razonamiento en loop
- [Anthropic Tool Use](https://docs.anthropic.com/claude/docs/tool-use)
- [Token counting](https://docs.anthropic.com/en/docs/build-with-claude/token-counting)
- [Pydantic AI — dependencies](https://ai.pydantic.dev/dependencies/)

---

## ⏱️ Timeline

- Persistencia de sesiones: 1.5 h
- Dependencias en tools: 1 h
- Aprobación humana: 1.5 h
- Presupuesto y contexto: 1 h
- Tests: 1 h
- **Total: 5-6 horas**

---

## 🎯 Next: PROJECT 2

El loop pausado que guarda su estado en la base es, exactamente, el problema que
resuelve una tarea de Celery. Seguí en
`../../PROYECTOS_COMPLETOS/project-2-agentic-backend/`.

---

**Made as part of Sr Backend Roadmap** 🚀
