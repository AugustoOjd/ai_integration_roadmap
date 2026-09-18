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

> ⚠️ **El worker NO tiene reload.** `uvicorn --reload` recarga sola; Celery no.
> Después de cualquier cambio de código hay que reiniciarlo a mano (Ctrl-C y
> levantarlo de nuevo).
>
> El síntoma de olvidarse es desconcertante, porque el sistema queda **partido en
> dos versiones**: la API se comporta como esperás y el worker como el código
> anterior. Todo lo que pasa adentro del worker —la traza, la cancelación, los
> reintentos— se comporta como la fase pasada.
>
> **Si una prueba falla de una forma que no tiene sentido, reiniciá el worker
> antes de buscar el bug.**

La ventana 1 es la mitad del aprendizaje:

```
INFO app.agent.loop iteración 1/8 stop_reason=tool_use in=1204 out=87
INFO app.agent.loop   -> calculate({'expression': '42 * 2'})
INFO app.agent.loop iteración 2/8 stop_reason=end_turn in=1310 out=24
```

Leer esas líneas mientras el agente contesta es verlo razonar.

## Atajos

Dos alias que te ahorran escribir lo mismo cien veces:

```bash
alias psqlp2='docker compose exec postgres psql -U agentic -d agentic_backend'
alias qp2='docker compose exec -T postgres psql -U agentic -d agentic_backend -c'
```

El `-T` importa dentro de `$( )` o de un loop: sin él Docker intenta asignar una
TTY y te ensucia la salida.

**`c_xxx`, `t_xxx` y `o_xxx` son marcadores de posición.** Si los pegás tal cual,
las consultas devuelven cero filas — no está roto, estás preguntando por un id
que no existe. Reemplazalos por los que te devolvieron los `curl`, o usá estas
subconsultas que buscan el último:

```sql
-- la última conversación
(select id from conversations order by created_at desc limit 1)
-- la última tarea
(select id from tasks order by created_at desc limit 1)
-- un pedido cancelable
(select id from orders where user_id = 'u_42' and status = 'pending' limit 1)
```

Por ejemplo:

```sql
select turn, position, role from messages
where conversation_id = (select id from conversations order by created_at desc limit 1)
order by position;
```

Y la consulta que resume el estado de todo, útil después de cualquier prueba:

```sql
select left(t.id, 14) as tarea, t.status,
       t.started_at::time(0)   as arranco,
       t.heartbeat_at::time(0) as ultimo_latido,
       t.finished_at::time(0)  as termino,
       t.retries,
       count(distinct s.id)    as pasos,
       left(coalesce(t.error, ''), 40) as error
from tasks t
left join execution_steps s on s.task_id = t.id
group by t.id order by t.created_at desc limit 8;
```

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

---

# Fase 5 — idempotencia: la tarea que corre dos veces

Con `acks_late`, un worker que muere después de ejecutar pero antes de confirmar
hace que el broker le dé la misma tarea a otro. **No es un riesgo, es el
diseño**: "exactly once" no existe, y lo que se elige es entre perder y duplicar.

Elegimos duplicar. Los tres puntos críticos son las tres defensas.

## Preparación

```bash
uv run alembic revision --autogenerate -m "tabla tool_executions"
uv run alembic upgrade head
```

Reiniciá API y worker — el worker ahora arranca con `acks_late`.

---

## 1 — El candado de la fila

**Correr.** Agarrá una tarea ya terminada y pedile al worker que la corra de
nuevo, como haría el broker al reentregarla:

```bash
TID=$(docker compose exec -T postgres psql -U agentic -d agentic_backend -tAc "select id from tasks where status='success' limit 1")
uv run python -c "from app.tasks.agent_tasks import execute_agent_task; execute_agent_task.delay('$TID')"
```

**Observar.**

```
WARNING tarea id=t_xxx ya no está en pending, se descarta
```

Ni una llamada al modelo. El `marcar_corriendo` no prendió porque `success` no
está entre los orígenes de `running`.

**Por qué.** Es la primera capa y cubre la reentrega completa: la tarea llegó
otra vez desde el principio. Lo que **no** cubre es el caso feo — la tarea que ya
estaba `running`, ejecutó dos tools, y murió. Ahí la reentrega la ve `running`,
se va, y esas dos tools ya corrieron.

Para eso está la segunda capa.

---

## 2 — El candado de la tool

**Correr.** Provocá el caso que el candado de la fila no cubre: ejecutá la misma
tool **dos veces con el mismo `tool_use_id`**, que es exactamente lo que pasa
cuando una corrida se rehace.

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
ORD=$(docker compose exec -T postgres psql -U agentic -d agentic_backend -tAc "select id from orders where user_id='u_42' and status='pending' limit 1")
```

```bash
uv run python -c "
from app.core.db import SessionFactory
from app.agent.deps import AgentDeps, RunContext
from app.tools import registry
db = SessionFactory()
ctx = RunContext(deps=AgentDeps(user_id='u_42', conversation_id='$CID', db=db), tool_use_id='toolu_PRUEBA')
print('1ra:', registry.execute('cancel_order', {'order_id': '$ORD'}, ctx))
print('2da:', registry.execute('cancel_order', {'order_id': '$ORD'}, ctx))
db.commit(); db.close()
"
```

**Observar.** Las dos líneas dicen **lo mismo**:

```
1ra: {"order_id": "o_xxx", "status": "cancelled", "cancelled": true}
INFO tool cancel_order (toolu_PRUEBA) ya ejecutada, se devuelve el resultado guardado
2da: {"order_id": "o_xxx", "status": "cancelled", "cancelled": true}
```

Sin el candado, la segunda habría devuelto
`"el pedido está en estado cancelled y sólo se pueden cancelar los pendientes"` —
o sea, un error donde antes hubo un éxito.

```sql
select tool_use_id, tool_name, status, completed_at from tool_executions;
-- toolu_PRUEBA | cancel_order | done | 2026-...
```

**Por qué dos cosas y no una.** Repetir el resultado importa tanto como no
repetir el efecto: si la segunda corrida le contestara algo distinto al modelo,
el historial dejaría de reproducirse igual y el agente tomaría otra decisión.

**Y por qué la clave es el `tool_use_id`.** Lo mandó el modelo, quedó persistido
en el historial, y por eso es **el mismo en cada reintento**. Un `uuid4()`
generado al ejecutar sería distinto cada vez: no sería un candado, sería una
bitácora.

**Rompelo — sacale los efectos a la tool.** En
[policy.py](app/agent/policy.py), vaciá el set:

```python
TIENEN_EFECTOS: frozenset[str] = frozenset()
```

Repetí el comando con otro pedido `pending` y otro `tool_use_id`. Ahora la
segunda llamada devuelve el error de "ya está cancelado": **la tool corrió dos
veces**. Volvé a poner `cancel_order`.

---

## 3 — La ventana que ninguna transacción cubre

**Correr.** Dejá una reserva abierta a mano, simulando un proceso que murió entre
reservar y terminar:

```sql
insert into tool_executions (tool_use_id, conversation_id, tool_name, status)
values ('toolu_HUERFANO', 'c_xxx', 'cancel_order', 'in_flight');
```

```bash
uv run python -c "
from app.core.db import SessionFactory
from app.agent.deps import AgentDeps, RunContext
from app.tools import registry
db = SessionFactory()
ctx = RunContext(deps=AgentDeps(user_id='u_42', conversation_id='c_xxx', db=db), tool_use_id='toolu_HUERFANO')
try:
    registry.execute('cancel_order', {'order_id': 'o_xxx'}, ctx)
