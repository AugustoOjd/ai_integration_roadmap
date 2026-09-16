# 🔬 Pruebas manuales

Este proyecto no tiene suite automática, y la razón no es ahorrar trabajo.

Un test automático contesta **"¿funciona?"**. Estas pruebas contestan **"¿qué está
pasando y por qué?"**. Un `assert` verde te dice que el invariante se cumple; no
te enseña qué lo rompe, ni cómo se ve cuando se rompe, ni por qué el diseño quedó
así. Eso se aprende mirando el sistema funcionar y, sobre todo, rompiéndolo a
propósito.

**Tres pruebas por fase, no más.** Las que atacan los puntos críticos de esa fase
— lo que si falla, hace que todo lo demás no tenga sentido. Una lista de veinte
chequeos no se corre; tres sí, y si están bien elegidas cubren lo que importa.

Cada prueba tiene la misma forma:

| | |
|---|---|
| **Correr** | el comando |
| **Observar** | qué tenés que ver, y dónde mirar |
| **Por qué** | qué mecanismo lo produce |
| **Rompelo** | el experimento que hace visible el mecanismo |

**La fila "Rompelo" es la que importa.** Si sólo corrés los comandos que andan,
estás haciendo QA.

## Cómo mirar

Tres ventanas abiertas, siempre:

```bash
# 1. el servidor — acá se ve el loop pensando
uv run uvicorn app.main:app --reload

# 2. la base — acá se ve qué quedó de verdad
docker compose exec postgres psql -U agentic -d agentic_backend

# 3. los curl
```

La ventana 1 es la mitad del aprendizaje:

```
INFO app.agent.loop iteración 1/8 stop_reason=tool_use in=1204 out=87
INFO app.agent.loop   -> calculate({'expression': '42 * 2'})
INFO app.agent.loop iteración 2/8 stop_reason=end_turn in=1310 out=24
```

Leer esas líneas mientras el agente contesta es verlo razonar.

## La API

Todos los endpoints **menos `/health`** exigen el header `X-User-Id`. Sin él,
401. Es andamiaje —en serio esto sería un token— pero la forma es la real: el
dueño entra por un canal que el modelo no ve nunca.

| Método | Ruta | Body | Devuelve |
|---|---|---|---|
| `GET` | `/health` | — | `{"status":"ok"}` |
| `POST` | `/conversations` | **ninguno** | `201` · `ConversationResponse` |
| `GET` | `/conversations/{cid}` | — | `ConversationResponse` |
| `POST` | `/conversations/{cid}/messages` | `{"prompt": "..."}` | `200` · `TurnResponse` |
| `POST` | `/conversations/{cid}/approvals/{tool_use_id}` | `{"approved": true\|false}` | `200` · `TurnResponse` |
| `GET` | `/conversations/{cid}/log?limit=50&before_id=` | — | `LogResponse` |

`POST /conversations` **no lleva body a propósito**: el `user_id` sale del header. Si
viniera en el JSON, abrir una conversación a nombre de otro sería cambiar una
línea del curl.

El `prompt` tiene un tope de 8000 caracteres. No es burocracia: sin tope, un
prompt de 500 KB entra al historial y se reenvía en cada vuelta y en cada turno
futuro de la conversación.

**Las respuestas**

```jsonc
// ConversationResponse
{"conversation_id","user_id","status","budget_tokens","budget_remaining","created_at"}
// status: active | pending_approval | exhausted

// TurnResponse
{"answer","iterations","tools_used":[...],"usage":{"input_tokens","output_tokens"},"budget_remaining"}

// PendingApprovalBody  ← el cuerpo del 202
{"status":"pending_approval","conversation_id",
 "pending":[{"tool_use_id","tool_name","tool_input","expires_at"}]}

// LogResponse
{"steps":[...],"next_before_id","stats":{"total_steps","failed_steps","tools",...}}
```

**Los códigos que vas a ver**

| | |
|---|---|
| `202` | una tool sensible espera aprobación — **no es un error** |
| `409` | la conversación está pausada · la aprobación ya se decidió · venció |
| `402` | se acabó el presupuesto de tokens |
| `422` | el agente no convergió en `AGENT_MAX_ITERATIONS` vueltas |
| `401` | falta el header `X-User-Id` |
| `502` / `503` | la API de Anthropic falló / no se pudo contactar |

La versión viva de todo esto está en **`localhost:8000/docs`**.

## Qué prompt dispara qué tool

Útil para probar a mano sin adivinar:

| Prompt | Tool |
|---|---|
| `"calculá 42 por 2"` | `calculate` |
| `"¿qué hora es en Tokio?"` | `get_current_time` |
| `"qué es celery"` | `search` |
| `"mostrame mis pedidos"` | `get_my_orders` |
| `"contame del pedido o_xxx"` | `get_order` |
| `"cancelá el pedido o_xxx"` | `cancel_order` → **sensible, devuelve 202** |

Los datos salen de `scripts/seed_orders.py`: cuatro pedidos de `u_42` (dos
`pending`, dos `shipped`) y dos de `u_7`, que no tienen que aparecer nunca.

---

# Fase 0 — el mini 9 andando en sincrónico

