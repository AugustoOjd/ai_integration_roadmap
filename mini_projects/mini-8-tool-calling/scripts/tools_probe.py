"""Fase 5 — Probar las tools directo, sin modelo.

Son funciones de Python comunes: se llaman y se verifican sin gastar un token
ni depender de que el modelo decida usarlas. Esa es la razón por la que el
decorador del registry devuelve la función intacta.

    uv run python -m scripts.tools_probe
"""

from app.tools.calculator import calculate
from app.tools.clock import get_current_time
from app.tools.search import search

# (expresión, resultado esperado). Aritmética normal.
CASOS_OK = [
    ("2 + 2", 4),
    ("4823 * 1917", 9245691),
    ("(15 + 5) / 4", 5),
    ("2 ** 10", 1024),
    ("-3 * -3", 9),
    ("17 % 5", 2),
    ("17 // 5", 3),
]

# Lo que tiene que RECHAZAR. Las primeras cinco son exactamente lo que
# `eval(expression)` habría ejecutado sin chistar.
CASOS_RECHAZADOS = [
    # Lectura de archivos arbitrarios.
    "open('/etc/passwd').read()",
    # Ejecución de comandos del sistema.
    "__import__('os').system('id')",
    # Robo de la API key desde el entorno del proceso.
    "__import__('os').environ['ANTHROPIC_API_KEY']",
    # El camino clásico para escaparse de un sandbox de Python.
    "().__class__.__bases__[0].__subclasses__()",
    # Cualquier variable: no hay nombres permitidos, sólo literales.
    "settings",
    # Denegación de servicio por CPU y memoria: sin el techo del exponente,
    # esta línea sola tumba el proceso.
    "9 ** 999999999",
    # Lo mismo, con el exponente escondido detrás de una cuenta.
    "2 ** (99999 * 99999)",
    # Errores honestos, no ataques, pero también tienen que ser controlados.
    "1 / 0",
    "2 +",
    "raíz cuadrada de 16",
]


def main() -> None:
    print("=" * 70)
    print("ARITMÉTICA")
    print("=" * 70)
    for expression, expected in CASOS_OK:
        got = calculate(expression)
        estado = "ok " if got == expected else "MAL"
        print(f"  [{estado}] {expression:>16} = {got}")

    print("\n" + "=" * 70)
    print("LO QUE eval() HABRÍA EJECUTADO")
    print("=" * 70)
    for expression in CASOS_RECHAZADOS:
        try:
            got = calculate(expression)
            # Si algo cae acá, el evaluador tiene un agujero.
            print(f"  [AGUJERO] {expression!r} devolvió {got!r}")
        except ValueError as exc:
            # Un error CONTROLADO: ValueError, con un mensaje que el modelo
            # puede leer y entender. No un NameError, no un traceback del
            # intérprete, y desde luego no un comando ejecutado.
            print(f"  [ok] {expression}\n       -> {exc}")

    print("\n" + "=" * 70)
    print("RELOJ")
    print("=" * 70)
    print(f"  local       : {get_current_time()}")
    print(f"  Asia/Tokyo  : {get_current_time(timezone='Asia/Tokyo')}")
    try:
        get_current_time(timezone="Buenos Aires")  # no es IANA válido
    except ValueError as exc:
        print(f"  zona mala   : {exc}")

    print("\n" + "=" * 70)
    print("BÚSQUEDA")
    print("=" * 70)
    for query in ["fastapi", "tool calling", "quantum blockchain"]:
        results = search(query)
        print(f"  {query!r} -> {len(results)} resultado(s)")
        for r in results:
            print(f"      {r['title']}: {r['snippet'][:60]}…")


if __name__ == "__main__":
    main()
