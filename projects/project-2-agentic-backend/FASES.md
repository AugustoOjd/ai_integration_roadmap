# 🗺️ PROJECT 2 — Plan por fases

Cada fase es **autocontenida**: explica su concepto desde cero, se construye
sola, se verifica sola y se puede entender sin haber leído las otras. Las
dependencias reales son la Fase 0 (el mini 9 andando en sincrónico, que es la red
de seguridad de todo lo demás) y tres pares que son dos mitades del mismo
problema: 4→5, 6→7 y 5,7→8.

El hilo conductor es uno solo: **el agente ya no corre adentro de un request**.

En el mini 9 el turno era sincrónico de punta a punta: mandabas el mensaje, el
proceso que atendía el request corría el loop, y devolvía la respuesta. Todo lo
que agrega este proyecto —idempotencia, una sola fuente de verdad, progreso,
cancelación, recuperación de un crash, aprobación desatendida— es la misma
consecuencia de una sola decisión: **el loop corre en otro proceso, al que no le
podés devolver nada y que se puede morir en cualquier momento.**

| Fase | Tema | Depende de |
|------|------|-----------|
| 0 | Esqueleto: el mini 9 portado a sincrónico, sin colas | — |
| 1 | Conversaciones y tareas: el modelo de datos, y el agente corriendo en el request | 0 |
| 2 | Celery en el medio: el worker y la frontera del proceso | 1 |
| 3 | Una sola fuente de verdad: el estado es tu tabla | 2 |
| 4 | Reintentos (mitad 1): qué se reintenta y qué no | 3 |
| 5 | Idempotencia (mitad 2): la tarea que corre dos veces | 4 |
| 6 | Progreso: la traza consultable mientras corre | 3 |
| 7 | Cancelación cooperativa | 6 |
| 8 | El worker que muere: heartbeat y reaper | 5, 7 |
| 9 | Aprobación sin nadie mirando | 3, 8 |
| 10 | Presupuesto por usuario, no por sesión | 3 |
| 11 | Verificación manual completa + CHECK_LEARNING | todas |

---

## Las seis decisiones, ya tomadas

Del `ANTES_DE_EMPEZAR.md` §5. Están acá para que el plan se lea solo.

| # | Pregunta | Respuesta | Fase donde se materializa |
|---|---|---|---|
| 1 | ¿Async en el worker, o capa sincrónica? | **Capa sincrónica** | 0, 2 |
| 2 | ¿Tool sensible en tarea desatendida? | **Se espera** a un humano | 9 |
| 3 | ¿Tarea o conversación? | **Una conversación tiene muchas tareas** | 1 |
| 4 | ¿Cómo se entera el usuario? | **Polling** sobre `GET /tasks/{id}` | 6 |
| 5 | ¿Presupuesto de quién? | **Por usuario** | 10 |
| 6 | ¿Reintentos? | **3, exponencial con jitter**, con lista explícita de qué no se reintenta | 4 |

Modelo: `claude-haiku-4-5`, el mismo del mini 9. Un loop son varias llamadas y el
costo se multiplica por vuelta, por tarea y por reintento.

---

## Qué vas a aprender (el mapa conceptual)

1. **Un `task_id` no es una respuesta, es una promesa.** Cuando el request
   devuelve antes de que el trabajo empiece, el estado de la tarea **es** el canal
   de comunicación: los errores, el progreso y las pausas se cuentan ahí o no se
   cuentan.
2. **La frontera del proceso es una frontera de serialización.** Lo que cruza a
   Celery es JSON sobre Redis. No cruzan sesiones de base, ni clientes, ni
   objetos: cruza un `task_id` y un `user_id`, y del otro lado se **reconstruye**
   todo. Es la misma reconstrucción de la Fase 6 del mini 9.
3. **"Exactly once" no existe; "at least once" + idempotencia sí.** Celery te
   garantiza que la tarea corre *al menos* una vez. Que el efecto ocurra una sola
   vez es responsabilidad tuya, y se consigue con una clave estable, no con
   cuidado.
4. **Dos sistemas con estado siempre discrepan.** El backend de Celery y tu tabla
   van a decir cosas distintas. La solución no es sincronizarlos: es que uno de
   los dos no sea autoridad de nada.
5. **Cancelar no es matar.** Un proceso muerto a mitad de turno deja un `tool_use`
   sin `tool_result` y la conversación rota para siempre. Cancelar es pedir
   permiso para terminar, y esperar a que el loop llegue a un punto seguro.
6. **La atomicidad del turno es lo que te salva del crash.** El mini 9 guardó el
   turno entero en una transacción "porque estaba bien". Acá cobra: un worker que
   muere en la vuelta 2 no deja basura en `messages`, porque nunca commiteó.
7. **Una pausa es el final de una tarea, no una tarea que espera.** Bloquear un
   worker esperando a un humano es regalar un worker. La aprobación termina la
   tarea y la aprobación **encola otra**.

---

## Nota sobre las comparaciones

Cada fase cierra con **"Cómo lo resuelven los frameworks"**: qué pieza de Pydantic
AI o de LangGraph cubre eso, y qué parte sigue siendo tuya igual.

No están ahí para hacerte dudar de escribirlo a mano. Están por lo contrario: si
hacés la fase y después leés qué nombre le pone el framework a lo que acabás de
construir, entendés *por qué* esa pieza existe en vez de aprender su API. Y en
varias fases la respuesta honesta es "no lo cubre ninguno de los dos", que es
justamente lo que hace que este proyecto valga la pena.

**Son notas al margen, no una fase.** Este proyecto se hace entero a mano y
termina en la Fase 12. Las reescrituras con framework son proyectos propios, y
van en este orden:

    PROJECT 3 (LangChain)  →  PROJECT 4 (Pydantic AI)  →  PROJECT 5 (LangGraph)
       una llamada              un turno                     una corrida

El 4 reescribe tu capa `app/agent/`; el 5 reescribe las fases de persistencia,
pausa y recuperación. Los conceptos que se citan acá (checkpointer, `interrupt`,
`RunContext`, `UsageLimits`) son estables; los nombres exactos de la API
conviene verificarlos al llegar a esos proyectos, porque ambas librerías se
mueven rápido.

---

## Fase 0 — Esqueleto: el mini 9 portado a sincrónico

### Concepto aislado

Este proyecto no empieza en cero: empieza con el mini 9 funcionando. Y no empieza
por Celery, a propósito. **Un sistema distribuido que nunca funcionó en un solo
proceso es imposible de debuggear**, porque cuando algo falle no vas a saber si el
bug es tuyo o del transporte.

Lo único que cambia acá es el color del código: async → sync. Es la respuesta a la
decisión §5.1, y es la que hay que tomar antes de escribir la primera tarea porque
cambiarla después toca todo.

Por qué sincrónico: **las tareas de Celery son funciones sincrónicas**. Todo lo que
traés del mini 9 es async (`AsyncSession`, `asyncpg`, `AsyncAnthropic`,
`async def run_agent`). Las tres salidas eran `asyncio.run()` adentro de la tarea,
duplicar la capa de datos en sincrónico, o un pool alternativo. Elegiste la
segunda: más aburrida, sin un event loop nuevo por tarea, sin conexiones atadas a
un loop que ya no existe.

El mapeo es mecánico:

| Mini 9 (async) | Project 2 (sync) |
|---|---|
| `create_async_engine` + `async_sessionmaker` | `create_engine` + `sessionmaker` |
| `postgresql+asyncpg://` | `postgresql+psycopg://` |
| `AsyncSession`, `await db.execute(...)` | `Session`, `db.execute(...)` |
| `AsyncAnthropic` | `Anthropic` |
| `async def run_agent(...)` | `def run_agent(...)` |

Y una consecuencia que **no** es mecánica y es la trampa de la fase: si un
endpoint sigue declarado `async def` y adentro hace una consulta sincrónica,
**bloqueás el event loop** y tiras abajo la concurrencia de toda la app. Los
handlers de FastAPI que tocan la base pasan a ser `def` a secas: FastAPI los corre
en su threadpool y cada uno tiene su thread. Es un cambio de una palabra por
endpoint y es el que más se olvida.

