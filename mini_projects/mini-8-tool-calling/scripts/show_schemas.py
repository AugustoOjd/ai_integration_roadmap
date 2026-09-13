"""Fase 4 — Ver qué generó el registry, sin gastar un token.

Todo lo que hace el registry es determinístico y local: derivar schemas y
validar dicts. Nada de esto necesita al modelo, así que se puede inspeccionar
gratis. Aprovechalo — es la parte del sistema que MÁS conviene mirar de cerca,
porque es la que el modelo va a leer en cada request.

    uv run python -m scripts.show_schemas
"""

import json

from app.tools import registry
from app.tools.registry import ToolError


def main() -> None:
    print("=" * 70)
    print("LO QUE VE EL MODELO (derivado de las funciones, no escrito a mano)")
    print("=" * 70)
    for param in registry.to_params():
        print(json.dumps(param, indent=2, ensure_ascii=False))
        print()

    print("=" * 70)
    print("VALIDACIÓN: qué pasa con cada input")
    print("=" * 70)

    casos = [
        # Lo normal.
        ("calculate", {"expression": "42 * 2"}),
        # El modelo inventa un campo de más. Antes reventaba con un TypeError
        # incomprensible; ahora es un error que se le puede contar.
        ("calculate", {"expression": "42 * 2", "precision": 4}),
        # Falta el requerido.
        ("calculate", {}),
        # Tipo equivocado. Ojo: Pydantic convierte int -> str si puede, así que
        # esto probablemente PASE. No es un bug, es coerción; si querés que
        # falle, el tipo va como `StrictStr`.
        ("calculate", {"expression": 42}),
        # Sin argumentos, como corresponde.
        ("get_current_time", {}),
        # Una tool alucinada: los modelos inventan nombres, sobre todo cuando
        # hay varias parecidas.
        ("buscar_en_google", {"query": "python"}),
    ]

    for name, tool_input in casos:
        try:
            output = registry.execute(name, tool_input)
            print(f"OK    {name}({tool_input}) -> {output!r}")
        except ToolError as exc:
            # Este texto es el que termina dentro del `tool_result` con
            # `is_error: True`, o sea que lo LEE EL MODELO. Fijate si es lo
            # bastante claro como para que se corrija solo a partir de él.
            print(f"ERROR {name}({tool_input})\n      {exc}")


if __name__ == "__main__":
    main()
