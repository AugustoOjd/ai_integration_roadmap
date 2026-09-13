# 🗺️ Mini 9 — Plan por fases

Cada fase es **autocontenida**: explica su concepto desde cero, se construye
sola, se verifica sola y se puede entender sin haber leído las otras. Las únicas
dependencias reales son la Fase 0 (el esqueleto y la base de datos donde vive
todo lo demás) y el par 5→6, que son las dos mitades del mismo problema.

El hilo conductor del mini es uno solo: **el loop del mini 8 no tenía estado que
sobreviviera al request**. Cada corrida empezaba con `messages = [{"role":
"user", "content": prompt}]`, terminaba, y se olvidaba de todo. Las seis cosas
que agrega este mini —memoria, dueño, traza, pausa, presupuesto, recorte— son la
misma consecuencia de una sola decisión: **el estado de la corrida ahora vive en
la base, no en la pila de Python**.

| Fase | Tema | Depende de |
|------|------|-----------|
| 0 | Esqueleto: Postgres, SQLAlchemy y el loop portado del mini 8 | — |
| 1 | Persistir el historial sin romper los pares `tool_use`/`tool_result` | 0 |
| 2 | Sesiones multi-turno: el loop que arranca con memoria | 1 |
| 3 | Dependencias: el `user_id` viaja por afuera del modelo | 0 (mejor con 2) |
| 4 | `execution_log`: la traza como dato, no como `print` | 2 |
| 5 | Aprobación (mitad 1): marcar tools sensibles y **pausar** | 2, 4 |
| 6 | Aprobación (mitad 2): **retomar** una corrida desde la base | 5 |
| 7 | Presupuesto en tokens, chequeado **antes** de llamar | 2 |
| 8 | Crecimiento del contexto: recorte que respeta los pares | 1, 7 |
| 9 | Tests + CHECK_LEARNING | todas |

---

## Qué vas a aprender (el mapa conceptual)

1. **La memoria de un agente es tu tabla, no del modelo.** La Messages API es
   *stateless*: no guarda nada entre requests. Si el agente recuerda, es porque
   vos persistís y recargás el historial.
2. **El historial es un formato, no un texto.** Los bloques `tool_use` y
   `tool_result` son parte del historial y se persisten tal cual. Guardar sólo
   los textos —la tentación, porque es lo legible— rompe la correlación por
   `tool_use_id` y la API rechaza el request siguiente.
3. **Lo que define permisos nunca va en el `input_schema`.** El modelo elige
   *qué hacer*; el contexto autenticado define *sobre qué*. Un `user_id` en el
   schema es un IDOR con un LLM en el medio.
4. **"El modelo pide, vos ejecutás" es una política, no una frase.** Se vuelve
   código cuando una tool sensible **pausa** el loop en vez de ejecutarse.
5. **Un loop pausado es estado que sobrevive al request.** No podés tener el
   `for` corriendo mientras esperás a un humano: hay que poder reconstruir la
   corrida desde la base. Es, exactamente, el problema de PROJECT 2 con Celery.
6. **`max_iterations` no es un presupuesto.** Cinco vueltas con historiales
   chicos son centavos; cinco con 100 KB de historial, no. El tope real se
   cuenta en tokens y se estima **antes** de mandar.
7. **Toda conversación larga se rompe sola.** El recorte de contexto no es una
   optimización: es la diferencia entre una sesión que dura y una que un día
   devuelve 400.

---

## Fase 0 — Esqueleto: Postgres, SQLAlchemy y el loop portado del mini 8

### Concepto aislado

Este mini no empieza en cero: empieza con el loop del mini 8 funcionando. Lo que
cambia es **dónde vive el estado**. En el mini 8 el historial era una lista local
de `run_agent`; a partir de acá es una fila.

Eso obliga a una decisión de modelo de datos antes de escribir nada:

| Tabla | Qué guarda | Por qué separada |
|---|---|---|
| `sessions` | dueño, presupuesto, tokens gastados, estado | es la conversación |
| `messages` | un mensaje del historial, con su `content` **crudo** | es lo que se le manda al modelo |
| `execution_steps` | qué tool, con qué input, qué devolvió, cuánto costó | es la auditoría, no se le manda al modelo |