Lo demás se copia con el cerebro apagado. El primer commit tiene que ser "mini 9
andando en sincrónico, con su conversación de dos turnos funcionando": a partir
de ahí, todo lo que se
rompa es atribuible a lo nuevo.

Se suma **Alembic**, que en el mini 9 era opcional. Acá la tabla de tareas crece
fase a fase (`status`, `heartbeat_at`, el flag de cancelación, la FK a
conversación) y sin migraciones cada fase te obliga a tirar la base.

### Qué construimos

- `pyproject.toml` — lo del mini 9 sin los extras async: `sqlalchemy` (sin
  `[asyncio]`), `psycopg[binary]`, `anthropic`, `fastapi`, `uvicorn`,
  `pydantic-settings`, **`alembic`**. Sin `celery` todavía: no se declara una
  dependencia que ninguna línea importa.
- `docker-compose.yml` — un Postgres, nada más. Redis llega en la Fase 2.
- `app/db.py` — `create_engine`, `sessionmaker`, dependencia `get_db`
- `app/models.py`, `app/repository.py`, `app/context.py`, `app/budget.py`,
  `app/policy.py`, `app/deps.py`, `app/tools/`, `app/agent.py` — portados
- `alembic/` — la migración inicial generada del estado actual de los modelos
- `PRUEBAS.md` — las tres verificaciones manuales de esta fase

### Cómo verificarlo

```bash
docker compose up -d
uv run alembic upgrade head
uv run python -m scripts.seed_orders   # datos para probar a mano
uv run uvicorn app.main:app --reload
```

Y la verificación que importa de verdad: una conversación de dos turnos con tools,
igual que en el mini 9. Si el segundo turno recuerda el primero, el port está bien.

### Deberías poder responder

- ¿Por qué un handler de FastAPI que hace consultas sincrónicas no debe ser `async def`?
- ¿Qué problema te habría traído `asyncio.run()` adentro de una tarea de Celery, y
  por qué es el mismo que resolviste en el `conftest.py` del mini 9?
- ¿Por qué el primer commit es un port sin funcionalidad nueva?

### Cómo lo resuelven los frameworks

- **Pydantic AI** — el problema no existe: `Agent` expone `run()` (async) y
  `run_sync()` (sincrónico) sobre el mismo código. `run_sync()` maneja el event
  loop internamente. Ojo con la conclusión fácil: eso resuelve *la llamada al
  modelo*, no tu capa de datos. Tu `repository.py` seguiría teniendo que elegir
  color igual.
- **LangGraph** — mismo planteo: grafos invocables en sync (`invoke`) y async
  (`ainvoke`), con checkpointers en las dos variantes (`PostgresSaver` /
  `AsyncPostgresSaver`). La decisión §5.1 se convierte en elegir una clase.
- **Lo que igual sería tuyo** — nada de esto te ahorra decidir; te ahorra
  reescribir. Y la trampa del `async def` con I/O sincrónico adentro es de
  FastAPI, no del framework de agentes: la tendrías igual.

---

## Fase 1 — Conversaciones y tareas: el agente corriendo en el request

### Concepto aislado

Dos cosas pasan acá, y la primera es un modelo de datos.

**Una conversación tiene muchas tareas** (decisión §5.3). El mini 9 modeló
conversaciones (`sessions`); el README de P2 modela tareas. No son lo mismo y
confundirlas es un refactor caro:

| Tabla | Qué es | Vive |
|---|---|---|
| `conversations` | el hilo: dueño, historial, presupuesto | para siempre |
| `tasks` | **una ejecución** del agente sobre esa conversación | minutos |
| `messages` | el historial, con su `content` crudo | pertenece a la conversación |
| `execution_steps` | la traza | pertenece a la **tarea** |

La prueba de que la distinción es correcta: el historial no puede pertenecer a la
tarea, porque el turno 2 necesita lo que dejó el turno 1 y son tareas distintas.
Y la traza no puede pertenecer a la conversación, porque "¿cómo va *esto* que
pedí?" se pregunta de una ejecución, no de un hilo.

Lo segundo: **el endpoint crea la tarea y corre el agente en el mismo request**.
Sin worker. Es feo y es deliberado: te obliga a escribir la máquina de estados y
el `GET` que la lee antes de que haya un proceso separado que los complique. El
`POST` va a tardar diez segundos y está bien; en la Fase 2 eso se vuelve un
`task_id` inmediato y **lo único que cambia es quién llama a `run_agent`**.

El estado de la tarea nace acá, y nace como una máquina, no como un string
suelto:

```
pending ──> running ──> success
                   ├──> failed
                   ├──> cancelled          (Fase 7)
                   └──> pending_approval   (Fase 9)
```

### Qué construimos

- `app/models.py` — `Conversation` y `Task` (con `status`, `created_at`,
  `started_at`, `finished_at`, `result` JSONB, `error`), y `ExecutionStep` con FK
  a `Task`
- Migración de Alembic con los cambios
- `app/schemas/tasks.py` — request y response
- `app/routes/tasks.py` — `POST /conversations/{id}/tasks` (crea, corre, guarda) y
  `GET /tasks/{id}`
- `app/services/task_state.py` — las transiciones permitidas, en un solo lugar

### Cómo verificarlo

```bash
curl -X POST localhost:8000/conversations -d '{"user_id": "u_42"}'
curl -X POST localhost:8000/conversations/c_abc/tasks -d '{"prompt": "calculá 42*2"}'
curl localhost:8000/tasks/t_001
```

El `POST` tarda lo que tarde el agente. Después, la verificación del modelo de
datos: mandá una segunda tarea a la misma conversación con un prompt que dependa
de la primera (*"¿y por 3?"*). Si contesta 252, el historial vive en la
conversación y no en la tarea.

### Deberías poder responder

- ¿Por qué el historial cuelga de la conversación y la traza de la tarea?
- ¿Qué se rompe si modelás "una tarea es una conversación"?
- ¿Por qué escribir la máquina de estados antes de tener un worker?

### Cómo lo resuelven los frameworks

- **LangGraph** — el `thread_id` del checkpointer es exactamente tu
  `conversation_id`: el estado del grafo se guarda indexado por hilo, y cada
  invocación sobre el mismo `thread_id` continúa donde quedó. Lo que **no** trae
  es el concepto de "tarea": una ejecución con identidad propia, estado propio y
  consultable por separado. Eso es tuyo, y es la mitad del proyecto.
- **Pydantic AI** — no modela nada de esto. Te da `all_messages_json()` para
  serializar el historial y un `ModelMessagesTypeAdapter` para leerlo de vuelta;
  dónde lo guardás y con qué forma es decisión tuya. Es honesto: el framework
  cubre el turno, no la persistencia.
- **Lo que sigue siendo tuyo** — la máquina de estados. Ni Pydantic AI ni
  LangGraph tienen un `status` de negocio con transiciones válidas, porque no es
  un problema de agentes: es un problema de tareas, y empieza en la Fase 3.

---

## Fase 2 — Celery en el medio: el worker y la frontera del proceso

### Concepto aislado

Ahora sí. Y el cambio es más chico de lo que parece, justamente porque la Fase 1
existió: el endpoint deja de llamar a `run_agent` y encola.

```python
# Fase 1: el request corre el agente
task = create_task(db, conversation_id, prompt)
run_agent(task.id, db)                       # diez segundos acá
return task

# Fase 2: el request encola y se va
task = create_task(db, conversation_id, prompt)
execute_agent_task.delay(str(task.id))       # milisegundos
return task                                   # status = "pending"
```

Lo importante de esa línea es **qué viaja**: un `task_id`, un string. No viaja la
sesión de base, ni el objeto `Task`, ni el cliente de Anthropic, ni el `AgentDeps`.
Lo que cruza a Celery es JSON serializado sobre Redis, y del otro lado hay que
**reconstruirlo todo** desde la base. Es la misma reconstrucción de la Fase 6 del
mini 9, con otro disparador.