except Exception as e:
    print(type(e).__name__, '->', e)
db.close()
"
```

**Observar.**

```
EjecucionAmbiguaError -> no se pudo confirmar si 'cancel_order' ya se ejecutó.
NO la reintentes: avisale al usuario que revise el estado antes de volver a pedirla.
```

Y hereda de `ToolError`, así que en una corrida real **el modelo lo lee y se lo
explica al usuario** en vez de matar la conversación.

**Por qué esto es honesto y no una falla.** Lo que garantiza el candado depende
de dónde esté el efecto:

| Efecto | Garantía |
|---|---|
| En esta base (`cancel_order`) | **Perfecta.** La reserva y el UPDATE viven en la misma transacción: commitean las dos o ninguna, y `in_flight` nunca sobrevive |
| Afuera (un mail, un cobro) | **Ninguna.** Entre reservar y que el mail salga hay una ventana que ninguna transacción cubre |

Por eso `toolu_HUERFANO` hubo que insertarlo a mano: con las tools de este
proyecto, ese estado no se produce solo.

Esa ventana no se cierra con más código. Se cierra preguntándole al proveedor si
el efecto ocurrió, mandándole **tu** clave de idempotencia para que deduplique él
—lo que hacen Stripe y similares—, o decidiendo por política qué preferís. El
default acá es negarse, que es lo correcto para lo irreversible; para una
notificación, donde perder es peor que duplicar, la política correcta sería la
contraria.

Limpiá la reserva:

```sql
delete from tool_executions where tool_use_id = 'toolu_HUERFANO';
```

---

## ✅ La Fase 5 está entendida cuando podés explicar

- [ ] Por qué `acks_late` **crea** este problema, y por qué lo querés igual
- [ ] Qué cubre el candado de la fila y qué caso deja afuera
- [ ] Por qué la clave es el `tool_use_id` y no un `uuid4()`
- [ ] Por qué se guarda el resultado y no sólo el hecho de haber ejecutado
- [ ] Por qué `cancel_order` no puede quedar en `in_flight` y `send_email` sí
- [ ] Qué tools **no** necesitan pasar por el candado, y por qué

---

# Fase 6 — progreso: la traza consultable mientras corre

El usuario pregunta "¿cómo va?" a los cuatro segundos y hay que tener algo que
contestarle. La mitad ya estaba: la traza se escribe vuelta a vuelta y con commit
inmediato. Lo que faltaba era que cada paso dijera **de qué ejecución es**.

Los tres puntos críticos: que la traza crezca mientras mirás, que el commit de la
traza no arrastre la transacción del turno, y que el polling no sea gratis para
el cliente.

## Preparación

```bash
uv run alembic revision --autogenerate -m "task_id en execution_steps"
uv run alembic upgrade head
```

---

## 1 — La lista crece entre un polling y el siguiente

**Correr.** Un prompt que obligue a varias vueltas:

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
TID=$(curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' \
  -d '{"prompt":"mostrame mis pedidos, después calculá cuánto gasté en total, y decime qué hora es"}' | jq -r .task_id)

for i in 1 2 3 4 5 6; do curl -s localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | jq -c '{status, iteration, pasos: [.steps[].tool_name]}'; sleep 2; done
```

**Observar.** La lista **crece** mientras la tarea corre:

```json
{"status":"pending","iteration":null,"pasos":[]}
{"status":"running","iteration":1,"pasos":["get_my_orders"]}
{"status":"running","iteration":2,"pasos":["get_my_orders","calculate"]}
{"status":"running","iteration":3,"pasos":["get_my_orders","calculate","get_current_time"]}
{"status":"success","iteration":3,"pasos":["get_my_orders","calculate","get_current_time"]}
```

**Por qué.** `record_step` commitea **en el acto**, vuelta a vuelta. Si esperara
al final del turno, esta consulta devolvería una lista vacía hasta que la tarea
terminara — o sea, justo hasta el momento en que ya no hace falta.

Y el `iteration` no está guardado en la fila: sale del último paso. Un contador
denormalizado es un contador que algún día discrepa de aquello de lo que deriva.

**Rompelo.** En [repository.py](app/agent/repository.py), sacá el commit de
`record_step` (dejá sólo el `add`). Repetí el polling: la lista queda **vacía
hasta el final** y después aparecen todos los pasos de golpe. Peor todavía: si la
tarea falla, no queda ni uno. Volvé a ponerlo.

---

## 2 — El commit de la traza no arrastra el turno

Ésta es la parte que arregla un agujero que estaba desde el mini 9.