La distinción que vale: `messages` es **input del modelo** y su forma la dicta la
API; `execution_steps` es **output para humanos** y su forma la elegís vos. Si
las mezclás en una tabla, cada cambio de una te rompe la otra.

El `content` de un mensaje va en **JSONB**, no en `text`. Es una lista de bloques
(`text`, `tool_use`, `tool_result`), no un string — mismo motivo por el que en la
Fase 0 del mini 8 `content` era una lista y no un string.

### Qué construimos

- `pyproject.toml` — lo del mini 8 más `sqlalchemy[asyncio]`, `asyncpg`,
  `alembic` (opcional en este mini), `pytest-asyncio`
- `docker-compose.yml` — un Postgres, nada más
- `app/db.py` — engine async, `async_sessionmaker`, dependencia `get_db` de FastAPI
- `app/models.py` — `Session`, `Message`, `ExecutionStep`
- `app/config.py` — lo del mini 8 más `DATABASE_URL` y `DEFAULT_BUDGET_TOKENS`
- Copiar del mini 8, **sin tocar**: `app/llm.py`, `app/tools/`, `app/agent.py`

Copiar el loop tal cual y recién después modificarlo es deliberado: el primer
commit del mini tiene que ser "mini 8 andando sobre Postgres", para que todo lo
que se rompa después sea atribuible a lo nuevo.

### Cómo verificarlo

```bash
docker compose up -d
uv run python -m scripts.db_smoke     # crea las tablas, inserta y lee una sesión
uv run uvicorn app.main:app --reload  # /health responde
```

### Deberías poder responder

- ¿Por qué `messages.content` es JSONB y no `text`?
- ¿Por qué la traza no se guarda en la misma tabla que los mensajes?
- ¿Por qué la sesión de SQLAlchemy es por-request y el cliente Anthropic no?

---

## Fase 1 — Persistir el historial sin romper los pares

### Concepto aislado

Ésta es la fase donde el mini se rompe si te apurás, así que va sola y antes que
el loop con memoria.

Guardar el historial parece trivial: una fila por mensaje. El problema es **qué**
guardás. El mensaje del assistant que te devolvió la API es una lista de bloques:

```python
[TextBlock(text="Voy a calcularlo"), ToolUseBlock(id="toolu_7", name="calculate", ...)]
```

Si persistís `"Voy a calcularlo"` porque es lo legible, en el turno siguiente le
mandás al modelo un historial donde el `tool_use` no existe pero el `tool_result`
sí. La API te contesta:

```
messages.N: tool_use ids were found without tool_result blocks
```

La regla, la misma de la Fase 2 del mini 8 pero ahora atravesando la base:
**el historial se persiste tal cual viaja**. Serializás `response.content`
completo a JSONB y lo deserializás igual. Si querés una vista legible para un
humano, es una proyección (Fase 4), no el dato.

Lo segundo que se rompe: **el turno se guarda entero o no se guarda**. Un turno
son N mensajes (assistant con `tool_use`, user con `tool_result`, assistant
final). Si commiteás mensaje por mensaje y el proceso muere en el medio, dejás la
sesión con un `tool_use` huérfano persistido — y esa sesión queda rota para
siempre. Una transacción por turno.

### Qué construimos

- `app/repository.py` — `load_history(session_id) -> list[MessageParam]` y
  `save_turn(session_id, messages)` en **una** transacción
- Serialización explícita de los bloques del SDK a dict (`.model_dump()`), y la
  vuelta a `MessageParam`
- Un test sin LLM: guardar un turno con `tool_use`/`tool_result`, recargarlo, y
  verificar que los `tool_use_id` siguen correlacionados

### Cómo verificarlo

Insertá a mano un turno con tools, recargalo y compará **byte a byte** contra lo
que guardaste. Después el ejercicio que vale: borrá a propósito el bloque
`tool_use` de la fila, mandá el historial a la API y leé el error completo.
Aprender ese mensaje de error acá te ahorra la Fase 8.

### Deberías poder responder

- ¿Qué se pierde si guardás sólo el texto de cada mensaje?
- ¿Por qué el turno completo va en una transacción y no mensaje por mensaje?
- ¿El `content` que le mandás a la API tiene que ser idéntico al que te devolvió?

---