Dos consecuencias que hay que mirar de frente:

**1. El `user_id` tiene que viajar** (la vuelta de tuerca del §2.2). El worker no
tiene request, no tiene header, no tiene sesión HTTP. El `AgentDeps` que en el
mini 9 se construía en el endpoint desde el usuario autenticado, acá se
reconstruye en el worker leyendo la tarea. Y como el mensaje viaja por Redis,
**cualquiera con acceso al broker lo puede leer y escribir**: la tarea es un
mensaje confiable sólo si tu Redis lo es. No pongas en el payload nada que no
pondrías en una tabla sin cifrar.

**2. El engine y el `fork` del worker.** El worker de Celery (pool prefork) arranca
un proceso maestro y forkea hijos. Si el engine de SQLAlchemy se creó al importar
el módulo —que es lo normal—, los hijos heredan los **descriptores de las
conexiones ya abiertas** y dos procesos terminan escribiendo en el mismo socket de
Postgres. Los síntomas son geniales: errores de protocolo, resultados de la query
de otro, cuelgues intermitentes.

La solución es una señal:

```python
from celery.signals import worker_process_init

@worker_process_init.connect
def reset_pool(**kwargs):
    # Cada hijo tira el pool heredado y abre conexiones propias.
    # close=False: NO cierra los sockets heredados, sólo los suelta —
    # cerrarlos mataría las conexiones que todavía usa el proceso padre.
    engine.dispose(close=False)
```

Es el primo sincrónico del problema que el `ANTES_DE_EMPEZAR` describe con
`NullPool`: la causa es la misma —un recurso creado en un contexto y usado en
otro— y es la misma causa por la que en el mini 9 el `conftest.py` necesitaba
`NullPool`.

### Qué construimos

- `celery[redis]` en las dependencias, y Redis en el `docker-compose.yml`
- `app/celery_app.py` — la config (broker, backend, serializer, timezone)
- `app/tasks/agent_tasks.py` — `execute_agent_task(task_id)`: abre su propia
  sesión de base, carga la tarea, reconstruye el `AgentDeps` desde el `user_id`,
  corre el loop, guarda
- La señal `worker_process_init` que resetea el pool
- `POST /conversations/{id}/tasks` devuelve `202` con el `task_id`, sin esperar

### Cómo verificarlo

```bash
docker compose up -d
uv run celery -A app.celery_app worker --loglevel=info   # otra terminal
curl -X POST localhost:8000/conversations/c_abc/tasks -d '{"prompt": "..."}'  # responde ya
curl localhost:8000/tasks/t_002    # pending → running → success
```

Después el experimento que enseña la fase: levantá el worker con `-c 4`, mandá
diez tareas de golpe, y mirá los logs de Postgres. Si te olvidaste del
`worker_process_init`, vas a ver errores de protocolo que no tienen nada que ver
con tu código.

### Deberías poder responder

- ¿Por qué se encola el `task_id` y no el objeto `Task`?
- ¿De dónde saca el worker el `user_id`, y por qué no puede sacarlo del prompt?
- ¿Qué pasa si el engine se creó antes del `fork`?
- ¿Qué de tu payload de Celery sería un problema si alguien lee tu Redis?

### Cómo lo resuelven los frameworks

- **Ninguno de los dos.** Y vale decirlo fuerte porque es el punto donde el
  proyecto se separa de todo lo que miramos: Pydantic AI y LangGraph corren un
  agente **dentro de tu proceso**. Que ese proceso sea un worker de Celery les es
  indiferente, y la frontera de serialización, el `fork` y el `user_id` que viaja
  siguen siendo problemas tuyos, idénticos.
- **La excepción, y no es gratis** — Pydantic AI tiene integraciones de ejecución
  durable (Temporal, DBOS, Prefect, Restate) y LangGraph tiene su propio servidor
  de ejecución. Las dos cubren esta fase de verdad, pero cubriéndola te sacan
  Celery: no es "agrego una librería", es "cambio de sistema de colas". Es
  exactamente el trade que el `ANTES_DE_EMPEZAR` describe con Temporal y que
  decidimos no hacer.
- **La pregunta que vale** — si un framework sólo cubre esta fase reemplazando el
  transporte, ¿qué aprendés de él además de su API? Ésa es la pregunta que
  contestan los PROJECT 4 y 5.

---

## Fase 3 — Una sola fuente de verdad: el estado es tu tabla

### Concepto aislado

Celery tiene su propio result backend, con sus propios estados: `PENDING`,
`STARTED`, `SUCCESS`, `FAILURE`, `RETRY`, `REVOKED`. Tu tabla `tasks` también
tiene un `status`. Van a discrepar. **Siempre discrepan.**

La regla: **elegí una sola fuente de verdad y que sea tu tabla.** El backend de
Celery es un detalle de transporte.

Los tres motivos, concretos:

1. **No sabe de tu dominio.** `pending_approval` y `cancelled` no existen en su
   vocabulario, y son dos de tus cinco estados.
2. **No sobrevive a una purga de Redis.** Un `FLUSHDB` para destrabar la cola —que
   vas a hacer, está en el README del proyecto— te borra el historial de estados de
   todo.
3. **Su `PENDING` significa "no sé nada de esta tarea".** Es **indistinguible de un
   id inventado**. `AsyncResult("cualquier-cosa").status` devuelve `PENDING`, no un
   error. Un `GET /tasks/{id}` construido sobre eso le contesta "en cola" a un id
   que no existió nunca.

Consecuencia de código: **`GET /tasks/{id}` nunca toca `AsyncResult`.** Lee tu
tabla. Si la fila no está, es `404` — que es la respuesta correcta y la que Celery
no te puede dar.

Y como ahora hay varios procesos escribiendo el mismo `status`, las transiciones
dejan de ser asignaciones y pasan a ser **compare-and-swap**:

```python
# No: "leo, decido y escribo" — entre el leer y el escribir pasa cualquier cosa.
# Sí: la condición viaja en el UPDATE y la base arbitra.
UPDATE tasks SET status = 'running', started_at = now()
WHERE id = :task_id AND status = 'pending'
```

Si ese `UPDATE` afecta **cero filas**, alguien te ganó de mano: otro worker ya la
tomó, o el usuario la canceló. No es un error — es información, y es el candado
que la Fase 5 va a usar contra la doble ejecución.

### Qué construimos

- `app/services/task_state.py` — una función por transición, cada una un
  `UPDATE ... WHERE status = <esperado>` que devuelve si prendió
- `GET /tasks/{id}` leyendo sólo la tabla, con `404` real
- `GET /tasks?status=running` — el listado con filtro
- Config de Celery: `result_backend` apagado o declarado explícitamente como
  "sólo para debug", con un comentario que diga por qué

### Cómo verificarlo

`GET /tasks/inventado` tiene que dar `404`. Después, con el worker apagado, mandá
una tarea: queda `pending` en tu tabla. Levantá el worker y mirala pasar a
`running` y a `success`. Y el experimento que cierra el tema: corré un `FLUSHDB`
en Redis y volvé a pedir `GET /tasks/{id}` de una tarea vieja. Tu tabla contesta
igual.

### Deberías poder responder

- ¿Por qué el `PENDING` de Celery no sirve para contestar un `GET`?
- ¿Qué devolvés si el `UPDATE ... WHERE status = 'pending'` afecta cero filas?
- ¿Para qué sirve entonces el result backend de Celery, si sirve para algo?

### Cómo lo resuelven los frameworks

- **LangGraph — y acá empeora las cosas.** Su checkpointer trae sus propias tablas
  con su propio estado por `thread_id`. Pasarías de dos estados que reconciliar
  (Celery + tu tabla) a **tres**, en la fase cuyo objetivo declarado es reducirlos
  a uno. Su estado es del *grafo* (en qué nodo va), no de tu *negocio* (si la tarea
  está aprobada, cancelada o sin presupuesto), así que tampoco reemplaza al tuyo:
  se suma.
- **Pydantic AI** — no guarda estado. Te devuelve el historial y vos decidís qué
  hacer con él. Para esta fase es la postura más compatible con el diseño, por
  omisión más que por decisión.