**Correr.** Mirá cuántas conexiones abre una corrida:

```sql
select count(*), state from pg_stat_activity
where datname = 'agentic_backend' group by state;
```

Mandá una tarea con `cancel_order` y contá durante la corrida: vas a ver una
conexión de más mientras escribe cada paso.

**Por qué.** `record_step` abre **su propia sesión**. Antes commiteaba sobre la
sesión del loop, y eso arrastraba todo lo pendiente ahí.

El caso concreto: `cancel_order` hace `flush` de la cancelación y de su reserva de
idempotencia, y el `record_step` que venía justo después **las commiteaba** —
antes de que existiera el `tool_result` que las registra. Si el loop moría en el
medio, quedaba un pedido cancelado que el historial no menciona, y en el turno
siguiente el modelo no tenía forma de saber que lo había cancelado.

Con conexión propia, el efecto de la tool y la prueba de ese efecto commitean
juntos, en `save_turn` o en `resume_turn`. El precio es una conexión más por
paso; la alternativa era un agujero que sólo aparece cuando algo ya salió mal.

**Verificalo.** Cancelá un pedido y comprobá que las dos cosas están o no están
juntas:

```sql
select o.id, o.status,
       exists (select 1 from messages m, jsonb_array_elements(m.content) b
               where m.conversation_id = o2.conversation_id
                 and b->>'type' = 'tool_result') as tiene_tool_result
from orders o, (select 'c_xxx'::text as conversation_id) o2
where o.id = 'o_xxx';
```

---

## 3 — El polling tiene un precio, y el servidor lo dice

**Correr.**

```bash
curl -si localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | grep -i "retry-after\|HTTP/"
```

**Observar.** Mientras la tarea vive:

```
HTTP/1.1 200 OK
retry-after: 2
```

Cuando termina, el header **desaparece**.

**Por qué.** Un cliente que hace polling elige el intervalo por su cuenta, y suele
elegir mal: cada 100 ms son diez queries por segundo contra tu base para una tarea
que tarda ocho. El `Retry-After` es una sugerencia —el cliente puede ignorarla—
pero decirle cuánto esperar es mucho más barato que descubrir después por qué
Postgres está saturado.

Que desaparezca al terminar también comunica algo: **dejá de preguntar**.

**Rompelo — medí lo que cuesta ignorarlo.** Con `DB_ECHO=true` en el servidor,
hacé polling agresivo sobre una tarea que corre:

```bash
for i in $(seq 1 40); do curl -s -o /dev/null localhost:8000/tasks/$TID -H 'X-User-Id: u_42'; sleep 0.1; done
```

Mirá la ventana del servidor: cada request son **tres** queries —la tarea, la
conversación para el permiso, y los pasos—. Cuarenta requests en cuatro segundos
son 120 queries para contestar una pregunta cuya respuesta cambia cada dos
segundos.

---

## ✅ La Fase 6 está entendida cuando podés explicar

- [ ] Por qué `record_step` commitea en el acto en vez de esperar al turno
- [ ] Por qué `iteration` se deriva de los pasos y no se guarda en la fila
- [ ] Qué se commiteaba de más cuando la traza compartía sesión con el loop
- [ ] Por qué la traza de progreso muestra menos campos que la de auditoría
- [ ] Qué le dice al cliente que el `Retry-After` desaparezca

---

# Fase 7 — cancelación cooperativa

Cancelar no es matar el proceso: es **dejar la conversación en un estado válido**.
El loop chequea un flag al principio de cada vuelta y corta ahí, donde no hay
ninguna tool a mitad de camino.

Los tres puntos críticos: que corte en un punto seguro, que sea idempotente, y
que `cancelled` no se confunda con `failed`.

## Preparación

```bash
uv run alembic revision --autogenerate -m "cancelacion de tareas"
uv run alembic upgrade head
```

---

## 1 — Corta donde no rompe nada

