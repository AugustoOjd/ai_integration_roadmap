"""Capa 3: el endpoint, con el agente mockeado.

Acá NO se testea el loop —eso ya está cubierto en `test_agent.py`— sino la
traducción: de `AgentResult` a JSON, y de excepción a código HTTP.

Es la capa más chica y la que más rompe contratos: un código que cambia de 422
a 500 no rompe ningún test de backend y sí rompe al cliente.
"""

import httpx2 as httpx
import pytest
from anthropic import APIConnectionError

from app.agent import AgentResult, MaxIterationsError
from app.routes import agent as rutas


@pytest.fixture
def agente_que_devuelve(monkeypatch):
    """Reemplaza `run_agent` por uno que devuelve o levanta lo que le digas.

    Ojo con la asimetría respecto de `test_agent.py`: allá mockear `run_agent`
    habría sido absurdo (es el código bajo prueba), acá es exactamente lo
    correcto (es la dependencia del código bajo prueba).
    """

    def _configure(*, returns=None, raises=None):
        async def fake(prompt: str, **kwargs):
            if raises is not None:
                raise raises
            return returns

        monkeypatch.setattr(rutas, "run_agent", fake)

    return _configure


def test_devuelve_la_traza_completa(client, agente_que_devuelve):
    """El contrato: no alcanza con la respuesta, hace falta saber qué hizo."""
    agente_que_devuelve(
        returns=AgentResult(
            text="Son las 14:30.",
            tools_used=["get_current_time"],
            iterations=2,
            input_tokens=250,
            output_tokens=50,
        )
    )

    respuesta = client.post("/agent/tool-calling", json={"prompt": "¿qué hora es?"})

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "prompt": "¿qué hora es?",
        "final_answer": "Son las 14:30.",
        "tools_used": ["get_current_time"],
        "iterations": 2,
        "usage": {"input_tokens": 250, "output_tokens": 50},
    }


def test_no_convergio_es_422(client, agente_que_devuelve):
    """No falló el cliente (400) ni el proveedor (503): no se pudo resolver."""
    agente_que_devuelve(raises=MaxIterationsError("no convergió"))

    respuesta = client.post("/agent/tool-calling", json={"prompt": "algo imposible"})

    assert respuesta.status_code == 422


def test_proveedor_inalcanzable_es_503(client, agente_que_devuelve):
    agente_que_devuelve(
        raises=APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    )

    respuesta = client.post("/agent/tool-calling", json={"prompt": "hola"})

    # 503 y no 502: 502 diría "el upstream contestó mal", y acá no contestó nada.
    assert respuesta.status_code == 503


def test_nunca_filtra_detalles_internos(client, agente_que_devuelve):
    """Lo mismo que protegemos frente al modelo, protegido frente al cliente."""
    agente_que_devuelve(
        raises=APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages?key=secreto")
        )
    )

    respuesta = client.post("/agent/tool-calling", json={"prompt": "hola"})

    assert "secreto" not in respuesta.text
    assert "api.anthropic.com" not in respuesta.text


@pytest.mark.parametrize(
    "payload",
    [
        {},  # falta el prompt
        {"prompt": ""},  # vacío
        {"prompt": "x" * 2001},  # pasado de largo: control de costo
    ],
)
def test_rechaza_payloads_invalidos_antes_de_gastar(client, payload):
    """Pydantic corta antes de que el request llegue al modelo.

    Importa que sea ANTES: un prompt de 500 KB no es un error de formato, es una
    factura. Y este test no necesita mockear nada porque la validación ocurre
    antes de que el endpoint ejecute una sola línea.
    """
    assert client.post("/agent/tool-calling", json=payload).status_code == 422


def test_health_no_llama_al_modelo(client):
    """Un load balancer pega acá cada pocos segundos: tiene que ser gratis."""
    assert client.get("/health").json() == {"status": "ok"}
