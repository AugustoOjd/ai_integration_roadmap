"""El contrato HTTP del agente.

Acá aparece el segundo uso de Pydantic en el mini, y conviene no confundirlo
con el primero:

    app/tools/registry.py   valida lo que manda EL MODELO  (input no confiable)
    app/schemas/agent.py    valida lo que manda EL CLIENTE (input no confiable)

Son dos fronteras distintas del sistema, y las dos se validan por la misma
razón: nada de lo que entra desde afuera se ejecuta sin revisar.
"""

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    """Lo que entra por el endpoint."""

    prompt: str = Field(
        # Los límites no son burocracia, son control de costo y de abuso. El
        # prompt viaja al modelo y se paga por token, en CADA vuelta del loop;
        # sin techo, un cliente puede mandarte 500 KB de texto y multiplicarlo
        # por cinco iteraciones. Es una factura, no un error.
        min_length=1,
        max_length=2000,
        description="La pregunta o instrucción para el agente.",
        # `examples` aparece en la documentación automática de /docs, que es
        # gratis y es lo primero que va a mirar quien consuma esto.
        examples=["¿Qué hora es en Tokio? Y cuánto es 4823 por 1917."],
    )


class Usage(BaseModel):
    """Los tokens que costó la corrida ENTERA, sumando todas las vueltas."""

    input_tokens: int
    output_tokens: int


class AgentResponse(BaseModel):
    """Lo que sale del endpoint.

    `final_answer` es lo único que le importa al usuario. Todo lo demás existe
    para vos: sin esos campos, un agente en producción es una caja negra que no
    podés ni debuggear ni costear.

    Fijate que NO devolvemos el historial completo de mensajes. Adentro hay
    mensajes de error de tools, nombres internos y, potencialmente, datos de
    otros sistemas: es información de diagnóstico, va al log, no al cliente.
    """

    prompt: str
    final_answer: str
    # Con repetidos y en orden de invocación: ver tres `calculate` seguidos te
    # dice que el modelo estuvo peleando con algo.
    tools_used: list[str]
    # Cuántas idas y vueltas al modelo hicieron falta. Es tu métrica de latencia
    # y de costo a la vez: cada iteración es una llamada HTTP a la API.
    iterations: int
    usage: Usage
