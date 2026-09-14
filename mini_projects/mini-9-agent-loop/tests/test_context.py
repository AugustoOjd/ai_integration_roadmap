"""Fase 8 — recortar sin romper pares.

El invariante que se afirma en casi todos los tests es `pares_intactos`: pase lo
que pase con el recorte, todo `tool_use` conserva su `tool_result` y viceversa.
Si eso se rompe, la API devuelve 400 y la sesión queda inservible.

Los tests usan un medidor de mentira —tokens = caracteres— en vez de
`count_tokens`. Es determinístico, gratis, y no cambia lo que se está probando:
la lógica de recorte no sabe de dónde salen los números.
"""

import json

import pytest
from anthropic.types import MessageParam

from app.context import (
    CONSERVAR_RECIENTES,
    PLACEHOLDER,
    ajustar,
    pares_intactos,
)


def medidor_por_caracteres(messages: list[MessageParam]) -> int:
    """Tokens = caracteres del JSON. Falso pero monótono, que es lo que importa:
    recortar siempre baja el número."""
    return len(json.dumps(messages, default=str))


async def medir(messages: list[MessageParam]) -> int:
    return medidor_por_caracteres(messages)


def turno(numero: int, *, relleno: int = 200) -> list[MessageParam]:
    """Un turno completo con una tool: user → assistant(tool_use) → user(result)
    → assistant(texto)."""
    return [
        {"role": "user", "content": f"pregunta {numero}"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"toolu_{numero}",
                    "name": "search",
                    "input": {"query": f"q{numero}"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": f"toolu_{numero}",
                    # Lo pesado del historial: el resultado de la tool.
                    "content": "x" * relleno,
                }
            ],
        },
        {"role": "assistant", "content": [{"type": "text", "text": f"respuesta {numero}"}]},
    ]


def conversacion(turnos: int, *, relleno: int = 200) -> list[MessageParam]:
    return [mensaje for i in range(1, turnos + 1) for mensaje in turno(i, relleno=relleno)]


# ---------------------------------------------------------------------------
# El caso fácil
# ---------------------------------------------------------------------------


async def test_si_entra_no_se_toca_nada():
    """Un historial que cabe se manda tal cual. El recorte es un remedio, no un
    hábito: cada `tool_result` vaciado es información que el modelo pierde."""
    historial = conversacion(2)

    ajustado, tokens = await ajustar(historial, limite=1_000_000, medir=medir)

    assert ajustado == historial
    assert tokens == medidor_por_caracteres(historial)


# ---------------------------------------------------------------------------
# Paso 2: vaciar tool_results
# ---------------------------------------------------------------------------


async def test_vacia_los_tool_results_viejos_primero():
    """La estrategia barata antes que la destructiva.

    El contenido de una búsqueda de hace diez turnos ya está resumido en el
    texto que el modelo escribió después: es lo más pesado y lo menos necesario.

    El `relleno` es grande a propósito: con resultados chicos, vaciar los viejos
    no mueve la aguja y el paso 3 termina tirando turnos igual. Que ese sea el
    caso realista —los `tool_result` son lo pesado del historial— es justamente
    lo que hace que esta estrategia valga la pena.
    """
    historial = conversacion(5, relleno=2_000)
    limite = int(medidor_por_caracteres(historial) * 0.6)

    ajustado, tokens = await ajustar(historial, limite=limite, medir=medir)

    assert tokens <= limite
    # No se perdió NINGÚN mensaje: mismo largo.
    assert len(ajustado) == len(historial)
    # Y los resultados viejos quedaron vaciados.
    resultados = [
        b
        for m in ajustado
        if not isinstance(m["content"], str)
        for b in m["content"]
        if b["type"] == "tool_result"
    ]
    assert PLACEHOLDER in [r["content"] for r in resultados]


async def test_vaciar_nunca_rompe_un_par():
    """LA razón por la que el recorte selectivo es el bueno.

    No borra bloques: vacía el contenido y deja el bloque con su `tool_use_id`.
    Un par no se puede romper si nadie saca una de sus mitades.
    """
    historial = conversacion(6, relleno=400)

    ajustado, _ = await ajustar(historial, limite=1_000, medir=medir)

    assert pares_intactos(ajustado)


