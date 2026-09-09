# 🗺️ Mini 7 — Plan por fases

Cada fase es **autocontenida**: explica su concepto desde cero, se construye
sola, se verifica sola y se puede entender sin haber leído las otras. La única
dependencia real es la Fase 0 (el esqueleto donde vive todo lo demás).

Orden sugerido, pero podés saltar: la Fase 4 (progreso) no necesita nada de las
Fases 1-3, y la Fase 5 (introspección) no necesita ninguna tarea en particular.

| Fase | Tema | Depende de |
|------|------|-----------|
| 0 | Esqueleto del proyecto | — |
| 1 | Retry declarativo: backoff + jitter | 0 |
| 2 | Errores retryables vs permanentes | 0 |
| 3 | Dead Letter Queue | 0 (se entiende mejor con 2) |
| 4 | Progress tracking | 0 |
| 5 | Introspección del cluster (`inspect`) | 0 |
| 6 | Endpoints de monitoreo | 0, 5 |
| 7 | Cancelar tareas (`revoke`) | 0 |
| 8 | Tests + CHECK_LEARNING | todas |

---

## Fase 0 — Esqueleto del proyecto

### Concepto aislado

Una app con tareas en background son **dos procesos separados que no comparten
memoria**: la API (FastAPI) que encola, y el worker (Celery) que ejecuta. Entre
los dos hay un Redis haciendo de **broker** (la cola de entrada) y de **backend**
(el almacén de resultados). Lo único que viaja entre procesos es un mensaje JSON.

Todo el mini 7 pasa dentro de ese triángulo. Esta fase lo levanta y nada más.

### Qué construimos

- `pyproject.toml` con las deps (`celery[redis]`, `fastapi`, `pydantic-settings`, `uvicorn`)
- `app/config.py` — settings desde env vars
- `app/celery_app.py` — instancia de Celery y su configuración
- `app/main.py` — FastAPI con `/health`
- `docker-compose.yml` + `Dockerfile` + `.env.example`

Es en gran parte el esqueleto del mini 6, pero **escrito de nuevo, no copiado**:
el objetivo es que puedas justificar cada flag de la config sin mirar atrás.

### Cómo verificarlo

```bash
docker compose up -d
curl localhost:8000/health
```
El worker arranca y en su log aparece el banner con la lista de tareas
registradas (por ahora, vacía).

### Deberías poder responder

- ¿Por qué `broker` y `backend` apuntan a DBs distintas de Redis?
- ¿Qué hace `task_acks_late=True` y qué exige a cambio de la tarea?
- ¿Por qué `worker_prefetch_multiplier=1` cuando las tareas duran distinto?

---

## Fase 1 — Retry declarativo: backoff + jitter

### Concepto aislado

Un reintento sirve para **fallos transitorios**: un 503, un timeout de red, un
deadlock de la DB. La pregunta no es "¿reintento?" sino "¿cuándo?".

- **Inmediato**: martilla al servicio que ya está caído. Peor el remedio.
- **Fijo (cada 5s)**: mejor, pero no le da tiempo a recuperarse a un incidente largo.
- **Exponencial** (1s, 2s, 4s, 8s...): le da al sistema una ventana creciente.
- **Exponencial + jitter**: el exponencial puro tiene un problema. Si 500 tareas
  fallan en el mismo segundo (porque el servicio se cayó), las 500 reintentan
  exactamente al segundo 1, y otra vez al 2, y al 4. Eso se llama **thundering
  herd**: convertís un pico en varios picos sincronizados. El **jitter**
  aleatoriza el delay dentro del intervalo y desparrama la carga.

En el mini 6 esto se escribió a mano con `raise self.retry(countdown=2 ** retries)`.
Celery ya lo trae hecho, y bien: acá aprendés la versión declarativa.

### Qué construimos

`app/tasks.py` — una tarea que falla las primeras N veces:

```python
@celery_app.task(
    bind=True,
    autoretry_for=(TransientError,),   # qué excepciones disparan el retry
    retry_backoff=True,                # 1s, 2s, 4s, 8s...
    retry_backoff_max=60,              # techo del delay
    retry_jitter=True,                 # aleatoriza dentro del intervalo
    max_retries=3,                     # 3 reintentos = 4 ejecuciones
)
```

### Cómo verificarlo

Encolás la tarea, mirás el log del worker y verificás que **los delays entre
intentos crecen y no son exactamente 1/2/4** (eso es el jitter haciendo su
trabajo). Consultás el estado y lo ves en `RETRY`.

### Trampas a entender