**Correr.** Una tarea larga, cancelada a mitad:

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
TID=$(curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' \
  -d '{"prompt":"mostrame mis pedidos, calculá el total, decime la hora en Tokio y buscá qué es celery"}' | jq -r .task_id)

sleep 3
curl -s -X POST localhost:8000/tasks/$TID/cancel -H 'X-User-Id: u_42' | jq -c '{status, iteration}'
sleep 6
curl -s localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | jq -c '{status, iteration, pasos: [.steps[].tool_name]}'
```

**Observar.** El `POST /cancel` devuelve la tarea todavía en `running` — sólo
prendió el flag. Unos segundos después:

```json
{"status":"cancelled","iteration":2,"pasos":["get_my_orders","(cancelada)"]}
```

El paso `(cancelada)` dice en qué vuelta cortó. El paréntesis lo distingue de
cualquier tool real en un `group by`.

**Por qué.** El corte es **antes** de llamar al modelo y antes de ejecutar nada.
En ese punto no hay un `tool_use` esperando su `tool_result`, así que el
historial queda consistente. Y nada del turno se persiste: `save_turn` sólo corre
en el camino feliz, así que la conversación queda **exactamente como estaba**.

**Verificalo — la conversación sigue usable:**

```bash
curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 9 por 9"}' | jq -r .task_id
```

Y la consulta de pares huérfanos de la Fase 0: **cero filas**.

**Rompelo — cancelá a lo bruto.** Esto es lo que hace
`revoke(terminate=True)`, que es la tentación obvia:

```bash
TID=$(curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"mostrame mis pedidos y calculá el total"}' | jq -r .task_id)

sleep 4
pkill -9 -f "celery.*worker"     # SIGKILL a mitad de turno
```

La tarea queda en `running` para siempre y el turno a medias se perdió. Ahora
mirá la diferencia con la cancelación cooperativa: no hay ningún paso
`(cancelada)`, no hay `finished_at`, y nadie sabe que eso pasó. Levantá el
worker de nuevo.

---

## 2 — Tres casos, no uno

**Correr.** Cancelá una tarea que **todavía no arrancó** — con el worker apagado:

```bash
# apagá el worker
TID=$(curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 3 por 3"}' | jq -r .task_id)

curl -s -X POST localhost:8000/tasks/$TID/cancel -H 'X-User-Id: u_42' | jq -r .status
# cancelled  ← en el acto, no "pedida"
```

Levantá el worker. En sus logs:

```
WARNING tarea id=t_xxx ya no está en pending, se descarta
```

**Observar.** El mensaje seguía en la cola y el worker lo tomó igual — pero el
CAS de `marcar_corriendo` no prendió porque el estado ya era `cancelled`. **El
mismo candado de la idempotencia sirve para esto.**

**Por qué tres casos.** Lo que hace `/cancel` depende de si hay alguien
escuchando:

| Estado | Qué pasa | Por qué |
|---|---|---|
| `pending` | se cancela **en el acto** | nunca arrancó; no hay loop que lea el flag |
| `pending_approval` | se cancela **en el acto** | está detenida; tampoco hay loop vivo |
| `running` | se prende el **flag** | hay un loop; corta en el próximo punto seguro |
| terminal | no se toca | el CAS impide que un pedido tardío la mueva |

**Rompelo — cancelá dos veces:**

```bash
curl -s -o /dev/null -w '%{http_code} ' -X POST localhost:8000/tasks/$TID/cancel -H 'X-User-Id: u_42'
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/tasks/$TID/cancel -H 'X-User-Id: u_42'
# 200 200
```

Las dos veces 200, no 409. **Cancelar dos veces no es un conflicto** — es un
doble click, o un cliente con retry. La segunda no tiene nada que hacer y nada
que reportar. Compará con la aprobación, que sí devuelve 409 la segunda vez: ahí
la diferencia importa, porque un segundo "sí" podría significar una segunda
ejecución.

---

## 3 — `cancelled` no es `failed`

**Correr.**

```sql
select status, count(*) from tasks group by status order by 2 desc;
```

**Observar.** Son columnas separadas, y tienen que serlo:

```
 success           |  14
 cancelled         |   3
 failed            |   2
```

**Por qué.** Una la pidió el usuario, la otra salió mal. Si `cancelled` cayera en
`failed`, cualquier métrica de tasa de error contaría gente cambiando de opinión
como si fueran incidentes — y un pico de cancelaciones te haría buscar un bug que
no existe.

```sql
-- la tasa de error de verdad
select round(100.0 * count(*) filter (where status = 'failed')
             / nullif(count(*) filter (where status in ('success','failed')), 0), 1) as pct_error
from tasks;
```

Fijate que `cancelled` queda **fuera del denominador** también: una tarea que el
usuario frenó no es ni un éxito ni un fracaso del sistema.

**Y el efecto que sí queda.** Si el agente alcanzó a ejecutar una tool con
efectos antes de la cancelación, **eso no se deshace**:

```sql
select tool_name, status from tool_executions
order by created_at desc limit 5;
```

Deshacer requiere una operación inversa que la mayoría de las tools no tiene —no
existe "des-enviar el mail"—. Lo que sí hay es el registro: la traza dice qué
alcanzó a pasar antes de cortar, y ésa es la respuesta honesta.

---

## ✅ La Fase 7 está entendida cuando podés explicar

- [ ] Por qué el chequeo va al principio de la vuelta y no en cualquier lado
- [ ] Qué deja atrás un `revoke(terminate=True)` que la cancelación cooperativa no
- [ ] Por qué cancelar una tarea `pending` no usa el flag
- [ ] Por qué cancelar dos veces da 200 y aprobar dos veces da 409
- [ ] Por qué `cancelled` y `failed` son estados distintos
- [ ] Qué pasa con una tool con efectos que ya se ejecutó

---

# Fase 8 — el worker que muere

Un deploy, un OOM, un `SIGKILL`. La tarea estaba en la vuelta 2 y nadie va a
moverla de `running`, porque el único que podía está muerto.

Los tres puntos críticos: que la conversación **no** quede rota, que alguien de
afuera note la fila huérfana, y entender por qué la reentrega del broker no
alcanza.

## Preparación

```bash
uv run alembic revision --autogenerate -m "heartbeat en tasks"
uv run alembic upgrade head
```

Ahora hacen falta **cinco ventanas**: se suma `beat`, que es un proceso aparte.

```bash
uv run celery -A app.tasks.celery_app worker --loglevel=info   # ejecuta
uv run celery -A app.tasks.celery_app beat   --loglevel=info   # encola el reaper
```

Para probar sin esperar cinco minutos, bajá el umbral en el `.env`:

```
TAREA_SIN_LATIDO_S=20
REAPER_INTERVALO_S=10
```

---

## 1 — El crash **no** rompe la conversación

**Correr.** Matá el worker a mitad de un turno:

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
TID=$(curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' \
  -d '{"prompt":"mostrame mis pedidos, calculá el total y decime la hora en Tokio"}' | jq -r .task_id)

sleep 5
pkill -9 -f "celery.*worker"
```

**Observar.** La consulta de pares huérfanos de la Fase 0: **cero filas**.

```sql
select turn, position, role from messages where conversation_id = 'c_xxx' order by position;
-- el turno que estaba corriendo NO está
select tool_name, iteration from execution_steps where task_id = 't_xxx' order by id;
-- los pasos SÍ están
```

**Por qué.** El turno se guarda **entero en una transacción**: un worker que muere
en la vuelta 2 nunca commiteó nada de ese turno. Esa decisión, que en el mini 9
parecía prolijidad, es lo que hace que un crash sea recuperable.

Los pasos de la traza sí quedaron, porque tienen su propia sesión y commitean
vuelta a vuelta. Y está bien: son auditoría, y querés saber qué alcanzó a hacer
antes de morirse.

**Verificalo — la conversación sigue usable:**

```bash
# levantá el worker de nuevo
curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 7 por 7"}' | jq -r .task_id
```

---

## 2 — La reentrega ocurre, y no alcanza

Ésta es la parte que explica por qué el reaper existe.

**Observar** los logs del worker que acabás de levantar:

```
WARNING tarea id=t_xxx ya no está en pending, se descarta
```

**El broker reentregó el mensaje solo.** Eso lo hace `acks_late` +
`task_reject_on_worker_lost`: el worker murió sin confirmar, así que el mensaje
volvió a la cola y otro lo tomó.

Pero ese worker nuevo entró, vio la fila en `running`, y **el candado de la
idempotencia lo hizo irse sin tocar nada** — que es exactamente lo correcto,
porque la corrida anterior pudo haber ejecutado tools con efectos.

```sql
select id, status, started_at, heartbeat_at, finished_at
from tasks where id = 't_xxx';
-- running | ... | ... | (null)
```

**O sea: la reentrega ocurrió y se descartó, y la fila quedó huérfana igual.**

Ese es el hueco exacto que el reaper cierra. No está para re-ejecutar —de eso ya
se encarga el broker— sino para **cerrar la fila que la reentrega dejó atrás**.

---

## 3 — Alguien de afuera se da cuenta

**Correr.** Con `beat` corriendo y el umbral bajo, esperá:

```bash
watch -n2 "docker compose exec -T postgres psql -U agentic -d agentic_backend -c \
  \"select left(id,14), status, left(coalesce(error,''),40) from tasks where status='running' or error like 'worker_lost%';\""
```

**Observar.** Al pasar el umbral, en la ventana del worker:

```
ERROR app.tasks.reaper tarea id=t_xxx reapeada: el worker dejó de latir
WARNING app.tasks.reaper reaper: 1 tareas cerradas por falta de latido
```

```sql
select status, error, finished_at from tasks where id = 't_xxx';
-- failed | worker_lost: sin latido desde hace más de 20s | 2026-...
```

**Por qué `worker_lost` como prefijo distinguible.** Una tarea que murió con el
worker no es lo mismo que una que falló sola. Mezclarlas en un `error` de texto
libre hace imposible contar cuántas veces se cayó el cluster:

```sql
select case when error like 'worker_lost%' then 'cluster' else 'la tarea' end as culpa,
       count(*)
from tasks where status = 'failed' group by 1;
```

**Rompelo — apagá `beat`.** Matá esa ventana, repetí la prueba 1, y esperá. La
tarea queda en `running` **para siempre**: el reaper está escrito, registrado y
listo, y nadie lo encola.

Es el modo de falla más fácil de no notar de todo el proyecto, porque **todo lo
demás sigue funcionando perfecto**. Las tareas nuevas corren, la API contesta, y
sólo se acumulan filas colgadas que nadie mira.

```sql
-- la consulta que lo delata, y que en producción sería una alerta
select count(*) from tasks
where status = 'running' and heartbeat_at < now() - interval '10 minutes';
```

---

## ✅ La Fase 8 está entendida cuando podés explicar

- [ ] Por qué un crash a mitad de turno no deja `tool_use` huérfanos
- [ ] Por qué los pasos de la traza sí sobreviven y los mensajes no
- [ ] Qué hace el broker solo, y qué queda sin hacer
- [ ] Por qué el worker que recibe la reentrega se va sin tocar nada
- [ ] Por qué el umbral tiene que ser mayor que la vuelta más lenta
- [ ] Qué pasa si `beat` no está corriendo, y por qué cuesta notarlo

---

# Fase 9 — aprobación sin nadie mirando

Cuando el agente corría en el request, el 202 traía el pedido de permiso con los
argumentos exactos. Ahora el request se fue hace seis segundos y **el 202 no
tiene a quién llegarle**. Esta fase cierra esa brecha — la misma por la que antes
tenías que buscar el `tool_use_id` con SQL.

Los tres puntos críticos: que el pedido se pueda ver sin SQL, que una pausa no
bloquee un worker, y que un permiso que nadie decide no quede abierto para
siempre.

## Preparación

```bash
uv run alembic revision --autogenerate -m "task_id en pending_approvals"
uv run alembic upgrade head
```

Reiniciá los tres procesos: API, worker y beat.

---

## 1 — El pedido de permiso llega por el `GET`

**Correr.**

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
ORD=$(qp2 "select id from orders where user_id='u_42' and status='pending' limit 1" -tA)

TID=$(curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d "{\"prompt\":\"cancelá el pedido $ORD\"}" | jq -r .task_id)

sleep 6
curl -s localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | jq '{status, pending_approvals}'
```

**Observar.**

```json
{
  "status": "pending_approval",
  "pending_approvals": [
    {
      "tool_use_id": "toolu_01ABC...",
      "tool_name": "cancel_order",
      "tool_input": {"order_id": "o_xxx"},
      "expires_at": "2026-09-19T..."
    }
  ]
}
```

**Ya no hace falta SQL.** Antes esto salía de `select tool_use_id from
pending_approvals`, que es exactamente el síntoma de una brecha: cuando la
respuesta a una pregunta de negocio requiere entrar a la base, falta un endpoint.

**Por qué el `tool_input` completo.** Quien aprueba tiene que ver *qué* se va a
ejecutar. Un "¿autorizás cancelar un pedido?" sin decir cuál no es una
aprobación, es un trámite.

Y aprobar ahora es un `POST` que también vuelve enseguida:

```bash
TUID=$(curl -s localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | jq -r '.pending_approvals[0].tool_use_id')

curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST \
  localhost:8000/tasks/$TID/approvals/$TUID \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' -d '{"approved":true}'
# 202

sleep 6
curl -s localhost:8000/tasks/$TID -H 'X-User-Id: u_42' | jq -r '.status, .result.answer'
qp2 "select id, status from orders where id = '$ORD';"
```

La **misma** tarea pasó `pending_approval → running → success`. No se creó una
fila nueva: el usuario pidió una cosa y siguió poleando un solo id.

---

## 2 — Una pausa no bloquea un worker

Ésta es la idea estructural de la fase.

**Correr.** Con el worker en concurrencia 1, dejá una aprobación sin resolver y
mandá otra tarea:

```bash
# reiniciá el worker así:
uv run celery -A app.tasks.celery_app worker --loglevel=info -c 1
```

```bash
CID2=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
ORD2=$(qp2 "select id from orders where user_id='u_42' and status='pending' limit 1" -tA)
curl -s -X POST localhost:8000/conversations/$CID2/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d "{\"prompt\":\"cancelá el pedido $ORD2\"}" | jq -r .task_id

sleep 6   # queda en pending_approval, sin decidir

# y ahora OTRA tarea, en otra conversación
CID3=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
TID3=$(curl -s -X POST localhost:8000/conversations/$CID3/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 6 por 6"}' | jq -r .task_id)

sleep 8
curl -s localhost:8000/tasks/$TID3 -H 'X-User-Id: u_42' | jq -r .status
```

**Observar.** `success`. Con **un solo** worker y una aprobación sin resolver, la
tarea nueva corrió igual.

**Por qué.** El mensaje de Celery **terminó** cuando el loop se pausó. El worker
no se quedó esperando: marcó la fila en `pending_approval` y volvió a la cola.

Si se hubiera quedado bloqueado, cada aprobación pendiente regalaría un worker —
con concurrencia 4 alcanzan **cuatro aprobaciones olvidadas** para frenar el
sistema entero. Y nadie relacionaría "el sistema está lento" con "hay cuatro
permisos sin decidir".

```sql
select status, count(*) from tasks group by status;
-- pending_approval | 1   ← detenida, sin ocupar nada
```

**Rompelo — decidí dos veces:**

```bash
curl -s -o /dev/null -w '%{http_code} ' -X POST localhost:8000/tasks/$TID/approvals/$TUID \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' -d '{"approved":true}'
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/tasks/$TID/approvals/$TUID \
  -H 'X-User-Id: u_42' -H 'content-type: application/json' -d '{"approved":true}'
# 202 409
```

409 la segunda, y —lo que importa— **no se encoló una segunda retoma**. El orden
del endpoint es deliberado: se decide primero con un CAS sobre la fila de la
aprobación, y sólo si prendió se encola. Dos POST simultáneos no pueden producir
dos ejecuciones.

Compará con `/cancel`, que devuelve 200 las dos veces: ahí la segunda llamada no
tiene nada que hacer; acá podría significar una segunda cancelación de pedido.

---

## 3 — Un permiso que nadie decide vence

**Correr.** Bajá el TTL en [policy.py](app/agent/policy.py) para no esperar 24 h:

```python
TTL_APROBACION = timedelta(seconds=30)
```

Reiniciá el worker, generá una aprobación y **no la decidas**:

```bash
CID4=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
ORD4=$(qp2 "select id from orders where user_id='u_42' and status='pending' limit 1" -tA)
TID4=$(curl -s -X POST localhost:8000/conversations/$CID4/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d "{\"prompt\":\"cancelá el pedido $ORD4\"}" | jq -r .task_id)

sleep 50
curl -s localhost:8000/tasks/$TID4 -H 'X-User-Id: u_42' | jq -r '.status, .error'
```

**Observar.**

```
failed
approval_expired: nadie decidió sobre 'cancel_order' a tiempo
```

```sql
select tool_use_id, status, decided_at from pending_approvals order by created_at desc limit 3;
-- expired
select status from conversations where id = 'c_xxx';
-- active   ← vuelve a aceptar mensajes
```

**Por qué `failed` y no `cancelled`.** Nadie la canceló: se quedó sin respuesta.
Son cosas distintas y la columna `error` lo dice con un prefijo consultable, como
`worker_lost`.

**Y por qué la conversación vuelve a `active`.** Lo que la tenía frenada ya no se
puede resolver — dejarla en `pending_approval` sería bloquearla para siempre por
un permiso que nadie va a dar.

**Por qué vencer importa más acá que antes.** Con un humano mirando el 202, un
pendiente sin resolver molestaba. Sin nadie mirando, **se acumulan** — y cada uno
deja una conversación bloqueada y una tarea colgada. Y el riesgo de fondo: alguien
autoriza el martes un "cancelá el pedido 991" que el agente propuso el viernes,
cuando el pedido ya se entregó.

Volvé a poner `TTL_APROBACION = timedelta(hours=24)`.

---

## ✅ La Fase 9 está entendida cuando podés explicar

- [ ] Por qué la tarea de Celery termina en vez de esperar la aprobación
- [ ] Por qué es la misma `Task` y no una nueva
- [ ] Por qué se decide **antes** de encolar la retoma
- [ ] Por qué aprobar dos veces da 409 y cancelar dos veces da 200
- [ ] Qué se rompería si al rechazar se borrara el `tool_use` del historial
- [ ] Por qué una aprobación vencida deja la tarea en `failed` y no en `cancelled`

---

# Fase 10 — presupuesto por usuario

El presupuesto de la conversación acota **un hilo**. Éste acota **a la persona**,
y al cruzar conversaciones y workers deja de ser un contador local: pasa a ser un
recurso compartido con concurrencia, que es un problema de base de datos y no de
agentes.

Los tres puntos críticos: que dos tareas en paralelo no se pasen del límite, que
una llamada fallida devuelva lo apartado, y que una reserva huérfana no se quede.

## Preparación

```bash
uv run alembic revision --autogenerate -m "presupuesto por usuario"
uv run alembic upgrade head
```

Bajá el límite en el `.env` para no gastar de verdad:

```
PRESUPUESTO_USUARIO_TOKENS=6000
```

Reiniciá API, worker y beat.

---

## 1 — Dos en paralelo, sólo una pasa

**Correr.** Con el límite bajo, dos tareas al mismo tiempo que juntas no entran:

```bash
CID=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
CID_B=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)

curl -s localhost:8000/users/me/budget -H 'X-User-Id: u_42' | jq -c

# las dos al mismo tiempo, contra el mismo presupuesto
curl -s -X POST localhost:8000/conversations/$CID/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"mostrame mis pedidos y calculá el total"}' | jq -r .task_id &
curl -s -X POST localhost:8000/conversations/$CID_B/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"mostrame mis pedidos y calculá el total"}' | jq -r .task_id &
wait