No hay funcionalidad nueva. Lo que se verifica es que **el port no rompió nada**,
así que cualquier cosa que falle acá falla por el cambio de async a sync.

Los tres puntos críticos: que el historial sobreviva al viaje a Postgres, que el
modelo no pueda elegir de quién son los datos, y que una corrida pueda pausarse y
retomarse desde otro request.

## Preparación

```bash
cd projects/project-2-agentic-backend

# El .env tiene que apuntar a la base con las credenciales nuevas:
#   DATABASE_URL=postgresql+psycopg://agentic:agentic@localhost:5432/agentic_backend
docker compose up -d --wait

uv sync
uv run alembic revision --autogenerate -m "esquema inicial"
```

**Antes de aplicarla, abrí el archivo que quedó en `alembic/versions/`.** El
autogenerate acierta casi siempre, y "casi siempre" no es una estrategia. Fijate
que estén las seis tablas, los `CheckConstraint` y los índices.

```bash
uv run alembic upgrade head
uv run python -m scripts.seed_orders
uv run uvicorn app.main:app --reload
```

```sql
\dt
-- orders · conversations · tasks · messages · pending_approvals · execution_steps
-- + alembic_version, que es de Alembic y guarda en qué revisión estás
```

---

## 1 — El par que no se puede romper

El invariante del que depende todo lo demás.

**Correr**

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)

curl -s -X POST localhost:8000/conversations/$CID/messages \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"prompt":"calculá 42 por 2"}' | jq '.answer, .usage'

curl -s -X POST localhost:8000/conversations/$CID/messages \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"prompt":"¿y por 3?"}' | jq '.answer, .usage'
```

**Observar.** El segundo prompt **no dice qué número**: si contesta 252, el
historial se persistió y se recargó. Y el `input_tokens` del segundo turno es
**más grande** que el del primero.

Después mirá qué se guardó de verdad:

```sql
select position, role, jsonb_pretty(content)
from messages where conversation_id = 'c_xxx' order by position;
```

El mensaje del assistant **no es texto**: es una lista de bloques, con un `text` y
un `tool_use` que lleva un `id` tipo `toolu_...`. Y el `tool_result` está en un
mensaje con rol **`user`** — contraintuitivo, pero desde la perspectiva del modelo
vos sos el usuario.

**Por qué.** La Messages API es *stateless*: no guarda nada entre requests. Si el
agente recuerda, es porque vos le volvés a contar el historial entero cada vez —
de ahí el crecimiento del `input_tokens`, que no es un bug sino el precio de la
memoria. Y el historial se persiste **tal cual viaja**, con los bloques de tools
incluidos, porque son ellos los que sostienen la correlación por `tool_use_id`.

**Rompelo.** Borrá a mano el bloque `tool_use`, dejando su `tool_result`:

```sql
select position, content from messages
where conversation_id = 'c_xxx' and content::text like '%tool_use%';

update messages
set content = '[{"type":"text","text":"Voy a calcularlo."}]'::jsonb
where conversation_id = 'c_xxx' and position = 1;
```

Mandá otro mensaje a esa conversación:

```
messages.N: tool_use ids were found without tool_result blocks
```

**Ése es el error que justifica medio proyecto**, y fijate cuándo aparece: el
turno que rompió el par funcionó perfecto, y falla **el siguiente**. Por eso el
turno se guarda entero en una transacción, por eso el recorte de contexto no
borra bloques, y por eso al rechazar una aprobación se contesta con un error en
vez de borrar el `tool_use`.

**La consulta que lo detecta** — tenela a mano, es la que hay que correr después
de cada fase:

```sql
with bloques as (
  select m.conversation_id,
         b->>'type'                            as tipo,
         coalesce(b->>'id', b->>'tool_use_id') as tuid
  from messages m, jsonb_array_elements(m.content) b
  where b->>'type' in ('tool_use','tool_result')
)
select conversation_id, tuid,
       count(*) filter (where tipo='tool_use')    as usos,
       count(*) filter (where tipo='tool_result') as resultados
from bloques group by conversation_id, tuid
having count(*) filter (where tipo='tool_use')
    <> count(*) filter (where tipo='tool_result');