## Fase 2 — Sesiones multi-turno: el loop que arranca con memoria

### Concepto aislado

Con la Fase 1 hecha, este mini entero cabe en una línea de diferencia:

```python
# el loop del mini 8 arrancaba siempre así:
messages = [{"role": "user", "content": prompt}]

# acá arranca así:
messages = await load_history(session_id) + [{"role": "user", "content": prompt}]
```

Y al terminar, `save_turn`. Eso es todo lo nuevo del loop.

Lo que sí cambia arriba del loop es la **forma de la API**. El mini 8 tenía un
endpoint sin estado (`POST /agent/tool-calling`). Acá hay un recurso:

```
POST /sessions                      -> abre la conversación, devuelve session_id
POST /sessions/{id}/messages        -> un turno
```

La consecuencia que se siente enseguida: el `input_tokens` crece en cada turno,
porque el historial viaja completo cada vez. No es un bug — es el costo de la
memoria, y es lo que la Fase 7 acota y la Fase 8 recorta.

### Qué construimos

- `app/schemas/sessions.py` — request/response Pydantic
- `app/routes/sessions.py` — los dos endpoints
- `app/agent.py` — `run_agent(session_id, prompt, db)`: carga, corre el loop del
  mini 8 sin tocarlo, guarda

### Cómo verificarlo

```bash
curl -X POST localhost:8000/sessions -d '{"user_id": "u_42"}'
curl -X POST localhost:8000/sessions/s_abc/messages -d '{"prompt": "calculá 42*2"}'
curl -X POST localhost:8000/sessions/s_abc/messages -d '{"prompt": "¿y por 3?"}'
```

El segundo prompt no dice qué número: si contesta 252, el historial funciona.
Mirá también el `input_tokens` de las dos respuestas: el segundo es más grande.

### Deberías poder responder

- ¿Por qué la sesión es un recurso propio y no un parámetro del endpoint del mini 8?
- ¿Qué pasa si dos requests de la misma sesión llegan a la vez?
- ¿Por qué `input_tokens` crece turno a turno y `output_tokens` no?

---

## Fase 3 — Dependencias: el `user_id` viaja por afuera del modelo

### Concepto aislado

Ésta es la pregunta 48 del `CHECK_LEARNING.md` del mini 8, y acá se responde.

```python
# ❌ el user_id como parámetro de la tool
def get_my_orders(user_id: str) -> list[dict]: ...
```

Si el `user_id` está en el `input_schema`, **lo elige el modelo** — y el modelo lo
saca del texto del usuario. Alguien escribe *"mostrame los pedidos del usuario
7"* y tu tool obedece. Es un IDOR con un LLM en el medio, y ninguna cantidad de
prompt engineering lo arregla: el prompt es entrada no confiable por definición.

```python
# ✅ el user_id viaja por afuera del modelo
def get_my_orders(ctx: RunContext[Deps]) -> list[dict]:
    return db.orders_for(ctx.deps.user_id)   # del token, no del prompt
```

La regla: **lo que define permisos nunca va en el `input_schema`.** El modelo
elige *qué hacer*; el contexto autenticado define *sobre qué*.

En código propio esto es un registry que sabe distinguir dos clases de
parámetros: los que van al schema (los del modelo) y los que se inyectan (los
tuyos). El de la Fase 4 del mini 8 deriva el schema de **todos** los tipos de la
función, así que hay que enseñarle a saltearse el primer parámetro cuando está
anotado como contexto — igual que FastAPI se saltea sus `Depends`.

### Qué construimos

- `app/deps.py` — `AgentDeps` (dataclass: `user_id`, la sesión de DB, el
  `session_id`), construido en el endpoint desde el usuario autenticado
- `app/tools/registry.py` — el del mini 8, extendido: el parámetro de contexto
  se excluye del `input_schema` y se inyecta en `execute(name, input, deps)`
- `app/tools/orders.py` — `get_my_orders(ctx)` y `get_order(ctx, order_id)`: la
  segunda sí recibe un id del modelo, pero filtra por `ctx.deps.user_id`
- Auth mínima: un header o un token fake. **No** es el tema del mini; lo que
  importa es que el `user_id` no venga del body ni del prompt

### Cómo verificarlo