- **La lección transferible** — "una sola fuente de verdad" es un principio de
  sistemas, no una feature. Cuantos más frameworks con estado sumás, más caro se
  vuelve sostenerlo. Vale tenerlo presente al evaluar cualquier librería que
  ofrezca persistencia "gratis".

---

## Fase 4 — Reintentos (mitad 1): qué se reintenta y qué no

### Concepto aislado

Esta fase y la 5 son las dos mitades de un mismo problema: los reintentos lo
crean, la idempotencia lo defiende. Van juntas y en este orden.

Lo primero, que es lo que casi nadie escribe: **no lo escribas vos**. Celery ya
trae `autoretry_for`, `retry_backoff`, `retry_jitter` y `max_retries`. El
`base_task` del mini 7 tiene que *configurarlos*, no reimplementarlos.

Lo segundo, que es la fase entera: **qué NO se reintenta.**

Un `BudgetExceededError` no se arregla reintentando: se va a agotar igual las tres
veces, tres veces más caro si alguna llegó a llamar al modelo. Un
`APIConnectionError` sí: el mundo se cayó un segundo y se levantó.

La regla que ordena todo: **se reintenta lo que depende del mundo, no lo que
depende de tu estado.**

| Se reintenta | No se reintenta |
|---|---|
| `APIConnectionError`, timeouts | `BudgetExceededError` |
| `APIStatusError` 5xx | Input de tool inválido |
| `RateLimitError` | Tool inexistente |
| `OperationalError` de Postgres | `max_iterations` agotado |
| | Tarea cancelada |
| | Cualquier `400` del API |

Dos detalles que separan una implementación correcta de una que parece correcta:

- **`RateLimitError` no usa tu backoff.** La respuesta trae un header `retry-after`
  con el tiempo real. Tu exponencial es una adivinanza; ese número no.
- **El jitter no es cosmético.** Sin él, diez tareas que fallan juntas por un
  incidente reintentan **exactamente a la vez**, tres veces seguidas. Es un
  ataque de denegación de servicio contra tu propio proveedor, y se arregla con
  un flag.

Un error permanente no re-lanza para reintentar: marca la tarea `failed` con su
razón y termina. Y cuando se agotan los reintentos de uno temporal, el hook
`on_failure` del `base_task` del mini 7 escribe la dead letter queue.

### Qué construimos

- `app/tasks/base_task.py` — portado del mini 7: `autoretry_for` con la tupla de
  temporales, `retry_backoff=True`, `retry_jitter=True`, `retry_backoff_max=60`,
  `max_retries=3`
- `app/errors.py` — la jerarquía, con una marca explícita de qué es temporal y qué
  es permanente (una clase base `PermanentError` / `TransientError` deja la
  decisión en un lugar y no en la tupla de cada tarea)
- Manejo especial de `RateLimitError`: `retry(countdown=retry_after)`
- `on_failure` → dead letter queue + `status = 'failed'` con `error`
- `task.retries` persistido en tu tabla, para poder contarlos sin Celery

### Cómo verificarlo

Una tool de prueba que falle con un error temporal las dos primeras veces y ande a
la tercera: la tarea tiene que terminar en `success` con `retries = 2`. Después la
misma prueba con un `BudgetExceededError`: tiene que terminar en `failed`
**inmediatamente**, con `retries = 0`. Si reintentó, la clasificación está mal.

Y mirá los tiempos entre reintentos en los logs: si son idénticos, el jitter no
está activo.

### Deberías poder responder

- ¿Por qué un `BudgetExceededError` no se reintenta?
- ¿Por qué el backoff lleva jitter?
- ¿Por qué `RateLimitError` no usa tu backoff sino el header de la respuesta?
- ¿Qué diferencia hay entre "falló y reintenta" y "falló definitivamente" en tu tabla?

### Cómo lo resuelven los frameworks

- **Los dos tienen reintentos, pero de otra cosa.** Pydantic AI reintenta la
  *llamada al modelo* y la validación de los argumentos de una tool (si el modelo
  manda un JSON que no valida, se lo devuelve y le pide que corrija). LangGraph
  tiene políticas de reintento por nodo. Ninguno reintenta *la tarea*, porque en
  su mundo no hay tarea: hay una función que vos invocaste.
- **Lo que sí vale robarles** — la clasificación entre temporal y permanente es la
  misma idea que tienen adentro; que se llame `TransientError` o de otra forma es
  lo de menos. Y el reintento de validación de Pydantic AI es genuinamente una
  cosa que tu registry no hace: cuando el modelo manda un input inválido, vos lo
  tratás como error permanente y ellos le dan al modelo una chance de corregirse.
  Es una mejora concreta que podrías portar.
- **Lo que sigue siendo tuyo** — todo el resto: la tupla de qué se reintenta, el
  `retry-after`, la DLQ y el `status` que distingue "reintentando" de "muerto".

---

## Fase 5 — Idempotencia (mitad 2): la tarea que corre dos veces

### Concepto aislado

**No es una posibilidad, es el diseño.**

Con `acks_late=True` —que es lo que querés, porque confirma la tarea *después* de
ejecutarla y así no se pierde nada si el worker muere— un worker que muere
**después de ejecutar pero antes de confirmar** hace que el broker le entregue la
misma tarea a otro. Sin `acks_late` no pasa esto, pero perdés tareas en cada
deploy. Elegiste no perderlas; el precio es este.

Y tu tarea llama a un LLM que ejecuta tools con efectos. **Dos veces significa dos
mails, dos reservas, dos cobros.**

La defensa tiene dos capas, y hacen falta las dos.

**Capa 1 — el candado de la fila.** Es el compare-and-swap de la Fase 3, cobrando:

```python
# Una tarea que arranca y no logra pasar de 'pending' a 'running'
# es una tarea que otro ya tomó. No la reprocesa: se va.
if not transition(task_id, expected="pending", new="running"):
    return
```

Esto cubre la reentrega completa. Lo que **no** cubre es el caso feo: la tarea que
ya estaba `running`, ejecutó dos tools, y murió. La reentrega la ve `running` y se
va — pero esas dos tools ya corrieron y el turno quedó a medio hacer. Ese caso lo
cierra la Fase 8.

**Capa 2 — la clave de idempotencia de la tool.** Y acá está el motivo por el que
en el mini 9 el `tool_use_id` es la clave primaria de la aprobación y no un id
propio: **es estable entre reintentos**, porque viene del historial persistido, no
de un `uuid4()` nuevo en cada corrida.

```
tool_executions: tool_use_id (PK), task_id, tool_name, status, result, created_at
```

El flujo: antes de ejecutar una tool con efectos, insertás la fila. Si la
`UniqueConstraint` rebota, ya se ejecutó: devolvés el `result` guardado en vez de
volver a ejecutar. Es "que equivocarse sea imposible" en vez de "que nadie se
equivoque" — la regla §2.4, aplicada donde más duele.

**La parte honesta y difícil**, que conviene escribir en un comentario y no
tapar: insertar la fila y ejecutar el efecto **no son atómicos**. Si el proceso
muere entre las dos cosas, la fila queda `in_flight` y no hay forma de saber desde
tu base si el mail salió. Ninguna. Las salidas reales son tres, y ninguna es
gratis: preguntarle al proveedor si el efecto ocurrió (si su API lo permite),
mandarle al proveedor *tu* clave de idempotencia para que él deduplique (lo que
hacen Stripe y similares), o decidir por política qué se prefiere para esa tool
—un mail duplicado suele ser mejor que un mail perdido; un cobro duplicado, nunca—.
Esa decisión es de negocio y va escrita al lado de la lista de tools sensibles.

### Qué construimos

- `acks_late=True` y `task_reject_on_worker_lost=True` en el `base_task`
- El chequeo de estado al entrar a la tarea, con el CAS de la Fase 3
- `app/models.py` — `ToolExecution` con `tool_use_id` como PK
- `app/tools/registry.py` — las tools marcadas con efectos pasan por el registro de
  idempotencia; las de sólo lectura no (no tiene sentido pagar una fila por un
  `calculate`)