- `max_retries=3` son **3 reintentos**, 4 ejecuciones en total.
- Si ponés `autoretry_for` **sin** `retry_backoff`, Celery usa
  `default_retry_delay` = **180 segundos**. Podés pensar que no reintenta cuando
  en realidad está esperando 3 minutos.
- Con `retry_jitter=True` el delay real es un valor aleatorio **entre 0 y el
  backoff calculado** (full jitter), no "el backoff ± un poquito".
- El `task_id` **no cambia** entre reintentos: es el mismo mensaje reencolado.

### Deberías poder responder

- ¿Qué es el thundering herd y cómo lo evita el jitter?
- ¿Cuántas veces se ejecuta una tarea con `max_retries=3`?
- ¿Cuál es la diferencia entre `self.retry()` manual y `autoretry_for`?

---

## Fase 2 — Errores retryables vs permanentes

### Concepto aislado

Reintentar no siempre tiene sentido. Hay dos familias de fallo:

| | Transitorio | Permanente |
|---|---|---|
| Ejemplos | 503, timeout, connection reset, 429 rate limit | 400 payload inválido, 404 recurso inexistente, 401 credencial mala |
| ¿Se arregla solo? | Sí, esperando | No, nunca |
| Acción | Reintentar con backoff | Fallar rápido y registrar |

Reintentar un error permanente 5 veces es **gastar 5 slots del worker para llegar
al mismo resultado**, más tarde y con la cola más llena. Y al revés: fallar
inmediatamente ante un 503 es perder una tarea que iba a funcionar sola.

La forma de expresar esto en código no es un `if` sobre el mensaje del error —
es una **taxonomía de excepciones de dominio**. El tipo de la excepción es el
que decide la política.

### Qué construimos

- `app/exceptions.py`:
  ```python
  class TaskError(Exception): ...
  class TransientError(TaskError): ...   # reintentable
  class PermanentError(TaskError): ...   # no reintentable
  ```
- Una tarea que traduce fallos externos a esta taxonomía y deja que
  `autoretry_for=(TransientError,)` haga el resto: `PermanentError` no está en
  la tupla, así que **muere en el primer intento**, como corresponde.

### Cómo verificarlo

La misma tarea con dos payloads distintos: uno termina en `FAILURE` a los 4
intentos (transitorio agotado), el otro en `FAILURE` **inmediato** (permanente).

### Trampas a entender

- `autoretry_for` matchea por herencia. Si `PermanentError` heredara de
  `TransientError`, se reintentaría igual.
- `Ignore` (excepción de Celery): corta la tarea sin marcarla como fallida ni
  tocar el estado. Útil cuando la tarea ya no aplica (el recurso se borró).

### Deberías poder responder

- Un LLM te devuelve 429 y otro 400. ¿Cuál reintentás y por qué?
- ¿Por qué la política de retry se modela con tipos de excepción y no con `if`?

---

## Fase 3 — Dead Letter Queue

### Concepto aislado

Una tarea agotó sus 3 reintentos. Queda en `FAILURE` en el backend... y expira
en 1 hora por `result_expires`. **Se perdió.** Nadie se enteró, nadie la puede
reprocesar, y el usuario que pidió esa operación nunca supo que no pasó.

Una **Dead Letter Queue** es el destino final de lo que no se pudo procesar: un
lugar durable donde queda el mensaje original + el error, para poder alertar,
auditar o reencolar a mano después de arreglar la causa.

En RabbitMQ es nativo (`x-dead-letter-exchange`). Con Redis como broker **no
existe**: hay que construirla. Y el gancho para hacerlo es el hook `on_failure`
de la Task, que Celery llama **una sola vez, cuando el fallo ya es definitivo**
(no en cada reintento; para eso está `on_retry`).

### Qué construimos

- Una `Task` base con `on_failure` sobreescrito, que empuja a una lista de Redis:
  ```python
  class DeadLetterTask(celery_app.Task):
      def on_failure(self, exc, task_id, args, kwargs, einfo):
          # task_id, nombre, args, tipo de excepción, mensaje, timestamp
  ```
- Las tareas la usan con `@celery_app.task(base=DeadLetterTask, ...)`
- `app/services/dead_letter.py` — escribir y leer la DLQ

### Cómo verificarlo

Encolás una tarea condenada a fallar, esperás a que agote los reintentos y
después leés la lista de Redis: ahí está la entrada, **una sola**, con el error.

### Trampas a entender

- `on_failure` corre **en el worker**, dentro del mismo proceso. Si tira una
  excepción, se la come Celery — no puede hacer algo caro ni frágil ahí.
- No confundir con `Reject`: en RabbitMQ manda el mensaje al DLX del broker; con
  Redis no hay tal cosa.
