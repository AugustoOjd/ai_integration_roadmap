"""Instrumentación. Se activa desde el .env, no desde el código.

Logfire es OpenTelemetry: las spans salen igual con o sin su backend. Sin token
se imprimen en la consola, que alcanza para ver la forma de un run.
"""

import logfire

from app.core.config import settings


def configurar() -> None:
    if not settings.LOGFIRE:
        return

    logfire.configure(
        service_name="triage",
        # Sin token no se manda nada afuera y las spans van a stderr.
        send_to_logfire="if-token-present",
        # scrubbing borra lo que parece un secreto antes de emitir la span.
        # Por default está prendido; dejarlo explícito evita la tentación de
        # apagarlo cuando un valor legítimo se ve censurado.
        scrubbing=logfire.ScrubbingOptions(),
    )

    # Parchea todos los agentes: una span por run, una por request al modelo y
    # una por tool call, con los reintentos adentro.
    logfire.instrument_pydantic_ai()

    # Las queries de las tools, para ver el tiempo que NO es del modelo.
    logfire.instrument_sqlalchemy()