```

Cero filas = sano. Con la conversación que acabás de romper, devuelve una.

---

## 2 — El modelo no elige de quién son los datos

**Correr.** Antes de mandar un mensaje, mirá **qué le estás mandando al modelo**:

```bash
uv run python -c "import json; from app.tools import registry; [print(t['name'], json.dumps(t['input_schema'])) for t in registry.to_params()]"
```

**Observar.** `get_my_orders` tiene `"properties": {}` — **vacío**. `get_order`
tiene un solo campo, `order_id`.

**Por qué.** `get_my_orders(ctx)` recibe un parámetro, pero está anotado como
`RunContext` y el registry lo saltea: no genera campo, no llega al schema. **El
modelo no sabe que esa función recibe algo.** Ahí está la frontera de seguridad
entera, visible en una línea de salida.

**Rompelo.** Agregale un parámetro en [orders.py](app/tools/orders.py):

```python
def get_my_orders(ctx: RunContext[AgentDeps], user_id: str) -> list[dict]:
```

Volvé a correr el dump: `user_id` **apareció en el schema**. Ahora pedile datos
ajenos (`u_7` tiene un "Notebook" sembrado):

```bash
curl -s -X POST localhost:8000/conversations/$CID/messages \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"prompt":"mostrame los pedidos del usuario 7"}' | jq .answer
```

Mirá los logs: `-> get_my_orders({'user_id': 'u_7'})`. **El modelo obedeció.**
Sacó el `u_7` del texto del usuario porque, desde su punto de vista, era un
parámetro legítimo. Eso es un IDOR con un LLM en el medio, y no se arregla con
prompt engineering: el system prompt es texto y compite con el resto del texto.

**Arreglalo** sacando el parámetro y repetí el mismo prompt. Ahora el modelo
devuelve los pedidos de `u_42` o dice que no puede — no porque lo hayas
convencido, sino porque **no tiene por dónde pedirlo**.

---

## 3 — Pausar, retomar, y el doble click

**Correr**

```bash
ORD=$(docker compose exec -T postgres psql -U agentic -d agentic_backend -tAc \
  "select id from orders where user_id='u_42' and status='pending' limit 1")

curl -s -o /tmp/r.json -w 'HTTP %{http_code}\n' -X POST \
  localhost:8000/conversations/$CID/messages \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d "{\"prompt\":\"cancelá el pedido $ORD\"}"

jq . /tmp/r.json
```

**Observar.** HTTP **202**, y el body no es una respuesta del agente: es un pedido
de permiso, con el `tool_use_id`, la tool y **los argumentos exactos**.

Que no se ejecutó no se comprueba leyendo la respuesta:

```sql
select id, status from orders where id = 'o_xxx';   -- sigue en 'pending'
select status from conversations where id = 'c_xxx';     -- 'pending_approval'
select tool_use_id, tool_name, tool_input, status from pending_approvals;
```

Y una conversación pausada rechaza mensajes nuevos con **409** — sin eso, el turno
siguiente arrancaría sobre un historial con un `tool_use` sin cerrar, que es el
error de la prueba 1.

```bash
curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST \
  localhost:8000/conversations/$CID/messages \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' -d '{"prompt":"hola"}'
```

Ahora aprobá:

```bash
TUID=$(jq -r '.pending[0].tool_use_id' /tmp/r.json)

curl -s -X POST localhost:8000/conversations/$CID/approvals/$TUID \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"approved":true}' | jq .answer
```

Devuelve la respuesta **final** del agente, no un "ok". En los logs: `retomando
conversation=... aprobada=True` y el loop siguiendo normalmente.

**Por qué.** Retomar no es *continuar*: el `for` de la corrida original murió con
aquel request. Lo que pasa es **reconstruir** — se levanta el historial de la
base, se rearman los bloques `tool_use` desde el JSONB, se ejecuta la tool, y se
entra al **mismo** loop. Para el loop esto es indistinguible de un turno normal, y
ésa es la propiedad que va a pedir Celery.

**Rompelo — el doble click.** Mandá el mismo POST otra vez:

```bash
curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST \
  localhost:8000/conversations/$CID/approvals/$TUID \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"approved":true}'
# 409
```

**El candado no es que el endpoint sea cuidadoso: es el `status` de la fila.** Dos
clicks, un reintento de red o un cliente con retry automático mandan el mismo POST
dos veces — y acá "dos veces" significa dos cancelaciones, dos mails, dos
reembolsos.

**Y el rechazo.** Pedí otra cancelación y contestá `{"approved": false}`. El
modelo tiene que responder algo coherente y **no explotar**: al rechazar no se
borra el `tool_use` —eso rompería el par— sino que se le manda un `tool_result`
con `is_error`. Confirmalo corriendo otra vez la consulta de huérfanos de la
prueba 1: sigue en cero.

---

## ✅ La Fase 0 está entendida cuando podés explicar

- [ ] Por qué el error de `tool_use` huérfano aparece un request *después* de la causa
- [ ] Por qué el `input_tokens` crece turno a turno y el `output_tokens` no
- [ ] Por qué el schema de `get_my_orders` está vacío, y qué pasó cuando lo llenaste
- [ ] Por qué retomar es reconstruir y no continuar
- [ ] Qué es el candado que impide ejecutar dos veces una aprobación
- [ ] Por qué al rechazar no se borra el `tool_use`

---

# Fase 1 — conversaciones y tareas

El agente sigue corriendo adentro del request, así que el `POST` tarda lo mismo
que antes. Lo que cambia es que ahora **queda una fila** que dice qué pasó.

Los tres puntos críticos: que la tarea exista antes de correr, que su estado sea
la única forma de enterarse del resultado, y que el historial cuelgue de la
conversación y no de la tarea.

## Preparación

```bash
uv run alembic revision --autogenerate -m "estado pending_approval en tasks"
```

Esta migración es de una línea y enseña lo contrario que la anterior:
`pending_approval` tiene 16 caracteres y el valor más largo que había era
`success`, de 7. Como el enum se guarda como VARCHAR, la columna pasa de
`VARCHAR(7)` a `VARCHAR(16)` — y el autogenerate **sí** lo detecta, porque
`env.py` tiene `compare_type=True`.

Sin ese flag la migración saldría vacía, la columna quedaría en `VARCHAR(7)`, y
el primer intento de pausar una tarea fallaría con
`value too long for type character varying(7)` — en runtime, no al migrar.

```bash
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