- La política por tool para el caso `in_flight`, explícita y comentada

### Cómo verificarlo

El test que **es** la fase: invocá la función de la tarea dos veces con el mismo
`task_id` y verificá que la tool con efectos se ejecutó una sola vez — mirando la
tabla de efectos, no el valor de retorno.

Después, la prueba manual que vale más que el test: mandá una tarea que use una
tool con efectos y matá el worker con `SIGKILL` mientras corre. Levantalo de nuevo
y mirá qué pasa cuando el broker reentrega.

### Deberías poder responder

- ¿Por qué `acks_late=True` crea este problema, y por qué lo querés igual?
- ¿Por qué el `tool_use_id` sirve de clave y un `uuid4()` no?
- ¿Qué hacés con una fila `in_flight` que quedó de un proceso muerto?
- ¿Qué tools **no** necesitan pasar por el registro de idempotencia?

### Cómo lo resuelven los frameworks

- **LangGraph — parcialmente, y es su mejor carta.** Con un checkpointer, el
  estado se guarda paso a paso; reinvocar con el mismo `thread_id` **retoma desde
  el último checkpoint** en vez de reejecutar los nodos completados. Eso cubre
  buena parte de la reentrega de Celery, y es genuinamente más de lo que da
  cualquier otra opción que miramos.
- **Pero el agujero real sigue abierto, en los dos.** Una tool con efectos que se
  ejecutó y todavía no llegó al checkpoint se vuelve a ejecutar igual. Ningún
  framework sabe que `send_notification` manda un mail: no hay clave de
  idempotencia por tool en ninguno de los dos. La ventana se achica; no se cierra.
- **Pydantic AI** — no cubre nada de esto por sí solo. Sí lo cubre a través de sus
  integraciones durables (Temporal), que es otra vez "cambiar Celery", no "agregar
  una librería".
- **Lo que sigue siendo tuyo, sí o sí** — la tabla `tool_executions`, la decisión
  de qué tools tienen efectos, y la política para el `in_flight` ambiguo. Esto es
  irreductiblemente tuyo y es el corazón del proyecto.

---

## Fase 6 — Progreso: la traza consultable mientras corre

### Concepto aislado

En el mini 9 el turno era opaco: terminaba y devolvía todo. Acá el usuario
pregunta *"¿cómo va?"* a los cuatro segundos y hay que tener algo que contestarle.

La buena noticia: **ya tenés la mitad**. La traza (`execution_steps`) se escribe
vuelta a vuelta y con commit inmediato, así que ya es consultable mientras la
tarea corre. Eso fue a propósito en la Fase 4 del mini 9.

La sutileza que hace que funcione, y que es la misma advertencia de aquella fase:
**los pasos de la traza no pueden vivir en la misma transacción que el turno.** Si
comparten transacción, no hay nada visible hasta que el turno termina —que es
exactamente cuando ya no te hace falta el progreso—. Son dos escrituras con
tiempos distintos: la traza commitea por vuelta, el turno commitea entero al final
(Fase 1 del mini 9, y lo que te va a salvar en la Fase 8).

Lo que falta decidir es el canal, y ya está decidido: **polling** (§5.4).

El motivo no es que sea lo más simple, es que ya existe. El `GET /tasks/{id}` de la
Fase 3 tiene que existir igual, y devolver la traza parcial es agregarle un campo.
WebSocket agrega un servicio que no sobrevive a varias réplicas de la API sin
pub/sub por Redis; webhook te obliga a tener un endpoint del lado del usuario, con
reintentos y firma. Los dos son la Fase 5 del README, no la base.

Lo que sí conviene agregar: un `Retry-After` en la respuesta mientras está
`running`, para que el cliente no te pegue cada 100 ms.

### Qué construimos

- `GET /tasks/{id}` extendido: `status`, `iteration` actual, los
  `execution_steps` hasta ahora, y `result` sólo cuando está terminada
- Commit explícito por paso de traza, en su propia sesión/transacción
- `Retry-After` en la respuesta cuando `status` es `pending` o `running`
- Opcional, y vale la pena: un campo `progress` en la tarea con un texto corto
  ("llamando a search_flights"), que es más barato de leer que la traza entera

### Cómo verificarlo

Mandá una tarea de tres vueltas y, mientras corre, pegale al `GET` cada segundo:
tenés que ver la lista de pasos crecer. Si sólo aparece todo junto al final, la
traza está compartiendo transacción con el turno.

### Deberías poder responder

- ¿Por qué la traza no puede commitear junto con el turno?
- ¿Por qué polling y no WebSocket, dado que el sistema ya usa Redis?
- ¿Qué le mostrás al usuario mientras `status` es `running`, sin filtrar el prompt
  de sistema?

### Cómo lo resuelven los frameworks

- **LangGraph — cubierto, y bien.** Tiene streaming de pasos intermedios en varios
  modos (el estado completo, sólo los cambios, los tokens del modelo, eventos
  propios) y el historial de checkpoints es consultable mientras corre. Es
  exactamente tu propiedad "la traza se lee mid-run", con más granularidad.
- **Pydantic AI** — streaming del turno y, para observabilidad, instrumentación
  OpenTelemetry (Logfire). Es más fuerte para *mirar* la corrida que para
  *consultarla programáticamente*: sirve para vos, no tanto para contestarle un
  `GET` al usuario.
- **Lo que sigue siendo tuyo** — el canal. Los dos te dan un stream **dentro del
  proceso que corre el agente**, y ese proceso es un worker de Celery que no tiene
  conexión con el cliente HTTP. Para que el stream llegue al usuario hace falta
  atravesar la frontera igual: o lo escribís en la base y el cliente hace polling
  (lo que estás haciendo), o publicás en Redis y la API lo reenvía. El framework te
  da el evento; cruzar el proceso sigue siendo tu problema.

---

## Fase 7 — Cancelación cooperativa

### Concepto aislado

No existe en ningún mini. Y no es "matar el proceso": es **dejar la conversación en
un estado válido**.

La tentación es `revoke(task_id, terminate=True)`. Manda un `SIGTERM` (o `SIGKILL`)
al worker que la está corriendo. Funciona, en el sentido de que la tarea deja de
correr. Lo que deja atrás:

- un turno a medio persistir, o peor: una tool con efectos ya ejecutada y su
  `tool_result` nunca escrito
- un `tool_use` sin su `tool_result` en el historial → **la conversación queda
  rota para siempre**, y el síntoma aparece un request después de la causa
- la fila en `running`, sin nadie vivo que la mueva

La respuesta simple y correcta: **un flag en la base que el loop chequea al
principio de cada vuelta.** Cooperativo, no forzado.

```python
for iteration in range(max_iterations):
    # El punto seguro es acá: antes de la llamada al modelo y antes de
    # ejecutar nada. No hay tool a mitad de camino ni tool_use sin resultado.
    if cancel_requested(task_id):
        transition(task_id, expected="running", new="cancelled")
        return
    ...
```

Lo que cuesta: cancelar no es instantáneo. Si el modelo está tardando cuatro
segundos en contestar, la cancelación tarda esos cuatro segundos. Es el precio de
no romper nada, y es barato.

Las tres preguntas que el `ANTES_DE_EMPEZAR` deja abiertas, respondidas:

- **¿Antes de la próxima llamada, o interrumpiendo una en curso?** Antes. Lo
  primero es fácil y suficiente; lo segundo te deja el historial roto.
- **¿Si una tool ya se ejecutó y tuvo efectos, se deshace?** No. Se **registra**.
  Deshacer requiere una operación inversa que la mayoría de las tools no tiene
  (no hay "des-enviar el mail"). La traza tiene que dejar claro qué alcanzó a
  pasar antes de cancelar.
- **¿Qué estado queda?** `cancelled`, no `failed`. Son cosas distintas: una la
  pidió el usuario, la otra salió mal. Mezclarlas te arruina cualquier métrica de
  tasa de error.