sleep 12
qp2 "select left(id,14) as tarea, status, left(coalesce(error,''),50) as error from tasks order by created_at desc limit 2;"
curl -s localhost:8000/users/me/budget -H 'X-User-Id: u_42' | jq -c
```

**Observar.** Una `success` y la otra `failed` con `BudgetExceededError`. Y en el
presupuesto, `tokens_reserved` de vuelta en **0**.

**Por qué.** La reserva es un UPSERT con la condición adentro:

```sql
INSERT INTO user_budgets (...) VALUES (...)
ON CONFLICT (user_id, window_start) DO UPDATE
  SET tokens_reserved = user_budgets.tokens_reserved + :est
  WHERE user_budgets.tokens_reserved + user_budgets.tokens_used + :est
        <= user_budgets.tokens_limit
```

Es el mismo compare-and-swap de las transiciones de estado, sobre números en vez
de sobre un enum: **la base arbitra** y el segundo ve cero filas afectadas.

**Rompelo — leé y después escribí.** Reemplazá el cuerpo de `reservar` en
[budget.py](app/agent/budget.py) por la versión ingenua:

```python
fila = db.get(UserBudget, (user_id, _ventana()))
if fila and fila.tokens_reserved + fila.tokens_used + estimado > fila.tokens_limit:
    return False