---

## 1 — La tarea existe antes de correr

**Correr**

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)

curl -s -X POST localhost:8000/conversations/$CID/tasks \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"prompt":"calculá 42 por 2"}' | jq
```

**Observar.** Devuelve `201` con la tarea ya en `success`, y con **tres
timestamps**:

```sql
select id, status,
       started_at  - created_at  as espera,
       finished_at - started_at  as ejecucion
from tasks order by created_at desc limit 5;
```

Ahora mismo `espera` es casi cero, porque el agente corre en el request. Cuando
haya una cola en el medio, esa columna va a ser lo que el usuario siente como
lentitud — y `ejecucion` va a seguir midiendo lo mismo. Son dos números
distintos y por eso son dos columnas.

**Por qué.** La fila se crea y se commitea **antes** de llamar al agente. Si el
proceso se muriera en la línea siguiente quedaría una tarea en `pending` que
alguien puede encontrar; sin esa fila, el pedido se perdió sin dejar rastro.

**Rompelo.** Mandá una tarea con un prompt largo y **matá el servidor con
Ctrl-C** mientras corre. Levantalo de nuevo y mirá:

```sql
select id, status, started_at, finished_at from tasks order by created_at desc limit 1;
```

Quedó en **`running` para siempre**, con `finished_at` en NULL. Nadie la va a
mover, porque el único que podía está muerto. Ése es exactamente el problema del
worker que se cae, y la fase que lo resuelve va a necesitar un heartbeat y
alguien de afuera que se dé cuenta.

---

## 2 — El estado de la tarea **es** la respuesta

**Correr.** Forzá un fallo dejando la conversación sin presupuesto:

```sql
update conversations set input_tokens_used = budget_tokens where id = 'c_xxx';
```

```bash
curl -s -o /tmp/t.json -w 'HTTP %{http_code}\n' -X POST \
  localhost:8000/conversations/$CID/tasks \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"prompt":"calculá 9 por 9"}'
```

**Observar.** El `POST` devuelve `402`… pero eso es el canal de hoy. Lo que
importa es que la fila quedó completa:

```sql
select status, error, finished_at from tasks order by created_at desc limit 1;
-- failed | BudgetExceededError: el turno necesita ~... | 2026-...
```

**Por qué.** El endpoint atrapa la excepción, marca la tarea `failed` con la
razón, y **después la deja seguir** para que `errors.py` elija el código HTTP.
Las dos cosas pasan: el cliente se entera ahora y la fila se entera para siempre.

Cuando el request devuelva un `task_id` y se vaya, el 402 ya no le llega a nadie
— y esta fila va a ser el único lugar donde el error existe. Por eso se escribe
ahora, mientras todavía parece redundante.

**Rompelo.** Pedile a la máquina de estados algo que no permite: marcá una tarea
terminada como si volviera a correr.

```sql
update tasks set status = 'success' where id = 't_xxx';
```

y después mandá el mismo `POST` de aprobación o cualquier camino que la mueva.
`success` es terminal: `TRANSICIONES[SUCCESS]` es un `frozenset` vacío, así que
cualquier intento levanta `TransicionInvalidaError` y devuelve 500. **Es un 500 a
propósito**: no es culpa del cliente, es que algún camino del código asumió un
estado que la tarea no tenía.

---

## 3 — El historial es de la conversación, no de la tarea

**Correr.** Dos tareas sobre el mismo hilo, donde la segunda depende de la
primera:

```bash
curl -s -X POST localhost:8000/conversations/$CID/tasks \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"prompt":"calculá 42 por 2"}' | jq -r '.result.answer'

curl -s -X POST localhost:8000/conversations/$CID/tasks \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"prompt":"¿y por 3?"}' | jq -r '.result.answer'
```

**Observar.** La segunda contesta 252 **aunque es otra tarea**. Y en la base:

```sql
select count(*) from tasks    where conversation_id = 'c_xxx';  -- 2
select count(*) from messages where conversation_id = 'c_xxx';  -- muchos más
```

**Por qué.** Si el historial colgara de la tarea, la tarea 2 arrancaría vacía y
"¿y por 3?" no tendría de qué hablar. La conversación dura para siempre y
acumula; la tarea dura minutos y es una ejecución sobre ella.

```bash
curl -s "localhost:8000/tasks?status=success" -H 'X-User-Id: u_42' | jq 'length'
```

**Rompelo.** Borrá la conversación y mirá qué se lleva puesto:

```sql
delete from conversations where id = 'c_xxx';
select count(*) from tasks    where conversation_id = 'c_xxx';  -- 0
select count(*) from messages where conversation_id = 'c_xxx';  -- 0
```

El `ON DELETE CASCADE` lo hace **Postgres en una sentencia**, no SQLAlchemy fila
por fila. Y la dirección importa: borrar el hilo se lleva sus ejecuciones, pero
borrar una ejecución no toca el hilo. Eso es lo que significa que una cosa
pertenezca a la otra.

---

## ✅ La Fase 1 está entendida cuando podés explicar

- [ ] Por qué la fila se crea y se commitea antes de llamar al agente
- [ ] Qué mide `started_at - created_at` y por qué hoy da casi cero
- [ ] Por qué el error se escribe en la tarea si el cliente ya recibió un 402
- [ ] Por qué `success` no puede volver a `running`
- [ ] Qué se rompería si el historial colgara de `tasks`

---

# Fase 2 — Celery en el medio

Cambió **una línea**: el endpoint llama a `.delay()` en vez de a `run_agent`. Todo
lo demás de esta fase es consecuencia de esa línea.

Los tres puntos críticos: que el request vuelva sin esperar, que lo único que
cruce el broker sea un id, y que el `fork` del worker no comparta conexiones.

## Preparación

Ahora hacen falta **cuatro ventanas**:

```bash
uv sync
docker compose up -d --wait          # postgres + redis