Imprimí el `input_schema` de `get_my_orders`: tiene que ser `{"properties": {}}`.
Después el test que es la fase entera: autenticado como `u_42`, mandá el prompt
*"mostrame los pedidos del usuario 7"* y verificá que la respuesta trae pedidos
de `u_42` o ninguno — nunca de `u_7`.

### Deberías poder responder

- ¿Por qué no alcanza con validar el `user_id` dentro de la tool?
- ¿Qué otra cosa, además del `user_id`, nunca debería estar en un `input_schema`?
- ¿Por qué `get_order(order_id)` sí puede recibir un id del modelo?

---

## Fase 4 — `execution_log`: la traza como dato

### Concepto aislado

El mini 8 logueaba cada vuelta con `print` / `logger`. Sirve mientras mirás una
terminal. Acá el agente toca datos de un usuario y ejecuta acciones a su nombre:
la pregunta "¿por qué el agente hizo *eso*?" hay que poder contestarla tres días
después, para una sesión específica, sin grep.

Eso convierte la traza en **un modelo de datos**, con los campos que hacen falta
para auditar y para costear:

```
execution_steps: session_id, turn, iteration, tool_name, tool_input,
                 tool_output, is_error, latency_ms, input_tokens, output_tokens
```

Dos decisiones que parecen de detalle y no lo son:

- **`tool_output` se recorta antes de guardarse.** Una tool que devuelve 200 KB
  te infla la tabla igual que te infla el contexto.
- **La traza se escribe aunque el turno falle.** Si el loop explota en la vuelta
  3, las vueltas 1 y 2 son justamente lo que querés mirar. Ojo con la
  transacción de la Fase 1: los pasos de la traza no pueden morir en el mismo
  rollback que los mensajes.

Y la que va a importar en la Fase 6: con la traza persistida, una corrida a medio
hacer es **reconstruible**. Ese es el puente.

### Qué construimos

- `app/models.py` — `ExecutionStep` (ya declarado en la Fase 0, ahora usado)
- El loop escribe un paso por tool ejecutada, con tokens y latencia
- `GET /sessions/{id}/log` — la traza legible, paginada
- Un helper que resume la sesión: tokens totales, tools más usadas

### Cómo verificarlo

Corré un prompt de dos tools encadenadas y pedí el log: dos filas, con
`iteration` 1 y 2, sus inputs y sus outputs. Después forzá un error de tool (la
de la Fase 6 del mini 8) y verificá que el paso quedó guardado con `is_error`.

### Deberías poder responder

- ¿Por qué la traza no puede vivir sólo en los logs de la aplicación?
- ¿Qué NO guardarías en `tool_input` aunque el modelo lo haya mandado?
- ¿Cómo mostrás la traza sin exponerle al usuario tu prompt de sistema?

---

## Fase 5 — Aprobación (mitad 1): marcar tools sensibles y pausar

### Concepto aislado

En el mini 8 "el modelo pide, vos ejecutás" era teoría: ejecutabas todo lo que
pedía. Acá se vuelve código.

La política es una línea, y es **tuya**, no técnica:

```python
REQUIEREN_APROBACION = {"cancel_order", "send_email", "refund"}
```

El criterio: una tool necesita aprobación si es **irreversible o visible para
afuera**. Leer no; escribir, cobrar, mandar un mail, sí. Ningún framework puede
decidir eso por vos porque no es una propiedad del código, es una del negocio.

Lo que cambia en el loop: antes de ejecutar los `tool_use` de una vuelta, mirás
si alguno está en el set. Si lo está, **no ejecutás ninguno todavía**: guardás el
estado de la corrida, devolvés `202` con lo pendiente, y el request termina.

```http
202 Accepted
{"status": "pending_approval",
 "pending": {"id": "toolu_7", "tool": "cancel_order", "input": {"order_id": 991}}}
```

El `202` es el código correcto y vale entenderlo: la request se aceptó, el
trabajo no terminó, y hay otro recurso donde seguirlo. No es un error (`4xx`) ni
un éxito completo (`200`).

Lo que hay que guardar para poder seguir: el historial hasta ahí (ya lo hacés,
Fase 1), **qué tool quedó pendiente con qué input y qué `tool_use_id`**, y el
estado de la sesión (`running` → `pending_approval`). Una sesión pausada rechaza
mensajes nuevos con `409`: primero se resuelve lo pendiente.