# ... y recién acá el UPDATE
```

Repetí las dos en paralelo: **las dos pasan**. Los dos procesos leyeron el mismo
número antes de que ninguno escribiera. Ése es el lost update de manual, y no se
arregla con más cuidado en el código — se arregla poniendo la condición adentro
de la sentencia.

---

## 2 — Lo que no se gastó se devuelve

**Correr.** Hacé que la llamada al modelo falle, con el worker apuntando a un
puerto muerto:

```bash
# worker así:
ANTHROPIC_BASE_URL=http://localhost:9999 uv run celery -A app.tasks.celery_app worker --loglevel=info
```

```bash
curl -s localhost:8000/users/me/budget -H 'X-User-Id: u_42' | jq -c
CID2=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
curl -s -X POST localhost:8000/conversations/$CID2/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"calculá 4 por 4"}' | jq -r .task_id

sleep 15   # tres reintentos
curl -s localhost:8000/users/me/budget -H 'X-User-Id: u_42' | jq -c
```

**Observar.** `tokens_used` **no se movió** y `tokens_reserved` volvió a 0 — pese
a que hubo cuatro intentos, cada uno con su reserva.

**Por qué.** El `try/except BaseException` alrededor de la llamada libera lo
apartado antes de re-lanzar. Sin eso, cada timeout le comería presupuesto al
usuario por una llamada que nunca ocurrió — y con reintentos son cuatro por
tarea, acumulándose durante toda la hora que dura la ventana.

`BaseException` y no `Exception` a propósito: un `KeyboardInterrupt` o un
`SystemExit` a mitad de la llamada también tienen que devolver la reserva.

---

## 3 — La reserva huérfana

**Correr.** Matá el worker **entre reservar y liquidar**, que es la única ventana
que el `try/except` no cubre:

```bash
# worker normal de nuevo
CID3=$(curl -s -X POST localhost:8000/conversations -H 'X-User-Id: u_42' | jq -r .conversation_id)
curl -s -X POST localhost:8000/conversations/$CID3/tasks -H 'X-User-Id: u_42' \
  -H 'content-type: application/json' -d '{"prompt":"mostrame mis pedidos y calculá el total"}' | jq -r .task_id