- Una DLQ sin nadie que la mire es un archivo de log caro. La fase siguiente
  natural en producción sería alertar (`send_error_alert.delay(...)`).

### Deberías poder responder

- ¿Cuántas veces se llama `on_failure` en una tarea con 3 reintentos que falla siempre?
- ¿Por qué el backend de resultados no sirve como DLQ?

---

## Fase 4 — Progress tracking

### Concepto aislado

Una tarea de 4 minutos es una caja negra: el cliente ve `STARTED` desde el
segundo 1 hasta el final. No puede distinguir "va por la mitad" de "se colgó".

Celery permite que la tarea **se reporte a sí misma** mientras corre:
`self.update_state(state="PROGRESS", meta={"current": i, "total": n})` escribe
en el backend un estado **custom** con metadata arbitraria. El cliente lo lee
con `AsyncResult(task_id).info`.

Lo interesante: `PROGRESS` no es un estado de Celery, te lo inventás vos. Celery
solo distingue estados **ready** (SUCCESS, FAILURE, REVOKED) de los que no lo
son — cualquier otro nombre es válido y `ready()` devolverá `False`.

### Qué construimos

- Una tarea larga que reporta progreso en cada paso
- `GET /tasks/{id}/progress` que traduce el estado interno a algo útil para el
  cliente: `{"state": "PROGRESS", "percent": 40, "current": 4, "total": 10}`

### Cómo verificarlo

Encolás, y hacés polling al endpoint mientras corre: el porcentaje sube.

### Trampas a entender

- El `meta` viaja a Redis serializado en JSON: nada de objetos raros adentro.
- Cada `update_state` es **un write a Redis**. Reportar cada iteración de un
  loop de 100.000 vueltas convierte el backend en el cuello de botella —
  se reporta cada N pasos o cada X %.
- Con `task_ignore_result=True` no hay dónde escribir: el progreso desaparece.
- Ojo con el orden: si consultás y ves `PENDING`, puede ser que la tarea aún no
  arrancó **o** que el id no existe. Son indistinguibles (esto ya lo viste en el mini 6).

### Deberías poder responder

- ¿Por qué `ready()` es `False` durante `PROGRESS`?
- ¿Dónde vive físicamente el `meta` que mandás en `update_state`?

---

## Fase 5 — Introspección del cluster

### Concepto aislado

Hasta acá todo fue sobre **una** tarea. Esta fase es sobre **la flota**: ¿hay
workers vivos? ¿cuántas tareas están corriendo ahora mismo? ¿cuántas procesó
cada uno desde que arrancó?

`celery_app.control.inspect()` responde eso. Y acá está el detalle que casi
nadie explica y que define si tu endpoint de monitoreo sirve o es una bomba:

> `inspect()` **no lee una base de datos**. Publica un mensaje de broadcast en
> el broker, espera a que cada worker conteste por su cuenta, y junta las
> respuestas hasta un **timeout**.

Consecuencias directas:
- Si no hay workers vivos, devuelve `None` — **no** un dict vacío. `for k in
  inspect.active()` explota con `TypeError`.
- Sin `timeout` explícito, se queda esperando el default (1s) por cada llamada.
  Un "dashboard" que llame a `active()`, `scheduled()`, `reserved()` y `stats()`
  puede tardar 4 segundos, ocupando un hilo del threadpool de FastAPI.
- Los datos son un **snapshot del momento**, no una serie temporal.

Métodos que importan:

| Método | Qué devuelve |
|---|---|
| `ping()` | qué workers están vivos (el más barato) |
| `active()` | tareas ejecutándose **ahora** |
| `reserved()` | tareas que el worker ya tomó pero no empezó (el prefetch) |
| `scheduled()` | tareas con ETA/countdown esperando su hora — **acá viven los retries pendientes** |
| `stats()` | pool, concurrencia, totales por tarea |

### Qué construimos

`app/services/monitoring.py` — una capa fina sobre `inspect` que:
- pasa `timeout` explícito
- normaliza `None` → `{}` para que la ruta nunca reciba una sorpresa
- distingue "no hay workers" de "hay workers y están ociosos" (dos cosas muy
  distintas que `inspect` devuelve casi igual)

### Cómo verificarlo

Con el worker levantado: `ping()` lo lista. Encolás una tarea lenta y aparece en
`active()`. Encolás una que reintenta y aparece en `scheduled()` mientras espera.
**Apagás el worker** y verificás que tu servicio devuelve "sin workers" en vez de
reventar.

### Deberías poder responder

