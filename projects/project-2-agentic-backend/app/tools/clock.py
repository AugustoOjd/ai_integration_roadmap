"""La tool `get_current_time`.

El modelo no tiene reloj: no es que sea impreciso con la hora, no tiene ninguna
noción de "ahora". Sin esta tool, ante "¿qué día es hoy?" sólo puede decir que no
sabe o inventar una fecha con total convicción. La segunda es la peligrosa.

Es la otra mitad de para qué sirven las tools: `calculate` existe por exactitud
(el modelo podría intentar la cuenta y errarle), ésta por posibilidad.
"""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from app.tools.registry import registry


@registry.tool
def get_current_time(
    # Tiene default, así que el registry lo deja fuera de `required` en el JSON
    # Schema. Esa correspondencia sale sola de la firma.
    #
    # Que el modelo pueda pedir una zona importa: ante "¿qué hora es en Tokio?",
    # la conversión la hace la tool con la base de datos de zonas horarias y no
    # el modelo de memoria, que erra cerca de los cambios de horario.
    timezone: Annotated[
        str | None,
        Field(
            description=(
                "Zona horaria IANA, por ejemplo 'America/Argentina/Buenos_Aires' "
                "o 'Asia/Tokyo'. Si se omite, usa la zona local del servidor."
            )
        ),
    ] = None,
) -> str:
    """Devuelve la fecha y hora actuales en formato ISO 8601 con zona horaria.

    Usala siempre que necesites saber qué día u hora es: no tenés forma de
    saberlo por tu cuenta. Podés pedir una zona horaria específica.
    """
    if timezone is None:
        # .astimezone() sobre un datetime naive le pega la zona local. Sin eso el
        # ISO saldría sin offset ('2026-09-12T14:30:00') y el modelo asumiría lo
        # que se le ocurra, normalmente UTC.
        return datetime.now().astimezone().isoformat(timespec="seconds")

    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        # El modelo puede mandar 'Buenos Aires', 'GMT-3' o 'ARG'. El mensaje lo
        # lee él, así que dice qué formato se espera y da un ejemplo: con eso
        # reintenta bien en la vuelta siguiente.
        raise ValueError(
            f"zona horaria desconocida: {timezone!r}. "
            f"Se espera un identificador IANA, por ejemplo 'Asia/Tokyo'."
        ) from exc

    return datetime.now(tz=zone).isoformat(timespec="seconds")