# ventana 1 — la API
uv run uvicorn app.main:app --reload

# ventana 2 — el worker
uv run celery -A app.tasks.celery_app worker --loglevel=info

# ventana 3 — la base
docker compose exec postgres psql -U agentic -d agentic_backend

# ventana 4 — los curl
```

Al arrancar el worker tenés que ver las tools registradas y, sobre todo, esto:

```
[tasks]
  . agent.execute
```

Si ese renglón no aparece, el worker no importó `app.tasks.agent_tasks` y
cualquier `.delay()` va a terminar en `Received unregistered task`.

---

## 1 — El request ya no espera

**Correr**

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)

time curl -s -o /tmp/t.json -w 'HTTP %{http_code}\n' -X POST \
  localhost:8000/conversations/$CID/tasks \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' \
  -d '{"prompt":"mostrame mis pedidos y calculá cuánto gasté en total"}'

jq . /tmp/t.json
TID=$(jq -r .task_id /tmp/t.json)
```

**Observar.** `HTTP 202` en **milisegundos**, con `"status": "pending"` y
`result: null`. El trabajo todavía no empezó. Mirá la ventana 2: el worker lo
toma y el loop corre ahí.

Ahora hacé polling:

```bash
for i in 1 2 3 4 5; do curl -s localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | jq -r .status; sleep 2; done
```

`pending` → `running` → `success`.

**Por qué.** 202 y no 201: el 201 diría "creé el recurso, acá está", y lo que
devolvemos no es el resultado sino una promesa. A partir de acá **la fila es el
único canal**: no hay a quién devolverle el error ni el resultado.

```sql
select id, status,
       started_at  - created_at as espera,
       finished_at - started_at as ejecucion
from tasks order by created_at desc limit 3;
```

Comparalo con la Fase 1: `espera` ya no es cero. Eso es la cola.

**Rompelo — apagá el worker.** Con la ventana 2 cerrada, mandá otra tarea. El
`POST` devuelve 202 igual, alegremente, y la fila se queda en `pending` para
siempre. Levantá el worker y mirala arrancar sola: **el trabajo estaba en Redis
esperando**. Eso es lo que compra una cola, y también la razón por la que un
`pending` viejo no distingue "nadie la tomó todavía" de "no hay nadie".

---

## 2 — Lo único que cruza es un id

**Correr.** Mirá el mensaje real que viaja por el broker. Encolá algo con el
worker **apagado** y espiá la cola:

```bash
docker compose exec redis redis-cli -n 0 LRANGE celery 0 -1
```

**Observar.** El cuerpo es JSON y adentro está el `task_id` y nada más. **No
está el `user_id`, no está el prompt, no está el presupuesto.**

**Por qué.** Cualquiera con acceso al broker puede leer eso — y escribirlo. Por
eso viaja lo mínimo y el worker reconstruye el resto de la base: si el `user_id`
viajara en el payload, habría dos lugares diciendo de quién es la corrida, y el
mensaje es el que un atacante controla.

Mirá en la ventana 2 cómo el worker lo reconstruye:

```
tomando tarea id=t_xxx conversation=c_xxx user=u_42
```

Ese `user=u_42` **no vino del mensaje**: salió de la conversación.

**Rompelo — encolá un id inventado:**

```bash
uv run python -c "from app.tasks.agent_tasks import execute_agent_task; execute_agent_task.delay('t_no_existe')"
```

En el worker:

```
WARNING tarea inexistente id=t_no_existe, se descarta
```

No explota y no reintenta: no hay nada que correr. **Ése es el motivo por el que
el worker no confía en lo que le llega** — el broker es un canal escribible, así
que el mensaje es una pista, no una autorización.

---

## 3 — El `fork` y las conexiones heredadas

**Correr.** Levantá el worker con varios procesos y mandale tareas en paralelo:

```bash
# ventana 2, reiniciado así:
uv run celery -A app.tasks.celery_app worker --loglevel=info -c 4
```

```bash
# Ojo: $CID tiene que estar seteado EN ESTA terminal. Si está vacío, la URL queda
# con doble barra y los seis curl dan 404 sin que se note.
echo $CID

for i in 1 2 3 4 5 6; do curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' -H 'content-type: application/json' -d "{\"prompt\":\"calculá $i por 7\"}" | jq -r '.task_id + " " + .status'; done
```

