# ✅ CHECK_LEARNING — PROJECT 2

Las preguntas de las once fases, juntas. Si podés contestarlas sin abrir el
código, el proyecto cumplió su objetivo.

**Cómo usarlo.** No es un examen con respuestas al final. Cada pregunta tiene al
lado la fase y, cuando existe, el experimento de `PRUEBAS.md` que la contesta.
Si dudás en una, la forma de resolverla no es leer el archivo — es correr el
"Rompelo" de esa fase y mirar qué pasa.

**La pregunta que las resume todas**, y la única que vale en una entrevista:

> Escribiste un agente que corre en un request. Ahora tiene que correr en un
> worker. ¿Qué deja de ser gratis?

---

## El hilo conductor

Todo este proyecto es una sola consecuencia: **el loop corre en otro proceso, al
que no le podés devolver nada y que se puede morir en cualquier momento.**

| En un request | En un worker |
|---|---|
| La excepción se vuelve un código HTTP | No hay a quién contarle |
| El 202 vuelve a quien preguntó | Nadie está esperando |
| Correr una vez significa correr una vez | El broker **va a** entregar dos veces |
| El proceso vive hasta contestar | Se puede morir a mitad de turno |
| El progreso es "esperá la respuesta" | Alguien pregunta a los 4 segundos |
| Un humano mira el pedido de permiso | Nadie está mirando |

Si podés reconstruir esa tabla de memoria y decir qué fase resuelve cada fila,
sabés de qué se trata el proyecto.

---

## Fase 0 — el port a sincrónico

- ¿Por qué un handler de FastAPI que hace consultas sincrónicas no debe ser
  `async def`? ¿Qué falla, y cómo se nota?
- ¿Qué problema traía `asyncio.run()` adentro de una tarea de Celery?
- ¿Por qué el primer commit es un port sin funcionalidad nueva?
- ¿Por qué el error de `tool_use` huérfano aparece un request **después** de la
  causa? *(PRUEBAS 0.1)*
- ¿Por qué el `input_tokens` crece turno a turno y el `output_tokens` no?
- ¿Por qué el schema de `get_my_orders` está vacío, y qué pasó cuando lo llenaste?
  *(PRUEBAS 0.2)*
- ¿Por qué retomar es reconstruir y no continuar?
- ¿Qué es el candado que impide ejecutar dos veces una aprobación?

## Fase 1 — conversaciones y tareas

- ¿Por qué el historial cuelga de la conversación y la traza de la tarea?
- ¿Qué se rompe si modelás "una tarea es una conversación"?
- ¿Por qué escribir la máquina de estados antes de tener un worker?
- ¿Por qué la fila se crea y se commitea **antes** de llamar al agente?
- ¿Qué mide `started_at - created_at`, y por qué en esta fase daba casi cero?
- ¿Por qué el error se escribe en la tarea si el cliente ya recibió un 402?
- ¿Por qué `success` no puede volver a `running`?

## Fase 2 — Celery en el medio

- ¿Por qué se encola el `task_id` y no el objeto `Task`?
- ¿De dónde saca el worker el `user_id`, y por qué no del mensaje?
- ¿Qué pasa si el engine se creó antes del `fork`? ¿Por qué el error no lo
  menciona? *(PRUEBAS 2.3)*
- ¿Qué de tu payload sería un problema si alguien lee tu Redis?
- ¿Por qué el `POST` devuelve 202 y no 201?
- ¿Por qué el `commit` va antes del `.delay()`?
- Encolaste con el worker apagado: ¿qué revela eso sobre el estado `pending`?

## Fase 3 — una sola fuente de verdad

- ¿Por qué `AsyncResult` de un id inventado devuelve `PENDING` y no un error?
  *(PRUEBAS 3.1)*
- ¿Por qué la condición va adentro del `UPDATE` y no en un `if` antes?
- ¿Qué significa que un CAS afecte cero filas? ¿Por qué no siempre es un error?
- ¿Qué se pierde con `FLUSHDB` en la base 1 y qué en la base 0?
- ¿Sobre qué **no** es autoridad tu tabla?

## Fase 4 — reintentos

- ¿Por qué un `BudgetExceededError` no se reintenta?
- ¿Por qué la lista de reintentables es una allowlist y no una blocklist?
- ¿Por qué `RateLimitError` no usa tu backoff sino el header de la respuesta?
- ¿Por qué el backoff lleva jitter? ¿Qué pasa con cinco tareas que fallan juntas
  sin él? *(PRUEBAS 4.2)*
- ¿Por qué la fila sigue en `running` mientras reintenta?
- ¿Por qué el candado sólo se chequea cuando `retries == 0`?
- ¿Qué distingue una entrada de DLQ con `retries=0` de una con `retries=3`?
- ¿Por qué el replay reencola pero no resetea el estado?

## Fase 5 — idempotencia

- ¿Por qué `acks_late=True` **crea** este problema, y por qué lo querés igual?
- ¿Qué cubre el candado de la fila y qué caso deja afuera?
- ¿Por qué la clave es el `tool_use_id` y no un `uuid4()`?
- ¿Por qué se guarda el resultado y no sólo el hecho de haber ejecutado?
- ¿Por qué `cancel_order` no puede quedar en `in_flight` y `send_email` sí?
- ¿Qué tools **no** necesitan pasar por el candado?