Y el caso barato que hay que cubrir igual: cancelar una tarea que todavía está
`pending`. Ahí es un CAS de `pending` a `cancelled` y la tarea nunca arranca —
cuando el worker la levanta, el chequeo de entrada de la Fase 5 la ve cancelada y
se va.

### Qué construimos

- `tasks.cancel_requested` (bool) y el estado `cancelled`, con su migración
- `POST /tasks/{id}/cancel` — idempotente: cancelar dos veces es `200`, no un error
- El chequeo al principio de cada vuelta de `run_agent`
- El CAS `pending → cancelled` para el caso de la tarea que no arrancó
- Un paso en la traza que registre la cancelación y en qué vuelta ocurrió

### Cómo verificarlo

Mandá una tarea larga, cancelala a mitad, y verificá tres cosas: que terminó en
`cancelled` y no en `failed`; que la traza muestra en qué vuelta se cortó; y —la
que importa— que **la conversación sigue usable**: mandá un turno nuevo sobre la
misma conversación y tiene que andar. Si la API te contesta *"tool_use ids were
found without tool_result blocks"*, cortaste en el lugar equivocado.

### Deberías poder responder

- ¿Por qué no `revoke(terminate=True)`?
- ¿Por qué el chequeo va al principio de la vuelta y no en cualquier lado?
- ¿Por qué `cancelled` y `failed` son estados distintos?
- ¿Qué hacés con los efectos de una tool que ya se ejecutó?

### Cómo lo resuelven los frameworks

- **LangGraph — cubierto por diseño, y con tu misma solución.** Entre nodo y nodo
  el estado está en un checkpoint consistente, así que cortar ahí nunca deja un
  `tool_use` huérfano. "Puntos seguros entre pasos" no es una feature que
  agregaron: es la consecuencia de modelar la ejecución como un grafo con estado
  persistido. Llegaste al mismo lugar poniendo el chequeo al tope del `for`.
- **Pydantic AI** — cancelás cancelando la corrida desde afuera (es código async
  normal). Lo que **no** te da es que el corte caiga en un punto seguro ni que el
  historial quede consistente: eso lo tenés que garantizar vos igual.
- **Lo que sigue siendo tuyo en los dos** — el canal de la cancelación. El flag
  vive en tu base porque quien cancela (un request HTTP) y quien obedece (un
  worker) son procesos distintos. Ningún framework te cruza esa frontera; te da el
  punto seguro, no la señal.

---

## Fase 8 — El worker que muere: heartbeat y reaper

### Concepto aislado

Un deploy, un OOM, un `SIGKILL`. La tarea estaba en la vuelta 2.

Esto es *exactamente* el problema de la pausa por aprobación del mini 9, pero
desordenado:

| | Pausa (mini 9) | Crash (P2) |
|---|---|---|
| ¿Se persistió el turno parcial? | Sí, a propósito | Depende de dónde murió |
| ¿Hay un `status` que lo marque? | `pending_approval` | Ninguno: quedó en `running` |
| ¿Quién lo retoma? | Un humano con un `POST` | Nadie, salvo que lo construyas |

**Primero, la buena noticia, y es grande: la conversación no queda rota.** Porque
el turno se guarda entero en una transacción (Fase 1 del mini 9), un worker que
muere en la vuelta 2 nunca commiteó nada de ese turno. No hay `tool_use` huérfano
en `messages`. Aquella decisión, que en el mini parecía prolijidad, acá es lo que
hace que un crash sea recuperable. Quedan filas huérfanas en `execution_steps` —y
está bien, son auditoría: querés saber qué alcanzó a hacer antes de morirse—.

**El problema que sí queda: la fila en `running` para siempre.** Nadie la va a
mover, porque el único que podía está muerto. Y el chequeo de la Fase 5 hace que
una reentrega la vea `running` y se vaya, que es correcto contra la doble ejecución
pero deja la tarea colgada.

Hace falta que alguien de afuera se dé cuenta. Dos piezas:

**El heartbeat.** La tarea actualiza `heartbeat_at` en cada vuelta del loop. Es una
escritura chiquita y ya estás escribiendo la traza ahí mismo.

**El reaper.** Una tarea periódica (Celery beat) que busca tareas `running` con
`heartbeat_at` viejo —más de N minutos, con N bastante mayor que la vuelta más
lenta que esperás— y las marca `failed` con una razón explícita (`worker_lost`, no
un `failed` genérico). Su turno parcial se descarta, que es gratis porque nunca se
persistió.

Eso es **lo mínimo aceptable**. Lo bueno sería que el reaper, en vez de marcar
`failed`, re-encole la tarea para que un worker sano la retome — y eso sólo es
seguro si la Fase 5 está bien hecha, porque retomar es reejecutar. De ahí la
dependencia 5→8: **no construyas el reintento automático antes que la
idempotencia.** Empezá marcando `failed`; el re-encolado es una mejora posterior y
consciente.

### Qué construimos

- `tasks.heartbeat_at`, actualizado en cada vuelta del loop
- `app/tasks/reaper.py` — la tarea periódica, y su entrada en `beat_schedule`
- `worker_lost` como razón de fallo distinguible en `error`
- Una métrica: cuántas tareas reapeó, que es la señal de que algo anda mal en el
  cluster

### Cómo verificarlo

El experimento, literal: mandá una tarea larga y matá el worker con `SIGKILL` (no
`SIGTERM`, que le da tiempo a terminar bien) en la vuelta 2. Verificá:

1. la fila quedó en `running` con un `heartbeat_at` que deja de moverse
2. después de N minutos, el reaper la pasó a `failed` con `worker_lost`
3. **la conversación sigue usable** — mandá un turno nuevo y tiene que andar
4. la traza muestra las vueltas 1 y 2, que es lo que querías saber

El punto 3 es el que demuestra que la Fase 1 del mini 9 estaba bien hecha.

### Deberías poder responder

- ¿Por qué un crash a mitad de turno **no** rompe la conversación?
- ¿Por qué el reaper marca `failed` y no re-encola, al menos al principio?
- ¿Cómo elegís N, el umbral del heartbeat?
- ¿Por qué `worker_lost` tiene que ser distinguible de un fallo normal?

### Cómo lo resuelven los frameworks

- **LangGraph — es su punto más fuerte de todo el proyecto.** El checkpointer hace
  que el estado sea durable paso a paso: si el proceso muere en la vuelta 2,
  reinvocar el mismo `thread_id` retoma desde el último checkpoint. No hace falta
  descartar el turno parcial porque el turno parcial está guardado y es válido. Es
  la única cosa en toda esta comparación que resuelve de verdad la parte más
  difícil de P2.
- **Pydantic AI** — sólo con ejecución durable (Temporal, DBOS). Sin eso, una
  corrida muerta se perdió.
- **Lo que sigue siendo tuyo en los dos** — **detectar que murió.** Ni el
  checkpointer ni Temporal te avisan que nadie está trabajando en esa tarea; el
  estado está a salvo, pero la fila sigue en `running` y alguien tiene que
  notarlo. El heartbeat y el reaper se escriben igual. Lo que cambia es qué hacés
  al detectarlo: con checkpointer, retomás; sin él, descartás.
- **El trade, en una línea** — LangGraph te regala la recuperación y te cobra la
  tercera fuente de verdad de la Fase 3. Vale conocer las dos caras antes de
  elegir.

---

## Fase 9 — Aprobación sin nadie mirando

### Concepto aislado

El mini 9 resolvió la pausa y el retomar. Acá se rompen los dos, por el mismo
motivo: **no hay a quién devolverle un `202`.**

En el mini 9 la secuencia era: el request encuentra una tool sensible, persiste lo
pendiente, devuelve `202` y el usuario —que estaba mirando la respuesta— sabe que
tiene que aprobar. Acá el usuario se fue hace ocho segundos con un `task_id` en la
mano. **El estado de la tarea es la única forma de enterarse.**

Y un agente que corre desatendido en un worker es justamente el caso donde la
aprobación más importa, porque nadie está mirando. Decidiste que **se espera**
(§5.2).

La pieza estructural, que es la idea más importante de la fase: **una pausa es el
final de una tarea, no una tarea que espera.**