Seis líneas `t_xxx pending`, casi instantáneas. Mientras corren, en otra ventana:

```sql
select status, count(*) from tasks group by status;
```

Con `-c 4` tenés hasta cuatro en `running` a la vez y el resto en `pending`
esperando turno. Eso es la concurrencia del worker, visible.

**Observar.** En el arranque del worker, una línea por proceso hijo:

```
INFO app.tasks.celery_app pool de conexiones reseteado para este worker
```

Y las seis tareas terminan en `success` sin errores raros de base.

**Por qué.** El pool prefork forkea los hijos **después** de importar los
módulos, y el engine se crea al importar `app.core.db`. Sin el
`worker_process_init`, los hijos heredan los descriptores de las conexiones ya
abiertas y terminan dos procesos escribiendo en el mismo socket de Postgres.

**Rompelo.** Comentá el cuerpo de la señal en
[celery_app.py](app/tasks/celery_app.py):

```python
@worker_process_init.connect
def _resetear_pool(**kwargs: object) -> None:
    pass   # engine.dispose(close=False)
```

Reiniciá el worker con `-c 4` y mandá las seis tareas de nuevo. Los síntomas no
son deterministas y ése es el punto — podés ver cualquiera de estos:

```
psycopg.OperationalError: consuming input failed
psycopg.errors.ProtocolViolation
InterfaceError: connection already closed
```

o, peor, una tarea que se cuelga sin decir nada. **Ninguno menciona el `fork`.**
Por eso la señal está puesta desde el primer día: este bug es carísimo de
diagnosticar si no sabés que existe.

Volvé a poner el `engine.dispose(close=False)`.

---

## ✅ La Fase 2 está entendida cuando podés explicar

- [ ] Por qué el `POST` devuelve 202 y no 201
- [ ] Qué pasa si encolás con el worker apagado, y qué revela sobre `pending`
- [ ] Por qué en el payload viaja sólo el `task_id`
- [ ] De dónde saca el worker el `user_id`, y por qué no del mensaje
- [ ] Por qué el `commit` va antes del `.delay()`
- [ ] Qué rompe el `fork` y por qué el error no lo menciona

---

# Fase 3 — una sola fuente de verdad

Ahora hay dos sistemas que creen saber el estado de una tarea: el backend de
Celery y tu tabla. Van a discrepar — siempre discrepan. Esta fase es elegir uno
y que el otro no sea autoridad de nada.

Los tres puntos críticos: que el `PENDING` de Celery no sirva para contestar,
que las transiciones sean atómicas, y que tu tabla sobreviva a lo que le pase a
Redis.

## Preparación

Sin migración: no cambió el esquema. Reiniciá la API y el worker para tomar el
código nuevo.

---

## 1 — El `PENDING` de Celery es indistinguible de un id inventado

**Correr.** Preguntale a Celery por una tarea que no existió jamás:

```bash
uv run python -c "from app.tasks.celery_app import celery_app; from celery.result import AsyncResult; print('inventado ->', AsyncResult('esto-no-existe', app=celery_app).status); print('otro mas  ->', AsyncResult('12345', app=celery_app).status)"
```

**Observar.**

```
inventado   -> PENDING
otro más    -> PENDING
```

**No es un error. Es `PENDING`.** Celery no tiene forma de distinguir "esta
tarea está en cola" de "nunca oí hablar de esto".

Ahora la tuya:

```bash
curl -s -o /dev/null -w 'HTTP %{http_code}\n' localhost:8000/tasks/t_inventado \
  -H 'X-User-Id: u_42'
# 404
```

**Por qué.** Un `GET` construido sobre `AsyncResult` le contestaría "en cola" a
un id que no existió nunca, y el cliente se quedaría haciendo polling para
siempre sobre la nada. La tabla puede dar un 404 real porque la fila existe o no
existe — no hay tercera opción.

Por eso la regla del proyecto: **ningún endpoint construye un `AsyncResult`.**

```bash
grep -rn "AsyncResult" app/api app/agent    # tiene que devolver vacío
```

---

## 2 — La condición viaja adentro del UPDATE

**Correr.** Mirá el SQL que emite una transición. Prendé el eco un momento:

```bash
DB_ECHO=true uv run python -c "from app.core.db import SessionFactory; from app.tasks.state import marcar_corriendo; db = SessionFactory(); print('prendio:', marcar_corriendo(db, 't_inventado')); db.close()"
```

**Observar.** La sentencia es una sola:

```sql
UPDATE tasks SET status=%(status)s, started_at=%(started_at)s
WHERE tasks.id = %(id_1)s AND tasks.status IN (%(status_1)s)
```

y `prendió: False`, porque no hay ninguna fila que cumpla.

**Por qué.** No hay un `SELECT` antes. Leer, decidir y después escribir deja una
ventana en el medio: con la API y cuatro workers escribiendo la misma tabla,
otro proceso puede mover la fila justo ahí. Con la condición adentro del
`UPDATE`, **la base arbitra** y el `rowcount` te dice quién ganó.