## Fase 6 — progreso

- ¿Por qué `record_step` commitea en el acto en vez de esperar al turno?
- ¿Qué se commiteaba de más cuando la traza compartía sesión con el loop?
- ¿Por qué `iteration` se deriva de los pasos y no se guarda en la fila?
- ¿Por qué la traza de progreso muestra menos campos que la de auditoría?
- ¿Por qué polling y no WebSocket, si el sistema ya usa Redis?
- ¿Qué le dice al cliente que el `Retry-After` desaparezca?

## Fase 7 — cancelación cooperativa

- ¿Por qué no `revoke(terminate=True)`? ¿Qué deja atrás?
- ¿Por qué el chequeo va al principio de la vuelta y no en cualquier lado?
- ¿Por qué cancelar una tarea `pending` no usa el flag?
- ¿Por qué cancelar dos veces da 200 y aprobar dos veces da 409?
- ¿Por qué `cancelled` y `failed` son estados distintos?
- ¿Qué pasa con una tool con efectos que ya se ejecutó?
- ¿De qué nivel de aislamiento depende que el flag llegue al loop?

## Fase 8 — el worker que muere

- ¿Por qué un crash a mitad de turno **no** deja `tool_use` huérfanos?
- ¿Por qué los pasos de la traza sobreviven y los mensajes no?
- El broker reentrega solo: ¿qué queda sin hacer, y por qué?
- ¿Por qué el worker que recibe la reentrega se va sin tocar nada?
- ¿Cómo elegís el umbral del heartbeat?
- ¿Por qué `worker_lost` tiene que ser distinguible de un fallo normal?
- ¿Qué pasa si `beat` no corre, y por qué cuesta notarlo?

## Fase 9 — aprobación sin nadie mirando

- ¿Por qué la tarea de Celery termina en vez de esperar la aprobación?
- ¿Qué pasaría con concurrencia 4 y cuatro aprobaciones olvidadas?
- ¿Por qué es la misma `Task` y no una nueva?
- ¿Por qué se decide **antes** de encolar la retoma?
- ¿Qué se rompe si al rechazar borrás el `tool_use` del historial?
- ¿Por qué una aprobación vencida deja la tarea en `failed` y no en `cancelled`?
- ¿Por qué la expiración es obligatoria acá y era opcional en el mini 9?

## Fase 10 — presupuesto por usuario

- ¿Por qué el presupuesto de la conversación se podía leer-y-escribir y éste no?
- ¿Qué hace el `WHERE` adentro del `ON CONFLICT DO UPDATE`?
- ¿Por qué se reserva el estimado y se liquida con el real?
- ¿Por qué el `except` es `BaseException` y no `Exception`?
- ¿Cómo detecta el reaper una reserva huérfana sin llevar registro por tarea?
- ¿Por qué la ruta dice `me` y no `{user_id}`?
- ¿Por qué conviven los dos presupuestos en vez de reemplazarse?

---

## Las transversales

Éstas no son de ninguna fase en particular: son las que atraviesan el proyecto.

**Sobre el diseño**

- Hay **tres** invariantes que se defienden con estructura y no con cuidado.
  ¿Cuáles son y qué lo garantiza en cada caso?
- El loop no sabe que existe una tabla `tasks`. ¿Cómo hacen entonces la
  cancelación y el heartbeat? ¿Qué se gana con eso?
- ¿Qué tres cosas commitean en su propia sesión, y por qué cada una?
- El mismo compare-and-swap aparece en cuatro lugares distintos. ¿Cuáles?

**Sobre lo que no se resolvió**

- ¿Qué garantiza el candado de idempotencia para una tool cuyo efecto sale de tu
  base, y qué **no** garantiza? ¿Cómo se cierra esa ventana de verdad?
- `/messages` y `/tasks` son dos puertas al mismo agente y sólo una crea filas.
  ¿Qué problemas trae y cómo lo unificarías?
- ¿Qué pasa con una tarea si `beat` nunca corrió?

**Sobre las herramientas**

- Alembic no detecta renombres. ¿Qué generó cuando `sessions` pasó a
  `conversations`, y qué había que escribir a mano?
- ¿Por qué `compare_type=True` en `env.py` y qué se rompía sin él?
- ¿Qué **no** se puede verificar con `task_always_eager`?

**Sobre el alcance**

- Este proyecto no se deploya. ¿Qué demuestra entonces, y cómo lo dirías en una
  entrevista?
- No tiene suite automática. ¿Qué se perdió con esa decisión y cuál sería el
  primer test si la escribieras?

---

## Si tuvieras que empezar de nuevo

- ¿Qué haría Temporal por vos que Celery no hace? ¿Qué te costaría?
- LangGraph resuelve las fases 6, 7 y 8 con un checkpointer. ¿Por qué no lo
  usaste, y qué te habría cobrado a cambio?
- Pydantic AI reemplaza siete piezas de tu capa `app/agent/`. ¿Cuáles son las
  cinco que **no** reemplaza?
- Con todo lo que sabés ahora: ¿cuál de las once fases fue la más difícil, y por
  qué esa?