### Qué construimos

- `app/models.py` — `PendingApproval` (o columnas en `sessions`): `tool_use_id`,
  `tool_name`, `tool_input`, estado, timestamps
- `app/policy.py` — el set de tools sensibles, como **dato de configuración**
- `app/agent.py` — la rama que pausa: persiste y sale, sin ejecutar nada
- `409` si llega un mensaje a una sesión en `pending_approval`

### Cómo verificarlo

`"Cancelá el pedido 991"` tiene que devolver `202`, y `cancel_order` **no** tiene
que haberse ejecutado — verificalo mirando la tabla de pedidos, no la respuesta.
Después mandá otro mensaje a la misma sesión: `409`.

### Deberías poder responder

- ¿Por qué no ejecutás las tools inocentes del mismo turno mientras esperás?
- ¿Por qué `202` y no `200` con un flag, ni `403`?
- ¿Quién decide qué tool es sensible, y por qué no puede decidirlo el modelo?

---

## Fase 6 — Aprobación (mitad 2): retomar una corrida desde la base

### Concepto aislado

Ésta es la fase difícil del mini, y la que justifica que el loop sea tuyo.

Un loop pausado es **estado que sobrevive al request**. No podés dejar el `for`
corriendo con un `await` esperando a un humano que quizás conteste mañana: el
worker se reinicia, el deploy pasa, la conexión se cae. La única forma es que
retomar sea **reconstruir**: un request nuevo levanta el historial de la base, le
agrega el `tool_result` que faltaba, y sigue el loop desde ahí.

```
POST /sessions/{id}/approvals/{tool_use_id}  {"approved": true}
```

- **Aprobado**: ejecutás la tool ahora, armás su `tool_result`, lo agregás al
  historial y seguís el loop normalmente.
- **Rechazado**: igual de importante. No borrás el `tool_use` —romperías el par
  de la Fase 1— sino que mandás un `tool_result` con `is_error: true` y un texto
  del estilo *"el usuario no autorizó esta acción"*. El modelo lo entiende y
  sigue: pide otra cosa, o le explica al usuario. Es la misma mecánica que un
  error de tool de la Fase 6 del mini 8.

Dos cosas que hay que cuidar:

- **Idempotencia**: dos `POST` de aprobación con el mismo `tool_use_id` no pueden
  ejecutar la tool dos veces. El estado del pendiente es el candado.
- **Expiración**: un pendiente de hace una semana no se aprueba. Un `expires_at`
  y un estado `expired`.

Y la observación que conecta con lo que sigue: *retomar una corrida desde la base
es exactamente lo que va a hacer una tarea de Celery en PROJECT 2*. Si esta fase
te sale limpia, ese proyecto ya está medio escrito.

### Qué construimos

- `app/routes/approvals.py` — el endpoint de decisión
- `app/agent.py` — `resume_run(session_id, tool_use_id, approved, deps)`: el
  mismo loop, con un punto de entrada distinto
- El `tool_result` de rechazo con `is_error`
- Control de idempotencia y `expires_at`

### Cómo verificarlo

La secuencia completa: `202` → aprobar → respuesta final con el pedido cancelado.
Después la que importa: `202` → **rechazar** → el modelo tiene que contestar algo
coherente, no explotar. Y al final, `GET /log`: la traza tiene que mostrar la
pausa, la decisión y quién la tomó.

### Deberías poder responder

- ¿Por qué no se puede resolver esto con un `await` dentro del loop?
- ¿Qué se rompe si al rechazar borrás el `tool_use` del historial?
- ¿Qué pasa si el proceso muere entre el `202` y la aprobación?
- ¿Qué le agrega Celery a esto, y qué parte ya está resuelta acá?

---

## Fase 7 — Presupuesto: `max_iterations` no alcanza

### Concepto aislado

El mini 8 acotaba el loop en **vueltas**. Es un tope contra el loop infinito, no
contra el gasto: cinco iteraciones con historiales chicos son centavos; cinco con
un historial de 100 KB, no. Y desde la Fase 2 los historiales crecen solos.

El tope real se cuenta en tokens, y se chequea **antes** de mandar:

```python
estimado = client.messages.count_tokens(model=..., messages=..., tools=...)
if session.tokens_used + estimado.input_tokens > session.budget_tokens:
    raise BudgetExceededError
```

`count_tokens` es gratis y exacto, pero sólo si le pasás **lo mismo** que le vas
a pasar a `create`: los mismos `messages`, el mismo `system` y las mismas
`tools`. Las definiciones de tools son tokens de input en cada vuelta — si las
dejás afuera de la cuenta, subestimás siempre.

Y estima **input**. El output no se puede saber de antemano: se acota con
`max_tokens` y se suma al gasto **después**, con el `usage` de la respuesta.

La política de qué hacer al agotarlo también es tuya, y no hay una sola buena:

| Al agotarse | Qué devolvés |
|---|---|
| Cortar duro | `402`/`429` y la sesión queda `exhausted` |
| Respuesta parcial | el último texto que tenías, marcado como incompleto |
| Degradar | seguir sin tools, o recortar contexto (Fase 8) y reintentar |

Del tope en tokens al tope en dinero hay una multiplicación: input y output
tienen precios distintos, así que se acumulan por separado y se convierten con el
precio del modelo puesto en config, no hardcodeado.

### Qué construimos

- `app/budget.py` — `estimate(messages, tools)`, `check(session, estimado)`,
  `record(session, usage)`, y la conversión a dinero
- `sessions.tokens_used` / `budget_tokens`, actualizados en la misma transacción
  del turno
- `BudgetExceededError` → código HTTP propio, con `budget_remaining` en el body
- `budget_remaining` en la respuesta de cada turno

### Cómo verificarlo

Poné `budget_tokens` en algo ridículo (500) y mandá un prompt: tiene que cortar
**antes** de la llamada — verificalo mirando que `usage` de esa sesión no se
movió. Después con un presupuesto normal, mirá cómo baja `budget_remaining`
turno a turno y comparalo contra el `usage` real.

### Deberías poder responder

- ¿Por qué `max_iterations` y presupuesto son dos topes distintos y hacen falta los dos?
- ¿Por qué `count_tokens` tiene que recibir también las `tools`?
- ¿Se puede estimar el costo del output antes de la llamada? ¿Qué hacés entonces?
- ¿Qué devolvés cuando el presupuesto se agota a mitad de un loop?

---

## Fase 8 — Contexto: toda conversación larga se rompe sola

### Concepto aislado

Haiku 4.5 tiene 200K de ventana, no 1M. Una sesión larga llega — y con el
historial completo viajando en cada turno (Fase 2), llega antes de lo que
parece. Las tres salidas, de peor a mejor:

| Estrategia | Qué hace | Costo |
|---|---|---|
| Ventana deslizante | tira los mensajes viejos | el agente "olvida" de golpe |
| Resumen | pide al modelo que resuma y reemplaza | una llamada extra, pérdida de detalle |
| Recorte selectivo | tira los `tool_result` viejos, guarda el texto | barato y suele alcanzar |

El recorte selectivo gana casi siempre porque los `tool_result` son lo más pesado
y lo menos necesario: el contenido de una búsqueda de hace diez turnos ya está
resumido en el texto que el modelo escribió después.

**La trampa**, que es la Fase 1 volviendo: no podés borrar un `tool_use` sin
borrar su `tool_result`, ni al revés. Vienen de a pares. La implementación
correcta no recorre mensajes: recorre **turnos completos**, y reemplaza el
contenido del `tool_result` por un placeholder (`"[resultado recortado]"`)
manteniendo el bloque y su `tool_use_id`.

Segunda decisión: el recorte es **de lo que se manda, no de lo que se guarda**.
La base conserva el historial completo (lo necesitás para el log de la Fase 4);
lo que recortás es la lista que le pasás a `create`. Si recortás la base, perdés
la auditoría para ahorrar tokens.

### Qué construimos

- `app/context.py` — `fit(messages, budget) -> messages`, con la estrategia de
  recorte selectivo y un invariante explícito: ningún `tool_use` queda huérfano
- Integración con la Fase 7: se recorta cuando el estimado no entra, antes de
  rechazar el turno por presupuesto
- Un test con un historial sintético largo que verifica el invariante

### Cómo verificarlo