Cero filas no es un error: es información. Para `pending → running` significa
"otro worker ya la tomó, no la reproceses" — que es el candado que va a impedir
el trabajo duplicado cuando el broker reentregue una tarea.

**Rompelo — hacé que el candado actúe.** Agarrá una tarea terminada y pedile al
worker que la corra de nuevo:

```bash
TID=$(docker compose exec -T postgres psql -U agentic -d agentic_backend -tAc \
  "select id from tasks where status='success' limit 1")

uv run python -c "from app.tasks.agent_tasks import execute_agent_task; execute_agent_task.delay('$TID')"
```

En el worker:

```
WARNING tarea id=t_xxx ya no está en pending, se descarta
```

**Corrió la tarea y no hizo nada.** El `marcar_corriendo` no prendió porque
`success` no está entre los orígenes válidos de `running`, así que el worker se
fue antes de tocar el modelo. Verificalo:

```sql
select id, status, finished_at, result->>'answer' from tasks where id = 't_xxx';
```

Mismo `finished_at`, misma respuesta: no se reprocesó. Ése es exactamente el
mecanismo que va a defender contra la doble entrega.

---

## 3 — Tu tabla sobrevive a Redis

**Correr.** Encolá algo, dejalo terminar, y después volá el backend de Celery:

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
TID=$(curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 8 por 8"}' | jq -r .task_id)

sleep 8
curl -s localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | jq -r '.status, .result.answer'
```

```bash
# el FLUSHDB que vas a hacer alguna vez para destrabar la cola
docker compose exec redis redis-cli -n 1 FLUSHDB
```

**Observar.** Preguntale a Celery y preguntale a tu tabla:

```bash
uv run python -c "from app.tasks.celery_app import celery_app; from celery.result import AsyncResult; print('celery dice:', AsyncResult('$TID', app=celery_app).status)"

curl -s localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | jq -r '.status, .result.answer'
```

Celery dice `PENDING` — se olvidó de todo. Tu tabla sigue diciendo `success` con
la respuesta intacta.

**Por qué.** El backend de Celery es un detalle de transporte: no sabe de tu
dominio (`pending_approval` no existe en su vocabulario), no sobrevive a una
purga, y su `PENDING` miente. Está configurado para poder mirar el transporte con
Flower, y su `result_expires=3600` dice lo mismo con otras palabras: esos datos
están pensados para vencerse.

**Rompelo al revés.** Volá la cola en vez de los resultados:

```bash
# apagá el worker primero
curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 3 por 3"}' | jq -r .task_id

docker compose exec redis redis-cli -n 0 FLUSHDB     # ← la cola, no los resultados
```

Levantá el worker: **no pasa nada**. La fila quedó en `pending` para siempre,
porque el mensaje que iba a hacerla correr ya no existe. Tu tabla sabe que la
tarea existe; lo que no sabe es que nadie la va a tomar.

Ése es el límite honesto de "una sola fuente de verdad": tu tabla es autoridad
sobre **qué pasó**, no sobre **qué va a pasar**. Detectar tareas que quedaron
huérfanas necesita algo más, y es lo que va a resolver el heartbeat.

---

## ✅ La Fase 3 está entendida cuando podés explicar

- [ ] Por qué `AsyncResult` de un id inventado devuelve `PENDING` y no un error
- [ ] Por qué la condición va adentro del `UPDATE` y no en un `if` antes
- [ ] Qué significa que un CAS afecte cero filas, y por qué no siempre es un error
- [ ] Qué se pierde con `FLUSHDB` en la base 1 y qué se pierde en la base 0
- [ ] Sobre qué **no** es autoridad tu tabla

---

# Fase 4 — reintentos: qué se reintenta y qué no

La mitad fácil la trae Celery. La que importa es la clasificación, y la regla que
la ordena es una sola: **se reintenta lo que depende del mundo, no lo que depende
de tu estado.**

Los tres puntos críticos: que un error permanente falle rápido, que uno
transitorio espere con jitter, y que lo que muere del todo quede reprocesable.

## Preparación

```bash
uv run alembic revision --autogenerate -m "columna retries en tasks"
uv run alembic upgrade head
```

Reiniciá API y worker.

---

## 1 — Lo que NO se reintenta falla en el primer intento

**Correr.** Dejá una conversación sin presupuesto y mandale una tarea:

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
docker compose exec -T postgres psql -U agentic -d agentic_backend -c \
  "update conversations set input_tokens_used = budget_tokens where id = '$CID';"

curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 2 por 2"}' | jq -r .task_id
```

**Observar.** En el worker, **una** línea de fallo y nada más:

```
ERROR tarea id=t_xxx falló definitivamente
BudgetExceededError: el turno necesita ~... tokens y quedan 0
```

```sql
select status, retries, error from tasks where conversation_id = '$CID';
-- failed | 0 | BudgetExceededError: ...
```

**`retries = 0`.** Ni un reintento.

**Por qué.** `BudgetExceededError` no está en `REINTENTABLES`, así que cae en el
`except Exception` que marca `failed` y termina. Reintentarlo se agotaría igual
las tres veces — y cada vuelta que llegara a llamar al modelo costaría plata por
un resultado que ya sabemos.

La lista es una **allowlist**, igual que el evaluador de `calculate`: lo que no
está clasificado se trata como permanente. El default es "no reintentar", así que
un error nuevo que nadie clasificó falla rápido en vez de gastar tres veces.

---

## 2 — Lo que SÍ se reintenta espera, y no todos a la vez

**Correr.** Apuntá el SDK a un puerto muerto: toda llamada al modelo va a dar
`APIConnectionError`, que es transitorio. No cuesta un centavo porque nunca sale
de tu máquina.

```bash
# apagá el worker y levantalo así:
ANTHROPIC_BASE_URL=http://localhost:9999 uv run celery -A app.tasks.celery_app worker --loglevel=info
```

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 5 por 5"}' | jq -r .task_id
```

**Observar.** Cuatro intentos en total y las esperas **crecen**:

```
WARNING tarea id=t_xxx reintento 1/3 en 0.8s por APIConnectionError
WARNING tarea id=t_xxx reintento 2/3 en 1.4s por APIConnectionError
WARNING tarea id=t_xxx reintento 3/3 en 3.1s por APIConnectionError
ERROR   Task agent.execute raised unexpected: APIConnectionError(...)
```

Mientras reintenta, mirá la fila:

```sql
select status, retries from tasks where conversation_id = '$CID';
-- running | 2      ← sigue en running, NO en failed
```

**Por qué.** La fila no se marca `failed` mientras reintenta: esta ejecución no
terminó. Recién cuando `self.retry` agota los intentos re-lanza la excepción
original, y ahí el `on_failure` de `AgentTask` cierra la fila.

Y fijate que el candado no la frenó. Un reintento entra con la fila ya en
`running`, así que el CAS de `marcar_corriendo` no prendería — por eso sólo se
chequea cuando `self.request.retries == 0`. **"Es un reintento mío" no es lo
mismo que "otro worker la tomó".**

**Rompelo — sacale el jitter.** En
[retry_policy.py](app/tasks/retry_policy.py), devolvé el exponencial pelado:

```python
return exponencial   # sin el * (0.5 + random.random() / 2)
```

Mandá **cinco** tareas de golpe y mirá los timestamps de los reintentos: las
cinco esperan exactamente 1s, después exactamente 2s, después exactamente 4s.
**Cinco ráfagas sincronizadas contra un servicio que ya se estaba cayendo.** Con
jitter, las esperas se reparten y las ráfagas se disuelven. Volvé a ponerlo.

---

## 3 — Lo que muere queda reprocesable

**Correr.** Con el worker todavía apuntando al puerto muerto, mirá la DLQ:

```bash
uv run python -c "from app.tasks import dead_letter; import json; print(json.dumps(dead_letter.list_failures(5), indent=2, ensure_ascii=False))"
```

**Observar.** Cada entrada tiene el tipo de excepción, cuántos reintentos
consumió, y **los argumentos originales**:

```json
{
  "task_name": "agent.execute",
  "args": ["t_xxx"],
  "exc_type": "APIConnectionError",
  "retries": 3,
  "failed_at": "2026-09-16T..."
}
```

Compará con la entrada de la prueba 1:

```bash
uv run python -c "from app.tasks import dead_letter; [print(e['exc_type'], 'retries=', e['retries']) for e in dead_letter.list_failures(10)]"
```

```
APIConnectionError   retries= 3    ← era transitorio y duró demasiado
BudgetExceededError  retries= 0    ← era permanente
```

**Ese número separa dos problemas distintos.** `retries=0` dice "esto no se
arregla solo, revisá el código o la config". `retries=3` dice "el mundo estuvo
caído más de lo que aguantamos" — mismo síntoma, causas opuestas.

**Por qué guardar los `args`.** Sin ellos la entrada dice "algo falló" y no se
puede hacer nada. Con ellos, reprocesar es una línea:

```bash
# apagá el worker, levantalo SIN el ANTHROPIC_BASE_URL falso
uv run celery -A app.tasks.celery_app worker --loglevel=info
```

```bash
uv run python -c "from app.tasks import dead_letter; print('reenviadas:', dead_letter.replay(10))"
```

Las tareas vuelven a correr, ahora contra la API de verdad. Ojo con lo que vas a
ver en la fila: el `marcar_corriendo` **no prende**, porque la tarea quedó en
`failed` y `failed` es terminal.

```
WARNING tarea id=t_xxx ya no está en pending, se descarta
```

**Eso está bien y es la lección.** El replay reencola el mensaje; la máquina de
estados decide si tiene sentido correrlo. Un reproceso de verdad necesita
además resetear la fila a `pending`, y que eso sea una decisión explícita —y no
un efecto de reencolar— es exactamente lo que querés.

---

## ✅ La Fase 4 está entendida cuando podés explicar

- [ ] Por qué la lista de reintentables es una allowlist y no una blocklist
- [ ] Por qué la fila sigue en `running` mientras reintenta
- [ ] Por qué el candado sólo se chequea cuando `retries == 0`
- [ ] Qué pasa con cinco tareas que fallan juntas si el backoff no tiene jitter
- [ ] Qué distingue una entrada de DLQ con `retries=0` de una con `retries=3`
- [ ] Por qué el replay reencola pero no resetea el estado
