# 🗺️ Mini 8 — Plan por fases

Cada fase es **autocontenida**: explica su concepto desde cero, se construye
sola, se verifica sola y se puede entender sin haber leído las otras. La única
dependencia real es la Fase 0 (el esqueleto donde vive todo lo demás).

El hilo conductor del mini es uno solo: **el modelo no ejecuta nada**. Devuelve
una *intención* ("quiero llamar a `calculate` con `{"expression": "42*2"}"`) y
vos ejecutás, devolvés el resultado y lo volvés a llamar. Todo lo demás —
registry, schemas, loop, paralelismo — son detalles de ingeniería alrededor de
ese único hecho.

| Fase | Tema | Depende de |
|------|------|-----------|
| 0 | Esqueleto + primera llamada sin tools | — |
| 1 | Anatomía de una tool: schema y `tool_use` | 0 |
| 2 | Cerrar el círculo: `tool_result` (un solo round-trip) | 1 |
| 3 | El agentic loop: `stop_reason == "tool_use"` | 2 |
| 4 | Tool registry: de función Python a schema | 3 |
| 5 | Las tools reales (y por qué `eval()` no) | 4 |
| 6 | Paralelismo y errores de tool | 3 (mejor con 5) |
| 7 | Endpoint FastAPI + observabilidad | 3, 6 |
| 8 | Tres loops: el tuyo, el `tool_runner` del SDK, Pydantic AI | 3 |
| 9 | Tests + CHECK_LEARNING | todas |

---

## Qué vas a aprender (el mapa conceptual)

1. **Tool use es un protocolo de turnos, no una llamada a función.** Vos y el
   modelo se pasan mensajes; el "call" es un bloque de contenido con un `id`.
2. **La descripción de la tool es prompt.** Si el modelo no llama a tu tool,
   el 90% de las veces el bug está en la `description`, no en el código.
3. **El schema es un contrato de entrada.** JSON Schema + `strict: true` para
   que los argumentos lleguen válidos, y validación propia igual (defensa en
   profundidad: el input de una tool es input no confiable).
4. **El loop es el agente.** Un agente mínimo es `while stop_reason ==
   "tool_use"`. El mini 9 sólo le agrega memoria, planificación y más tools.
5. **El historial es estado mutable y frágil.** Cada `tool_use` necesita su
   `tool_result` con el `tool_use_id` correcto, en el mismo turno, y los bloques
   de la respuesta se reenvían **tal cual** vinieron.
6. **Ejecutar lo que un LLM te pide es una superficie de ataque.** `eval()` en
   una tool es RCE con pasos extra.
7. **Los frameworks de agentes son azúcar sobre esto.** Pydantic AI y el
   `tool_runner` del SDK hacen lo mismo que tu loop; la fase 8 los pone lado a
   lado justamente para que se vea que no hay magia abajo.

---

## Fase 0 — Esqueleto + primera llamada sin tools

### Concepto aislado

Antes de tools, hay que ver la forma cruda de una respuesta de la Messages API.
Una respuesta **no es un string**: es un objeto con `content` (una *lista* de
bloques: `text`, `thinking`, `tool_use`...), un `stop_reason` y un `usage`.

Todo el mini se juega en leer bien esos tres campos. `stop_reason` es el que
manda el control de flujo:

| `stop_reason` | Qué significa |
|---|---|
| `end_turn` | El modelo terminó, hay respuesta final |
| `tool_use` | Quiere que ejecutes algo y le contestes |
| `max_tokens` | Se cortó a la mitad, subí el límite |
| `refusal` | Los clasificadores de seguridad declinaron |

### Qué construimos

- `pyproject.toml` con `anthropic`, `fastapi`, `pydantic-settings`, `uvicorn`
- `app/config.py` — settings (`ANTHROPIC_API_KEY`, modelo, `max_tokens`)
- `app/llm.py` — el cliente `Anthropic()` como singleton
- `app/main.py` — FastAPI con `/health`
- Un script suelto que manda "hola" y **imprime el objeto completo**, no el texto

**Modelo: `claude-haiku-4-5`.** El README del mini todavía dice
`claude-3-5-sonnet-20241022`, que está viejo. Haiku es la elección correcta acá:
un loop de tools hace varias llamadas por request y vas a iterar mucho en
desarrollo — a $1/$5 por MTok contra $5/$25 de la familia Opus, la diferencia se
nota. Tool use funciona igual en todos los modelos.

Tres particularidades de Haiku 4.5 que conviene saber desde el día 0, porque son
excepciones respecto de los modelos más nuevos:

- **Contexto de 200K**, no 1M. En un loop largo el historial crece rápido (ver
  fase 3): con Haiku el techo llega antes.
- **Thinking no es adaptativo.** Es el único modelo actual que sigue usando
  `thinking: {type: "enabled", budget_tokens: N}` (con `budget_tokens` menor a
  `max_tokens`, mínimo 1024). En este mini lo dejamos apagado.
- **`output_config.effort` da error.** Es una palanca de los modelos nuevos que
  acá no existe.

Ponelo en `config.py` como setting, no hardcodeado: si alguna fase se te
complica, cambiar a `claude-opus-5` es una línea de `.env` y sirve para
distinguir "mi código está mal" de "el modelo no llega".

### Cómo verificarlo

```bash
uv run python -m scripts.smoke     # imprime content, stop_reason, usage
uv run uvicorn app.main:app --reload
```

### Deberías poder responder

- ¿Por qué `content` es una lista y no un string?
- ¿Qué diferencia hay entre `max_tokens` y lo que realmente gastaste (`usage`)?
- ¿Por qué el cliente se crea una sola vez y no por request?

---

## Fase 1 — Anatomía de una tool: schema y `tool_use`

### Concepto aislado

Una tool que le pasás al modelo son **tres cosas y ninguna es código**:

```python
{
  "name": "calculate",              # el identificador que te va a devolver
  "description": "...",             # PROMPT: cuándo usarla, qué NO hace
  "input_schema": {...}             # JSON Schema de los argumentos
}
```

El modelo nunca ve tu función. Ve esas tres cosas, más el mensaje del usuario, y
decide. Por eso la `description` es la pieza de ingeniería más importante: es
literalmente parte del prompt. Una descripción buena dice **cuándo usarla, qué
espera en cada campo y cuáles son sus límites**; una mala dice "calcula cosas".

En esta fase **no ejecutamos nada**. Mandamos el prompt con `tools=[...]` y
miramos qué vuelve:

```python
ToolUseBlock(type="tool_use", id="toolu_01ABC...", name="calculate",
             input={"expression": "42 * 2"})
```

Ese `id` es la clave de correlación de toda la fase 2.

### Qué construimos

- Una tool definida a mano (dict literal), sin registry todavía
- Una llamada con `tools=[...]` que sólo imprime los bloques que vuelven
- Un experimento: la misma pregunta **con** y **sin** la tool declarada

### Cómo verificarlo

Preguntá "¿cuánto es 42 por 2?" y mirá `stop_reason == "tool_use"`.
Después degradá la `description` a `"hace cálculos"` y observá que empieza a
contestar de memoria en vez de llamar a la tool. Ese experimento es la fase.

### Deberías poder responder

- ¿Dónde vive la decisión de usar una tool: en tu código o en el modelo?
- ¿Para qué sirve `tool_choice` (`auto` / `none` / `tool`) y por qué `auto` es el default?
- ¿Qué pasa si dos tools tienen descripciones que se solapan?

---

## Fase 2 — Cerrar el círculo: `tool_result` (un solo round-trip)

### Concepto aislado

El modelo pidió. Ahora vos ejecutás y contestás. La respuesta va como un mensaje
con **rol `user`** (contraintuitivo: vos sos el "usuario" desde la perspectiva
del modelo) que contiene un bloque `tool_result`:

```python
{"type": "tool_result",
 "tool_use_id": "toolu_01ABC...",   # el id EXACTO del tool_use
 "content": "84"}
```

Y el historial queda así — tres mensajes, no dos:

```
user      : "¿cuánto es 42 por 2?"
assistant : [thinking?, text?, tool_use(id=X)]      ← la respuesta COMPLETA
user      : [tool_result(tool_use_id=X)]
```

Dos reglas que se rompen siempre:

1. El mensaje `assistant` que agregás al historial es `response.content` **entero
   y sin tocar**, no sólo el bloque de texto. Con Haiku y thinking apagado vas a
   ver sólo `text` y `tool_use`, pero la regla es "reenviar la lista completa",
   no "reenviar text y tool_use": si algún día prendés thinking o cambiás de
   modelo, filtrar bloques rompe el razonamiento del turno.
2. Todo `tool_use` **debe** tener su `tool_result` en el turno siguiente. Si
   falta uno, la API rechaza el request.

### Qué construimos

- Una función `execute(name, input) -> str` con un `if` (sí, un `if`)
- El armado manual del historial de 3 mensajes
- La segunda llamada a la API, que ahora sí devuelve `end_turn` + texto final

### Cómo verificarlo

Imprimí el historial completo antes de la segunda llamada. Después probá a
propósito: mandá un `tool_use_id` inventado y leé el error de la API. Aprender
el mensaje de error acá vale más que evitarlo.

### Deberías poder responder

- ¿Por qué el `tool_result` va con rol `user`?
- ¿Qué pasa si mandás sólo el bloque de texto del assistant y descartás el `tool_use`?
- ¿El `content` de un `tool_result` tiene que ser string? ¿Qué le conviene al modelo?

---

## Fase 3 — El agentic loop: `stop_reason == "tool_use"`

### Concepto aislado

La fase 2 asumió **una** tool y **un** round-trip. En la vida real el modelo
puede encadenar: buscar → calcular sobre lo buscado → responder. Eso no se
resuelve con más `if`, se resuelve con un loop:

```
loop:
  response = messages.create(historial, tools)
  si stop_reason != "tool_use": salir, devolver el texto
  ejecutar cada tool_use del turno
  agregar el assistant y el user(tool_results) al historial
```

Esto es, literalmente, un agente. El mini 9 no le agrega magia: le agrega
memoria, más tools y mejores prompts, pero el motor es este `while`.

Dos cosas que no son opcionales:

- **`max_iterations`**: sin tope, un modelo confundido te hace loop infinito
  quemando tokens. 5-10 y cortás con un error claro.
- **Corte por presupuesto**: acumulá `usage.output_tokens` por vuelta y logueá.

### Qué construimos

- `app/agent.py` — `run_agent(prompt) -> AgentResult` con el loop
- Un dataclass/modelo de resultado: texto final, `tools_used`, `iterations`, `usage`
- Logging de cada vuelta: qué tool, con qué input, qué devolvió

### Cómo verificarlo

Un prompt que necesite dos tools encadenadas ("¿qué hora es? y multiplicá por 2
el minuto actual") tiene que dar `iterations >= 2`. Bajá `max_iterations` a 1 y
verificá que corta limpio en vez de colgarse.

### Deberías poder responder

- ¿Cuál es la condición de salida del loop y por qué no es "ya usé una tool"?
- ¿Cómo crece el historial por vuelta y qué implica para el costo?
- ¿Qué hacés si se alcanza `max_iterations`: error, respuesta parcial, o retry?

---

## Fase 4 — Tool registry: de función Python a schema

### Concepto aislado

Escribir el JSON Schema a mano y además la función, y además el `if` del
dispatch, es tres lugares para desincronizar. Un **registry** es el patrón que
los unifica: una función Python decorada, y el schema se **deriva** de sus tipos.

```python
@registry.tool
def calculate(expression: str) -> dict:
    """Evalúa una expresión aritmética. Sólo números y + - * / ( )."""
```

De ahí salen las tres partes: `name` del nombre de la función, `description`
del docstring, `input_schema` de los tipos (Pydantic genera JSON Schema con
`model_json_schema()`). El registry expone dos operaciones:

- `to_api()` → la lista de tools para el request
- `execute(name, input)` → validar con el modelo Pydantic y despachar

**`strict: true`** en la definición de la tool hace que la API garantice que
`input` valida contra tu schema (requiere `additionalProperties: false` y
`required`). Aun así validás vos: el `input` de una tool es entrada no
confiable, generada por un modelo a partir de texto de un usuario.

### Qué construimos

- `app/tools/registry.py` — decorador, derivación del schema, dispatch
- Un modelo Pydantic de input por tool
- Manejo de tool desconocida y de input inválido → `tool_result` con `is_error`

### Cómo verificarlo

Registrá una tool nueva **sin tocar el loop de la fase 3**. Si tuviste que
tocarlo, el registry está mal acoplado.

### Deberías poder responder

- ¿Por qué el docstring termina siendo prompt de producción?
- ¿Qué te da `strict: true` y qué NO te da?
- ¿Qué pasa si el modelo alucina un nombre de tool que no existe?

---

## Fase 5 — Las tools reales (y por qué `eval()` no)

### Concepto aislado

Las tres tools del mini, cada una con su lección:

**`calculate`** — la lección de seguridad. El README propone `eval(expression)`.
Eso es **ejecución remota de código**: el input viene de un modelo que a su vez
lo generó desde texto de un usuario. `__import__('os').system('rm -rf /')` es
una expresión válida de Python. La versión correcta parsea con `ast.parse(expr,
mode="eval")` y recorre el árbol permitiendo **sólo** nodos aritméticos
(`BinOp`, `UnaryOp`, `Constant` numérica, operadores `+ - * / // % **`),
rechazando todo lo demás. Regla general: *una tool nunca ejecuta el input, lo
interpreta*.

**`get_current_time`** — la lección de determinismo. Una tool sin argumentos
(`input_schema` con `properties: {}`). Existe porque el modelo **no tiene reloj**:
su única fuente de "ahora" sos vos. Devolvé ISO 8601 con timezone explícita.

**`search`** — la lección de frontera de red. Sea un stub o un `httpx` real:
timeout obligatorio, tamaño de respuesta acotado, y el resultado recortado antes
de devolverlo (todo lo que devolvés entra al contexto y lo pagás en tokens cada
vuelta del loop).

### Qué construimos

- `app/tools/calculator.py` con evaluador AST seguro
- `app/tools/clock.py`
- `app/tools/search.py` (stub determinista para tests + implementación real)

### Cómo verificarlo

Tests directos a las funciones, sin LLM: `calculate("2+2") == 4`, y que
`calculate("__import__('os')")` levante un error controlado, no un `NameError`.

### Deberías poder responder

- ¿Qué nodos del AST permitís y por qué la lista es *allowlist* y no *blocklist*?
- ¿Por qué el tamaño del resultado de una tool es un problema de costo?
- ¿Qué pasa si una tool tarda 30s? ¿Quién tiene el timeout?

---

## Fase 6 — Paralelismo y errores de tool

### Concepto aislado

Un solo turno del assistant puede traer **varios** bloques `tool_use` (está
activado por default). "¿Qué hora es y cuánto es 100*2?" devuelve dos en la
misma respuesta.

Dos reglas:

1. **Ejecutalas en paralelo** (`asyncio.gather`) — son independientes por
   definición, si el modelo las pidió juntas.
2. **Todos los `tool_result` van en UN SOLO mensaje `user`.** Partirlos en
   varios mensajes le enseña al modelo, turno a turno, a dejar de pedir cosas en
   paralelo. Es un bug silencioso que se paga en latencia.

**Errores:** si una tool explota, no propagues la excepción hacia arriba ni
omitas el bloque. Devolvé el `tool_result` con `is_error: True` y un mensaje
útil. El modelo es sorprendentemente bueno reaccionando a eso: reintenta con
otros argumentos o le avisa al usuario. Omitir el bloque, en cambio, es un 400
de la API.

### Qué construimos

- Ejecución concurrente de los `tool_use` de un turno
- `_to_result_block(...)` que envuelve éxito y error con la misma forma
- Un test con una tool que falla a propósito

### Cómo verificarlo

Prompt con dos tools → un solo mensaje `user` con dos bloques. Verificalo
imprimiendo el historial, no confiando en que "anduvo".

### Deberías poder responder

- ¿Por qué partir los `tool_result` degrada el comportamiento del modelo?
- ¿Cuándo conviene `disable_parallel_tool_use`?
- ¿Un error de tool es un error del request? ¿Por qué no?

---

## Fase 7 — Endpoint FastAPI + observabilidad

### Concepto aislado

Envolver el agente en HTTP tiene tensiones propias que no existen en un script:

- **Latencia**: un loop de 3 vueltas son 3 llamadas al modelo. Segundos, no
  milisegundos. O streameás, o el cliente necesita un timeout generoso.
- **Trazabilidad**: la respuesta tiene que decir *qué hizo*, no sólo el texto:
  `tools_used`, `iterations`, tokens. Sin eso, un agente en producción es una
  caja negra que no podés debuggear ni costear.
- **Errores**: `RateLimitError` → 429, `APIConnectionError` → 503, tu
  `MaxIterationsError` → 422. Una cadena de `except` específica, no un
  `except Exception`.

### Qué construimos

- `app/schemas/agent.py` — request/response Pydantic
- `app/routes/agent.py` — `POST /agent/tool-calling`
- Manejo de errores tipados del SDK

### Cómo verificarlo

```bash
curl -X POST localhost:8000/agent/tool-calling \
  -H 'content-type: application/json' \
  -d '{"prompt": "¿Qué hora es? Y calculá 100 * 2"}'
# tools_used: ["get_current_time", "calculate"]
```

### Deberías poder responder

- ¿Qué campos necesita la respuesta para que el endpoint sea debuggeable?
- ¿Qué código HTTP devolvés si el modelo se queda sin iteraciones?
- ¿Qué información NO deberías devolverle al cliente?

---

## Fase 8 — Tres loops: el tuyo, el `tool_runner` del SDK, Pydantic AI

### Concepto aislado

Escribiste el loop a mano **a propósito**, en las fases 1-7. Esta fase es el pago
de esa inversión: la misma feature, implementada tres veces, en tres niveles de
abstracción. La lección no es "cuál gana", es **qué te esconde cada una y qué te
cuesta cuando se rompe**.

**Nivel 1 — tu loop (fases 3-6).** Ves todo: `tool_use`, `tool_use_id`,
`tool_result`, `stop_reason`, el historial creciendo. Es el nivel donde debuggeás
cuando algo falla en los otros dos.

**Nivel 2 — `tool_runner` del SDK.** El loop ya viene hecho:

```python
runner = client.beta.messages.tool_runner(model=..., tools=[...], messages=[...])
final = runner.until_done()
```

Con el decorador `@beta_tool`, el SDK deriva el schema del docstring + type hints
y ejecuta tus funciones solo. Sigue siendo el protocolo de Anthropic a la vista:
seguís hablando de `tool_use` y `tool_result`, sólo que no armás el historial vos.
Te da hooks por turno (aprobación, logging, interceptar errores), streaming y
compaction.

**Nivel 3 — Pydantic AI.** Un framework de agentes completo, agnóstico de
proveedor:

```python
agent = Agent("anthropic:claude-haiku-4-5", deps_type=..., output_type=...)

@agent.tool
def calculate(ctx: RunContext, expression: str) -> float: ...

result = await agent.run("¿cuánto es 42 por 2?")
```

Acá el vocabulario cambia: ya no hablás de `tool_use` ni de `stop_reason`, hablás
de *agentes*, *dependencias* y *output tipado*. Deriva schemas con Pydantic
(igual que tu registry de la fase 4, pero hecho), valida el output del modelo
contra un tipo, y reintenta solo cuando la validación falla. Lo que ganás es
tipado de punta a punta y portabilidad entre proveedores; lo que perdés es
visibilidad del protocolo — y, si el modelo deja de llamar una tool, estás
debuggeando a través de una capa más.

**Por qué esta fase va acá y no al principio:** cualquiera de los tres niveles
resuelve el mini. Pero si arrancabas en el nivel 3, el mini 9 (agent loop) no
tendría piso: sabrías usar `Agent(...)` sin poder explicar qué pasa adentro.

### Qué construimos

- `app/agent_runner.py` — la feature con `tool_runner` + un hook que loguea igual
  que tu loop manual
- `app/agent_pydantic_ai.py` — la feature con Pydantic AI, reusando los **mismos**
  modelos Pydantic de input de la fase 4
- Una tabla corta en el README: qué controlás, qué te esconde y cuándo elegir cada uno

### Cómo verificarlo

Los mismos prompts de la fase 3 contra las tres implementaciones, mismo
resultado. Después, el ejercicio que vale: degradá una `description` (como en la
fase 1) y fijate **en cuál de las tres te das cuenta más rápido de qué pasó**.

### Deberías poder responder

- ¿Qué hace el `tool_runner` que tu loop no hacía?
- ¿Dónde quedó el `tool_use_id` en la versión con Pydantic AI? ¿Lo podés ver?
- ¿Qué te da el `output_type` de Pydantic AI que el protocolo crudo no te da?
- ¿En qué caso concreto NO usarías un framework y te quedarías con el loop propio?
- ¿Por qué `client.beta.messages` y no `client.messages` para el runner?

---

## Fase 9 — Tests + CHECK_LEARNING

### Concepto aislado

Testear código que llama a un LLM tiene una regla: **no llames al LLM en los
tests**. Son lentos, cuestan plata y no son determinísticos. Se testea en tres
capas:

1. **Tools puras**, sin mock: `calculate("2+2") == 4`. Es código común.
2. **El loop, con el cliente mockeado**: armás a mano una secuencia de respuestas
   (`tool_use` → `tool_use` → `end_turn`) y verificás que el loop las orquesta
   bien: historial correcto, `tool_use_id` correlacionados, corte en
   `max_iterations`. Acá vive el 80% de tus bugs.
3. **El endpoint**, con `TestClient` y el agente mockeado: códigos HTTP y forma
   de la respuesta.

Opcionalmente una cuarta capa marcada `@pytest.mark.integration`, excluida por
default, que sí pega a la API real.

### Qué construimos

- `tests/conftest.py` — fixture del cliente Anthropic fake
- `tests/test_tools.py`, `tests/test_agent.py`, `tests/test_routes.py`
- `CHECK_LEARNING.md` con las preguntas de cada fase

### Deberías poder responder

- ¿Por qué mockear el cliente y no la función `run_agent`?
- ¿Cómo testeás que los `tool_result` van todos en un mensaje?
- ¿Qué NO se puede testear sin llamar al modelo real?

---

## Correcciones al README del mini

Detectadas al armar el plan, se aplican en las fases indicadas:

| README dice | Correcto | Fase |
|---|---|---|
| `model="claude-3-5-sonnet-20241022"` | `claude-haiku-4-5`, como setting | 0 |
| `calculate` usa `eval(expression)` | Evaluador AST con allowlist | 5 |
| Itera `response.content` buscando `tool_use` | El control de flujo es `stop_reason` | 3 |
| El ejemplo no reenvía el mensaje del assistant al historial | Se reenvía `response.content` completo | 2 |
| Un `tool_result` por mensaje | Todos los del turno en un mismo mensaje `user` | 6 |