sleep 2    # justo mientras está esperando al modelo
pkill -9 -f "celery.*worker"

curl -s localhost:8000/users/me/budget -H 'X-User-Id: u_42' | jq -c
```

**Observar.** `tokens_reserved` con un número **mayor a 0** y ninguna tarea
corriendo. Eso es presupuesto que el usuario perdió por una llamada que ya no
existe.

Levantá el worker y `beat`, esperá un ciclo:

```
WARNING app.tasks.reaper reaper: 1 presupuestos con reservas huérfanas liberados
```

```bash
curl -s localhost:8000/users/me/budget -H 'X-User-Id: u_42' | jq -c
# tokens_reserved: 0
```

**Por qué funciona sin llevar un registro por tarea.** La regla es una sola:

> **si el usuario no tiene ninguna tarea `running`, no puede haber ninguna reserva
> legítima abierta.**

En reposo, `tokens_reserved` tiene que ser 0. Cualquier otro valor es basura, y
eso se expresa en un `UPDATE ... WHERE NOT EXISTS (...)` sin necesidad de saber
cuánto había reservado cada corrida.

**Y un detalle del endpoint.** La ruta es `/users/me/budget`, no
`/users/{user_id}/budget`:

```bash
curl -s localhost:8000/users/me/budget -H 'X-User-Id: u_7' | jq -c
# el de u_7, no el de u_42
```

Un endpoint que acepta un id de usuario es un endpoint donde hay que acordarse de
verificar que sea el tuyo. Con `me` no hay nada que verificar — el id sale del
canal autenticado y no hay otra forma de pedirlo. Es la misma regla que la de las
tools, un nivel más arriba.

---

## ✅ La Fase 10 está entendida cuando podés explicar

- [ ] Por qué el presupuesto de la conversación se podía leer-y-escribir y éste no
- [ ] Qué hace el `WHERE` adentro del `ON CONFLICT DO UPDATE`
- [ ] Por qué se reserva el estimado y se liquida con el real
- [ ] Por qué el `except` es `BaseException` y no `Exception`
- [ ] Cómo detecta el reaper una reserva huérfana sin registro por tarea
- [ ] Por qué la ruta dice `me` y no `{user_id}`

---

# Fase 11 — la pasada completa

Esta fase **no agrega pruebas nuevas**. Corre las de las diez fases anteriores,
seguidas, sobre un sistema que ya tiene todas las piezas.

Y ése es el punto: **varias van a fallar**. Una prueba de la Fase 2 que deja de
pasar después de la Fase 8 es una regresión que ninguna fase individual podía
detectar, porque cada una se corrió cuando el código todavía no tenía lo que vino
después. Sin suite automática, ésta es la única pasada que las encuentra.

## Preparación: arrancar de cero

Una pasada honesta empieza con la base vacía. Las conversaciones rotas a
propósito, los presupuestos agotados y las tareas colgadas de las fases
anteriores ensucian todo.

```bash
docker compose down -v && docker compose up -d --wait
uv run alembic upgrade head
uv run python -m scripts.seed_orders
```

Y dejá el `.env` en sus valores reales, no los de prueba:

```
TAREA_SIN_LATIDO_S=300
REAPER_INTERVALO_S=60
PRESUPUESTO_USUARIO_TOKENS=200000
```

Con `TTL_APROBACION = timedelta(hours=24)` en `policy.py`.

**Los cinco procesos:**

```bash
uv run uvicorn app.main:app --reload
uv run celery -A app.tasks.celery_app worker --loglevel=info -c 4
uv run celery -A app.tasks.celery_app beat   --loglevel=info
docker compose exec postgres psql -U agentic -d agentic_backend
# + la terminal de los curl
```

## Cómo correrla

De la Fase 0 a la 10, **en orden**, sin saltear los "Rompelo". Anotá dos cosas
por cada una: si pasó, y si tuviste que reiniciar algo para que pasara.

Ojo con las que se pisan entre sí:

| Cuidado con | Por qué |
|---|---|
| **0.1** rompe una conversación a propósito | usá una descartable, no la de las otras pruebas |
| **0.2** deja `get_my_orders` con un parámetro de más | **sacalo** antes de seguir o todo lo demás miente |
| **4.2** y **10.2** levantan el worker con `ANTHROPIC_BASE_URL` falso | volvelo a levantar normal después |
| **5.2** vacía `TIENEN_EFECTOS` | reponelo o la 7 y la 9 pierden sentido |
| **7.1** y **8.1** matan el worker con `pkill` | levantalo antes de la prueba siguiente |
| **9.3** baja el `TTL_APROBACION` a 30s | volvelo a 24 h |

**Después de cada fase, el invariante que no puede fallar nunca:**

```sql
with bloques as (
  select m.conversation_id,
         b->>'type'                            as tipo,
         coalesce(b->>'id', b->>'tool_use_id') as tuid
  from messages m, jsonb_array_elements(m.content) b
  where b->>'type' in ('tool_use','tool_result')
)
select conversation_id, tuid
from bloques group by conversation_id, tuid
having count(*) filter (where tipo='tool_use')
    <> count(*) filter (where tipo='tool_result');