async def test_los_tool_results_recientes_sobreviven():
    """Los resultados recientes son los datos con los que el modelo razona AHORA.
    Vaciarlos es lo mismo que no haber llamado a la tool."""
    historial = conversacion(5, relleno=2_000)
    limite = int(medidor_por_caracteres(historial) * 0.6)

    ajustado, _ = await ajustar(historial, limite=limite, medir=medir)

    ultimos = ajustado[-CONSERVAR_RECIENTES:]
    resultados_recientes = [
        b
        for m in ultimos
        if not isinstance(m["content"], str)
        for b in m["content"]
        if b["type"] == "tool_result"
    ]
    assert resultados_recientes
    assert all(r["content"] != PLACEHOLDER for r in resultados_recientes)


async def test_no_muta_el_historial_original():
    """Los `messages` que entran son los mismos objetos que después se
    persisten. Mutarlos acá guardaría el placeholder en la base — justo lo que
    este módulo NO tiene que hacer."""
    historial = conversacion(5, relleno=500)
    copia = json.loads(json.dumps(historial))

    await ajustar(historial, limite=100, medir=medir)

    assert historial == copia


# ---------------------------------------------------------------------------
# Paso 3: tirar turnos enteros
# ---------------------------------------------------------------------------


async def test_tira_turnos_enteros_cuando_vaciar_no_alcanza():
    """Y los tira de a turnos completos, nunca de a mensajes sueltos."""
    historial = conversacion(8, relleno=100)
    limite = 900

    ajustado, tokens = await ajustar(historial, limite=limite, medir=medir)

    assert tokens <= limite
    assert len(ajustado) < len(historial)
    assert pares_intactos(ajustado)
    # Lo que quedó es el final de la conversación, no un pedazo del medio.
    assert ajustado[-1] == historial[-1]


async def test_corta_siempre_al_inicio_de_un_turno():
    """Cortar en cualquier otro lado deja el historial empezando con un
    `tool_result` sin su pedido, que es un request inválido."""
    historial = conversacion(6, relleno=100)

    ajustado, _ = await ajustar(historial, limite=700, medir=medir)

    primero = ajustado[0]
    assert primero["role"] == "user"
    # Y es texto de verdad, no un mensaje `user` que en realidad es tool_result.
    assert isinstance(primero["content"], str) or all(
        b["type"] != "tool_result" for b in primero["content"]
    )


async def test_nunca_recorta_por_debajo_de_un_turno():
    """Con un solo turno que igual no entra, devuelve lo que hay.

    No levanta: quien llama (el loop) ya tiene su manejo para "no entra", y que
    esta función decidiera abortar le sacaría esa decisión.
    """
    historial = conversacion(1, relleno=5_000)

    ajustado, tokens = await ajustar(historial, limite=10, medir=medir)

    assert tokens > 10
    assert pares_intactos(ajustado)
    assert len(ajustado) == 4


@pytest.mark.parametrize("turnos", [1, 2, 5, 12])
@pytest.mark.parametrize("limite", [10, 500, 2_000, 10_000])
async def test_el_invariante_se_sostiene_siempre(turnos: int, limite: int):
    """Barrido: para cualquier combinación, los pares quedan intactos.

    Es el test más aburrido del archivo y el que más vale. El recorte es el
    lugar del mini donde es más fácil romper el historial sin darse cuenta,
    porque el síntoma aparece recién en el request SIGUIENTE.
    """
    ajustado, _ = await ajustar(conversacion(turnos, relleno=300), limite=limite, medir=medir)

    assert pares_intactos(ajustado)
    assert ajustado, "nunca se devuelve un historial vacío"


# ---------------------------------------------------------------------------
# El detector de huérfanos
# ---------------------------------------------------------------------------


def test_pares_intactos_detecta_un_tool_use_huerfano():
    historial = conversacion(1)
    # Sacamos el mensaje con el tool_result: el pedido queda solo.
    del historial[2]

    assert not pares_intactos(historial)


def test_pares_intactos_detecta_un_tool_result_huerfano():
    historial = conversacion(1)
    # Sacamos el mensaje con el tool_use: el resultado queda solo. Es lo que
    # pasa si el recorte corta por el lado equivocado.
    del historial[1]

    assert not pares_intactos(historial)