```
tarea 1:  pending → running → pending_approval   [la tarea de Celery TERMINA acá]
          ...el usuario aprueba cuando quiera...
tarea 2:  pending → running → success            [una tarea NUEVA, que retoma]
```

El worker no se queda bloqueado esperando. Si lo hiciera, regalarías un worker por
cada aprobación pendiente, y con concurrencia 4 alcanzan cuatro aprobaciones
olvidadas para que el sistema entero se frene. La tarea de Celery **retorna**, la
fila queda en `pending_approval`, y el `POST` de aprobación **encola una tarea
nueva** que reconstruye la corrida desde la base.

Eso es, palabra por palabra, la Fase 6 del mini 9 —"retomar es reconstruir, no
continuar"— con otro disparador. Si esa fase te salió limpia, ésta es
principalmente plomería.

Lo que sí es nuevo:

- **La expiración deja de ser opcional.** En el mini 9 un pendiente sin resolver
  molestaba. Acá, sin nadie mirando, se acumulan: el reaper de la Fase 8 se hace
  cargo también de los `pending_approval` vencidos y los pasa a `failed` con
  `approval_expired`.
- **Cómo se entera el usuario.** Polling, igual que el progreso (§5.4): el
  `GET /tasks/{id}` devuelve `pending_approval` y qué tool está esperando. Mismo
  canal, campo nuevo.
- **La idempotencia de la aprobación, ahora en serio.** Dos `POST` con el mismo
  `tool_use_id` no pueden encolar dos tareas. El CAS de la Fase 3 sobre el estado
  del pendiente es el candado, y el `tool_use_id` como PK de la Fase 5 es lo que lo
  hace estable.

### Qué construimos

- El estado `pending_approval` en la máquina de la Fase 1, y sus transiciones
- `app/tasks/agent_tasks.py` — la rama que persiste lo pendiente y **retorna**
- `POST /tasks/{id}/approvals/{tool_use_id}` — decide y encola la tarea de retoma
- `app/tasks/agent_tasks.py::resume_agent_task(task_id, tool_use_id, approved)`
- El `tool_result` con `is_error` para el rechazo (del mini 9, sin cambios: no se
  borra el `tool_use`, se le contesta que no)
- El reaper extendido a los pendientes vencidos

### Cómo verificarlo

La secuencia completa, con el `GET` como único canal: mandás una tarea que use una
tool sensible → el `GET` dice `pending_approval` → aprobás → el `GET` termina en
`success` con la tool ejecutada. Después la que importa: **rechazás**, y el modelo
tiene que contestar algo coherente en vez de explotar.

Y la prueba de que la estructura es correcta: con el worker en concurrencia 1,
dejá una aprobación pendiente sin resolver y mandá **otra** tarea. Tiene que
correr normalmente. Si se queda en `pending`, tu tarea está bloqueando el worker y
la pausa está mal implementada.

### Deberías poder responder

- ¿Por qué la tarea de Celery termina en vez de esperar la aprobación?
- ¿Qué se rompe si al rechazar borrás el `tool_use` del historial?
- ¿Por qué la expiración es obligatoria acá y era opcional en el mini 9?
- ¿Cómo evitás que dos `POST` de aprobación encolen dos tareas de retoma?

### Cómo lo resuelven los frameworks

- **LangGraph — cubierto, y es la feature que más se le parece a lo tuyo.** Su
  `interrupt()` frena el grafo en un nodo, persiste el estado en el checkpoint, y
  la ejecución se retoma después mandando el valor que faltaba. Es literalmente
  "pausar es persistir y salir; retomar es reconstruir". La diferencia es que
  ellos lo tienen como primitiva y vos lo tenés como dos fases del mini 9.
- **Pydantic AI — también, y con un modelo explícito.** Tiene tools que requieren
  aprobación: la corrida termina devolviendo las llamadas diferidas, y la retomás
  pasándole los resultados de las decisiones. Mismo patrón: la corrida **termina**,
  no espera. Que los dos frameworks hayan llegado a la misma forma que vos es la
  mejor señal de que la forma es correcta.
- **Lo que sigue siendo tuyo** — tres cosas, y no son chicas: **quién decide** qué
  tool es sensible (es una propiedad del negocio, no del código, y ningún framework
  puede decidirla); **la expiración** de un pendiente que nadie resuelve; y **el
  canal** por el que el usuario se entera, que otra vez cruza la frontera del
  proceso y otra vez es tu `GET`.

---

## Fase 10 — Presupuesto por usuario, no por sesión

### Concepto aislado

El `budget.py` del mini 9 acota **una sesión**. Decidiste que el presupuesto de
este proyecto es **por usuario** (§5.5), y eso lo cambia de lugar: deja de ser una
columna de la conversación y pasa a ser una cuenta que cruza conversaciones,
tareas y workers.

Por qué importa más acá que en el mini 9: un loop mal guiado corriendo desatendido
en un worker, que además **reintenta**, es la factura sorpresa clásica. En el mini
9 había un humano esperando la respuesta que se habría dado cuenta.

Tres problemas nuevos, todos de concurrencia.

**1. Dos workers chequean a la vez.** Los dos leen "gastó 9.000 de 10.000", los dos
concluyen que entran, los dos llaman al modelo. El chequeo y el descuento tienen
que ser una sola operación atómica en la base, no un `SELECT` seguido de un
`UPDATE`.

**2. El gasto se conoce después.** `count_tokens` estima el input; el output se
sabe recién con el `usage` de la respuesta. El patrón que resuelve las dos cosas es
**reservar y liquidar**: antes de llamar, reservás el estimado en un `UPDATE`
atómico con condición; después de la respuesta, ajustás con el consumo real. Si el
`UPDATE` de reserva afecta cero filas, no hay presupuesto y no llamaste. Es el
mismo compare-and-swap de la Fase 3, aplicado a números en vez de a estados.

**3. Una tarea que muere deja reservado lo que no gastó.** Si el worker se muere
entre reservar y liquidar, esos tokens quedan contados y nadie los devuelve. El
reaper de la Fase 8 tiene que liberar las reservas de las tareas que mató; si no,
el presupuesto de un usuario se va degradando solo con cada crash.

Y la ventana: "por usuario" a secas no alcanza, porque un presupuesto sin ventana
se agota una vez y ya. Por usuario **y por período** —hora o día— es lo que
funciona, y hace falta decidir si la ventana es fija (se resetea a las 00:00) o
deslizante (los últimos 60 minutos). La fija es mucho más barata de consultar y
casi siempre alcanza.

### Qué construimos

- `app/models.py` — `UserBudget`: `user_id`, `window_start`, `tokens_reserved`,
  `tokens_used`, `limit`, con `UniqueConstraint(user_id, window_start)`
- `app/budget.py` — pasa de sesión a usuario: `reserve(user_id, estimado)`
  atómico, `settle(user_id, usage)`, `release(user_id, reserva)`
- El chequeo **antes** de cada llamada al modelo, no una vez por tarea (un loop de
  cinco vueltas son cinco decisiones de gasto)
- `BudgetExceededError` → la tarea termina `failed` sin reintento (Fase 4)
- El reaper libera reservas huérfanas
- `GET /users/{id}/budget` — cuánto queda, para poder mirarlo

### Cómo verificarlo

Poné un límite ridículo y mandá **dos tareas en paralelo** que juntas lo excedan.
Exactamente una tiene que fallar por presupuesto. Si pasan las dos, el chequeo no
es atómico y tenés una condición de carrera.

Después: matá el worker entre la reserva y la respuesta, y verificá que el reaper
devuelve los tokens. Sin eso, cada crash le come presupuesto a un usuario que no
gastó nada.

### Deberías poder responder

- ¿Por qué el chequeo y el descuento tienen que ser una sola operación?
- ¿Por qué se reserva el estimado y después se liquida, en vez de descontar al final?
- ¿Qué pasa con la reserva de una tarea que muere?
- ¿Por qué el presupuesto se chequea por vuelta y no una vez por tarea?

### Cómo lo resuelven los frameworks

