"""La tool `get_current_time`.

Existe por un motivo que no es obvio hasta que lo chocás: el modelo NO TIENE
RELOJ. No es que sea impreciso con la hora — no tiene ninguna noción de "ahora".
Lo único que sabe es que su entrenamiento terminó en algún momento, y a partir
de ahí, nada.

Sin esta tool, a "¿qué día es hoy?" sólo puede hacer dos cosas: decir que no
sabe, o inventar una fecha con total convicción. La segunda es la peligrosa.

Es también el ejemplo más limpio de la otra mitad de para qué sirven las tools.
`calculate` existe por EXACTITUD (el modelo podría intentar la cuenta y errarle);
esta existe por POSIBILIDAD: no hay forma de que la responda por su cuenta.
"""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from app.tools.registry import registry


@registry.tool
def get_current_time(
    # Un parámetro OPCIONAL: tiene default, así que el registry lo deja fuera
    # de `required` en el JSON Schema. Esa correspondencia sale sola de la
    # firma — no hay nada que sincronizar a mano.
    #
    # Vale la pena que el modelo pueda pedir una zona: si el usuario pregunta
    # "¿qué hora es en Tokio?", la conversión la hace la tool (bien, con la
    # base de datos de zonas horarias) y no el modelo de memoria (mal, y peor
    # cerca de los cambios de horario de verano).
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
        # `.astimezone()` sobre un datetime naive le pega la zona local del
        # sistema. Sin eso, el ISO saldría sin offset ('2026-09-12T14:30:00') y
        # sería ambiguo: el modelo no tiene forma de desambiguarlo y va a
        # asumir lo que se le ocurra, normalmente UTC.
        return datetime.now().astimezone().isoformat(timespec="seconds")

    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        # El modelo puede mandar 'Buenos Aires', 'GMT-3' o 'ARG'. Ninguna es
        # IANA válida. El mensaje de error lo lee él, así que le decimos
        # exactamente qué formato esperamos y damos un ejemplo: con eso
        # reintenta bien en la vuelta siguiente.
        raise ValueError(
            f"zona horaria desconocida: {timezone!r}. "
            f"Se espera un identificador IANA, por ejemplo 'Asia/Tokyo'."
        ) from exc

    return datetime.now(tz=zone).isoformat(timespec="seconds")