```

Cero filas, siempre. Si aparece una y no la rompiste vos en 0.1, encontraste algo.

---

## Las doce afirmaciones

Al terminar la pasada tenés que poder demostrar estas doce a mano. Es también,
si algún día escribís la suite, su índice exacto.

| # | Afirmación | Fase |
|---|---|---|
| 1 | Llamar dos veces a la tarea ejecuta la tool con efectos **una sola vez** | 5 |
| 2 | Una tarea que arranca y encuentra su fila en `running` no la reprocesa | 5 |
| 3 | Un `BudgetExceededError` no reintenta; un `APIConnectionError` sí | 4 |
| 4 | El flag de cancelación corta al principio de la vuelta y el historial queda válido | 7 |
| 5 | Una tarea `running` con heartbeat viejo termina en `failed`/`worker_lost` | 8 |
| 6 | Un crash a mitad de turno **no** deja `tool_use` huérfanos | 8 |
| 7 | Una tarea en `pending_approval` no bloquea al worker | 9 |
| 8 | Dos `POST` de aprobación encolan **una sola** retoma | 9 |
| 9 | Dos tareas en paralelo contra el mismo presupuesto: sólo una pasa | 10 |
| 10 | `GET /tasks/{id}` de un id inventado da `404`, no "pending" | 3 |
| 11 | El historial nunca tiene un `tool_use` sin su `tool_result` | 0 |
| 12 | El payload que cruza el broker no lleva datos de usuario | 2 |

## El estado final, en una consulta

```sql
select
  (select count(*) from conversations)                                as conversaciones,
  (select count(*) from tasks)                                        as tareas,
  (select count(*) from tasks where status = 'success')               as ok,
  (select count(*) from tasks where status = 'failed')                as fallidas,
  (select count(*) from tasks where status = 'cancelled')             as canceladas,
  (select count(*) from tasks where error like 'worker_lost%')        as por_crash,
  (select count(*) from tool_executions)                              as tools_con_candado,
  (select count(*) from pending_approvals where status = 'expired')   as permisos_vencidos,
  (select coalesce(sum(tokens_reserved), 0) from user_budgets)        as reservas_abiertas;
```

**`reservas_abiertas` tiene que ser 0** con todo quieto. Cualquier otro número es
presupuesto que alguien perdió.

## Lo que esta pasada NO cubre

Decirlo es parte de la fase:

- **Regresiones futuras.** Ésta es una foto. Un cambio mañana no la vuelve a
  correr; una suite sí.
- **Las carreras de verdad.** Las pruebas 9 y 10 fuerzan concurrencia con dos
  `curl` en paralelo, que es una aproximación grosera. Una carrera real necesita
  repetición y control de tiempos.
- **El comportamiento del modelo.** Todo esto verifica el sistema alrededor del
  agente. Que el agente *razone bien* es otra cosa, y se mide con evals.

---

## ✅ El proyecto está terminado cuando

- [ ] La pasada completa corre de la Fase 0 a la 10 sin sorpresas
- [ ] Las doce afirmaciones se pueden demostrar a mano
- [ ] `reservas_abiertas` queda en 0 con el sistema quieto
- [ ] La consulta de pares huérfanos da cero filas
- [ ] Podés contestar las preguntas de [CHECK_LEARNING.md](./CHECK_LEARNING.md)
      sin abrir el código

Y la que vale más que todas juntas, porque es la que te van a preguntar:

> **Escribiste un agente que corre en un request. Ahora tiene que correr en un
> worker. ¿Qué deja de ser gratis?**