Armá un historial de 50 turnos con tools, pasalo por `fit()` y verificá dos
cosas: que entra en el presupuesto, y que todo `tool_use` sigue teniendo su
`tool_result`. Después mandalo a la API de verdad: si vuelve `200`, el
invariante se cumple.

### Deberías poder responder

- ¿Por qué el recorte se aplica al request y no a la base?
- ¿Qué se rompe si recortás mensaje por mensaje en vez de turno por turno?
- ¿Cuándo un resumen vale la llamada extra que cuesta?
- ¿Cómo te das cuenta, mirando métricas, de que necesitás recortar?

---

## Fase 9 — Tests + CHECK_LEARNING

### Concepto aislado

Misma regla que el mini 8: **ningún test llama al modelo**. Lo que cambia es que
ahora hay una segunda dependencia lenta: la base. Se testea en cuatro capas.

1. **Puras, sin nada**: `context.fit()`, `budget.check()`, la política de tools
   sensibles. Código común.
2. **Persistencia, con Postgres real**: `save_turn`/`load_history` con bloques de
   tools. Acá un SQLite en memoria miente (JSONB, tipos, transacciones): usá un
   Postgres de test con una transacción por test y rollback al final.
3. **El loop, con el cliente mockeado**: la fixture `fake_model` del mini 8, con
   secuencias guionadas — `tool_use` sensible → pausa; aprobación → `tool_result`
   → `end_turn`. Acá vive el 80% de los bugs.
4. **Los endpoints, con `TestClient`**: códigos HTTP (`202`, `409`, el del
   presupuesto) y forma de la respuesta.

Lo nuevo a cubrir, uno por fase:

- El historial se persiste y se recarga **con** los bloques `tool_use`/`tool_result`
- Una tool con deps usa el `user_id` del contexto y **no** uno del prompt
- Un prompt que pide datos de otro usuario no accede a nada
- Una tool sensible pausa el loop en vez de ejecutarse
- Rechazar la aprobación produce un `tool_result` con `is_error`
- Aprobar dos veces el mismo `tool_use_id` ejecuta la tool una sola vez
- El presupuesto corta **antes** de la llamada, no después
- El recorte de contexto nunca deja un `tool_use` huérfano

### Qué construimos

- `tests/conftest.py` — fixture de DB transaccional + el cliente fake del mini 8
- `tests/test_persistence.py`, `test_deps.py`, `test_approvals.py`,
  `test_budget.py`, `test_context.py`, `test_routes.py`
- `CHECK_LEARNING.md` con las preguntas de cada fase

### Deberías poder responder

- ¿Por qué SQLite en memoria no sirve para testear esta persistencia?
- ¿Cómo testeás una pausa, si el loop termina y el request también?
- ¿Qué de este mini **no** se puede testear sin llamar al modelo real?

---

## Correcciones al README del mini

Detectadas al armar el plan, se aplican en las fases indicadas:

| README dice | Correcto | Fase |
|---|---|---|
| `def get_my_orders(ctx: RunContext[Deps])` | `RunContext` es de Pydantic AI y acá el loop es propio: es el **patrón**, no el import. Tu registry inyecta tu propio `AgentDeps` | 3 |
| "`TestModel` de Pydantic AI sirve acá" | `TestModel` sólo funciona dentro de un `Agent` de Pydantic AI, y este mini no lo usa en runtime. Los tests van con el cliente fake del mini 8 | 9 |
| Estructura sin capa de datos entre loop y DB | Hace falta `app/repository.py`: el loop no habla SQL | 1 |
| Estructura sin `app/policy.py` | La lista de tools sensibles es configuración, no una constante perdida en `agent.py` | 5 |
| `count_tokens(...)` "es gratis" a secas | Es gratis **y** exacto sólo si recibe los mismos `messages`, `system` y `tools` que `create` | 7 |
| El ejemplo de budget compara contra un "estimado" sin definir | Se compara contra `input_tokens` del estimado; el output no se puede estimar, se acota con `max_tokens` | 7 |
| La aprobación aparece como un paso | Son dos problemas distintos: pausar (persistir y salir) y retomar (reconstruir) | 5, 6 |
| Timeline de 5-6 h | Con Postgres, pausa/retoma y tests transaccionales, 8-10 h es más honesto | — |