- ¿Por qué `inspect()` puede devolver `None`?
- ¿En cuál de los métodos ves una tarea que está esperando su reintento?
- ¿Cuál es la diferencia entre `active()` y `reserved()`?

---

## Fase 6 — Endpoints de monitoreo

### Concepto aislado

Exponer lo de la Fase 5 por HTTP tiene sus propias reglas, distintas de las de
un CRUD:

- **Un endpoint de monitoreo nunca debe caerse cuando el sistema está caído.**
  Es justo cuando más lo necesitás. Si no hay workers, responde 200 con
  `{"workers": [], "healthy": false}`, no un 500.
- **Degradación elegante**: si `stats()` falla pero `ping()` responde, devolvés
  lo que tenés.
- **Es caro**: son llamadas de red con timeout, no cacheables por defecto. No es
  un endpoint para pollear cada 100ms desde un frontend.

También acá entra la diferencia entre `/health` (¿está viva la API?) y un
`/health/workers` (¿hay quién ejecute?). Son preguntas distintas y un load
balancer solo debería mirar la primera.

### Qué construimos

- `app/routes/monitoring.py`:
  - `GET /monitoring/workers` — quién está vivo + stats
  - `GET /monitoring/active` — qué corre ahora
  - `GET /monitoring/dashboard` — la vista agregada
  - `GET /monitoring/dead-letter` — la DLQ de la Fase 3
- Schemas Pydantic para que la respuesta tenga forma estable y no sea el dict
  crudo de Celery (que cambia entre versiones)

### Cómo verificarlo

Los endpoints responden con el worker arriba **y** con el worker abajo. Ese
segundo caso es el que hay que probar de verdad.

---

## Fase 7 — Cancelar tareas (`revoke`)

### Concepto aislado

El estado `REVOKED` es el que falta del vocabulario. Cancelar una tarea tiene
dos casos completamente distintos:

- **Todavía no empezó**: el worker recibe el id revocado y simplemente descarta
  el mensaje cuando le toca. Barato y seguro.
- **Ya está corriendo**: hay que `terminate=True`, que **mata el proceso hijo**
  con una señal. Es violento: la tarea no puede hacer cleanup, y si estaba a
  mitad de una escritura, quedó a mitad. Por eso `terminate` no es el default.

Detalle operativo: la lista de ids revocados vive **en memoria del worker**. Si
el worker reinicia, la olvida — salvo que arranques con `--statedb`.

### Qué construimos

`DELETE /tasks/{task_id}` con un flag `terminate`, y el manejo del estado
`REVOKED` en el endpoint de status.

### Deberías poder responder

- ¿Por qué `terminate=True` es peligroso con `task_acks_late=True`?
- ¿Qué pasa si revocás un `task_id` que no existe?

---

## Fase 8 — Tests + CHECK_LEARNING

### Concepto aislado

Testear tareas con reintentos tiene una trampa obvia: **no podés esperar 1+2+4
segundos reales en un test**. Las estrategias:

- `task_always_eager=True` — la tarea corre inline, sin broker. Sirve para
  probar la **lógica** de la tarea, pero **no** el comportamiento de retry ni de
  progreso (en eager el retry se comporta distinto).
- **Llamar a la función directamente** (`tarea.run(...)` o la función pura por
  debajo) — lo más limpio para la lógica de negocio.
- **Mockear** `self.retry` / `inspect()` — para probar *que se decidió
  reintentar*, sin ejecutar la espera.
- Separar siempre la **lógica** (testeable puro) de la **orquestación** (Celery).
  Si tu tarea es 3 líneas que llaman a un servicio, testeás el servicio.

### Qué construimos

- `tests/test_retries.py` — se reintenta lo transitorio, no lo permanente
- `tests/test_progress.py` — la tarea reporta los estados esperados
- `tests/test_monitoring.py` — el servicio con `inspect` mockeado, incluyendo el
  caso `None`
- `tests/test_routes.py` — los endpoints, incluido el modo "sin workers"
- `CHECK_LEARNING.md` — preguntas con respuestas plegadas, como en el mini 6

---

## Al terminar deberías poder explicar, sin mirar código

1. Cuándo reintentar y cuándo no, y cómo se modela esa decisión.
2. Qué es el thundering herd y por qué el jitter no es un detalle cosmético.
3. Qué pasa con una tarea que agota sus reintentos, y por qué eso necesita una DLQ.
4. Cómo una tarea reporta progreso y dónde vive ese dato.
5. Por qué `inspect()` es una llamada de red y qué implica para tu endpoint.
6. Los 7 estados y cuáles son "ready".
7. Cómo se testea todo esto sin esperar los delays reales.