- **Pydantic AI — parcialmente.** Tiene límites de uso por corrida: cantidad de
  requests al modelo y de tokens, chequeados durante el loop. Cubre el "este agente
  no se desboca". Lo que **no** cubre es tu caso: el límite es **por corrida**, en
  memoria del proceso. No cruza tareas, ni conversaciones, ni workers, ni
  reintentos.
- **LangGraph** — no tiene un concepto de presupuesto. Lo escribís en un nodo.
- **Lo que sigue siendo tuyo** — todo lo que hace difícil esta fase: la cuenta
  compartida en la base, la atomicidad entre procesos, reservar-y-liquidar, y las
  reservas huérfanas. "Por usuario" convierte un contador local en un recurso
  compartido con concurrencia, y eso es un problema de base de datos, no de
  agentes. Ningún framework de agentes lo va a resolver, porque no es su problema.

---

## Fase 11 — Verificación manual + CHECK_LEARNING

### Concepto aislado

Este proyecto **no tiene suite automática**, y la razón no es ahorrar trabajo.

Un test automático contesta *"¿funciona?"*. Un `assert` verde te dice que el
invariante se cumple; no te enseña qué lo rompe, ni cómo se ve cuando se rompe,
ni por qué el diseño quedó así. Eso se aprende mirando el sistema funcionar y,
sobre todo, rompiéndolo a propósito.

Las pruebas viven en `PRUEBAS.md`, una sección por fase, **tres como máximo**, y
cada una con la misma forma:

    Correr    el comando
    Observar  qué tenés que ver, y dónde mirar
    Por qué   qué mecanismo lo produce
    Rompelo   el experimento que hace visible el mecanismo

La fila **Rompelo** es la que importa. Un documento con sólo comandos que andan
es QA, no aprendizaje.

Esta fase no agrega pruebas nuevas: **es la pasada completa**. Correr las de las
once fases seguidas, sobre un sistema que ya tiene todas las piezas, y ver cuáles
se rompieron en el camino. Varias van a fallar, y eso es información: una prueba
de la Fase 2 que deja de pasar después de la Fase 8 es una regresión que ninguna
fase individual podía detectar.

---

**Lo que este proyecto perdió al no tener suite, dicho de frente.** No es gratis:

- No hay red contra regresiones. La pasada completa de esta fase es manual y se
  hace una vez; una suite corre en cada cambio.
- No hay CI que falle. Cualquier cosa que se rompa se descubre corriéndolo.
- Los casos de carrera —dos tareas contra el mismo presupuesto, dos aprobaciones
  simultáneas— son incómodos de reproducir a mano y fáciles de escribir como test.

La decisión fue explícita: el objetivo acá es entender, no sostener. En un
proyecto que tuviera que durar, la suite no es opcional — y si algún día querés
escribirla, la lista de abajo es exactamente su índice.

### Qué construimos

- Una pasada completa de `PRUEBAS.md`, de la Fase 0 a la 10, anotando qué se
  rompió
- `CHECK_LEARNING.md` con las preguntas de cada fase, reunidas

### Las doce afirmaciones que el sistema tiene que sostener

Es la lista que hay que poder demostrar a mano al terminar — y, si algún día
aparece una suite, su índice:

- Llamar dos veces a la tarea ejecuta la tool con efectos **una sola vez** (F5)
- Una tarea que arranca y encuentra su fila en `running` no la reprocesa (F5)
- Un `BudgetExceededError` no reintenta; un `APIConnectionError` sí (F4)
- El flag de cancelación corta al principio de la vuelta y deja el historial válido (F7)
- Una tarea `running` con heartbeat viejo termina en `failed`/`worker_lost` (F8)
- Un crash a mitad de turno **no** deja `tool_use` huérfanos en `messages` (F8)
- Una tarea en `pending_approval` no bloquea al worker (F9)
- Dos `POST` de aprobación encolan una sola tarea de retoma (F9)
- Dos tareas en paralelo contra el mismo presupuesto: sólo una pasa (F10)
- `GET /tasks/{id}` de un id inventado da `404`, no "pending" (F3)
- El historial nunca tiene un `tool_use` sin su `tool_result` (F0, la consulta SQL)
- El payload que cruza el broker no lleva datos de usuario (F2)

### Deberías poder responder

- ¿Qué de este proyecto sólo se puede verificar rompiéndolo a mano?
- ¿Cuáles de las doce afirmaciones son incómodas de probar manualmente, y por qué?
- Si escribieras la suite, ¿cuál sería el primer test y por qué ése?

### Cómo lo resuelven los frameworks

- **Pydantic AI** tiene modelos de prueba: uno que contesta cualquier cosa sin
  llamar a la API y otro que te deja guionar la secuencia de respuestas. Es tu
  `fake_model` del mini 8, mantenido por otro — pero **sólo funciona adentro de
  un `Agent` suyo**, así que no se puede importar para probar tu loop.
- **Lo que sigue siendo tuyo** — las doce afirmaciones de arriba. Son de Celery,
  de tu base y de tu máquina de estados. El framework te ahorra el mock del
  modelo, que es el pedazo más fácil.

---

## Correcciones al README del proyecto

**Ya están aplicadas**: el README se reescribió con todo esto corregido. La tabla
queda como registro de qué decía el original y por qué estaba mal — es el mismo
ejercicio que el §6 del `ANTES_DE_EMPEZAR`, y leer las dos juntas muestra cuánto
de un plan escrito antes de empezar no sobrevive al contacto con el código.

| README dice | Correcto | Fase |
|---|---|---|
| `Database Tables: 1 (tasks)` | Seis como mínimo: `conversations`, `tasks`, `messages`, `execution_steps`, `tool_executions`, `user_budgets` | 1, 5, 10 |
| `SQLAlchemy 2.0+ - Async ORM` | **Sincrónico**, por la decisión §5.1 | 0 |
| No menciona Alembic | Es obligatorio: el esquema cambia en seis de las catorce fases | 0 |
| El ejemplo de retry captura `TemporaryError`/`PermanentError` sin definirlas | La clasificación **es** el contenido de la fase, no un detalle | 4 |
| `GET /monitoring/active` como estado de las tareas | Eso es salud del transporte. El estado de negocio sale de tu tabla | 3 |
| `redis-cli FLUSHDB` como solución a tareas trabadas | Funciona, y te borra el result backend entero — otro motivo para no depender de él | 3 |
| Task lifecycle sin `cancelled` ni `pending_approval` | Son dos de los cinco estados | 7, 9 |
| Terraform, Railway, CI, Flower | **Fuera de alcance.** Ver la nota de cierre | — |
| `Timeline: 12-15h` | Con idempotencia, cancelación y recuperación, 18-22 h es honesto | — |

---

## Lo que queda fuera de alcance, y por qué

Este proyecto termina en la Fase 11: un sistema que corre en tu máquina, que
entendés, y que sabés romper. **No se despliega.**

Quedan afuera a propósito:

| Fuera | Por qué |
|---|---|
| Terraform, Railway, AWS | Es infraestructura, no agentes. Nada de eso te enseña algo sobre el problema de este proyecto |
| CI (GitHub Actions) | Sin suite automática no hay nada que correr en CI |
| Flower y los endpoints de `/monitoring` | Salud del transporte. Lo interesante —que el estado de negocio sale de tu tabla y no de Celery— ya está en la Fase 3 |
| Dockerfile de la app | El `docker-compose.yml` levanta Postgres y Redis, que es lo que hace falta para correrlo. Empaquetar la app es un paso de deploy |

Lo que **sí** está adentro y podría parecer de despliegue: el
`worker_process_init` de la Fase 2 (sin eso el worker no anda) y el `/health`
(porque enseña qué NO debe chequear un liveness).

El costo de esta decisión es real y conviene tenerlo escrito: **este proyecto no
demuestra que sabés deployar**. Si va al portfolio, lo que demuestra es que
entendés idempotencia, cancelación cooperativa y recuperación de fallos — que es
bastante más difícil de aprender que un `terraform apply`, y bastante menos
común de encontrar.
