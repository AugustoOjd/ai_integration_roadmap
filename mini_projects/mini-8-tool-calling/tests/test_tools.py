"""Capa 1: las tools, sin mocks de ningún tipo.

Son funciones de Python comunes. Que se puedan testear así —sin modelo, sin
registry, sin red— es consecuencia directa de dos decisiones de diseño: el
decorador devuelve la función intacta, y las implementaciones no saben que
existe un LLM.
"""

import pytest

from app.tools.calculator import MAX_EXPRESSION_LENGTH, calculate
from app.tools.clock import get_current_time
from app.tools.search import MAX_RESULTS, MAX_SNIPPET_CHARS, search


class TestCalculateAritmetica:
    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("2 + 2", 4),
            ("4823 * 1917", 9245691),
            ("(15 + 5) / 4", 5),
            ("2 ** 10", 1024),
            ("-3 * -3", 9),
            ("17 % 5", 2),
            ("17 // 5", 3),
        ],
    )
    def test_calcula_bien(self, expression, expected):
        assert calculate(expression) == expected


class TestCalculateSeguridad:
    """Los tests que justifican que el evaluador exista.

    Cada caso es algo que `eval(expression)` habría ejecutado sin chistar. Si
    alguno de estos se pone verde por las razones equivocadas —porque devolvió
    un valor en vez de levantar— tenés un agujero de ejecución remota.
    """

    @pytest.mark.parametrize(
        "ataque",
        [
            "open('/etc/passwd').read()",  # lectura de archivos
            "__import__('os').system('id')",  # ejecución de comandos
            "__import__('os').environ['ANTHROPIC_API_KEY']",  # robo de credenciales
            "().__class__.__bases__[0].__subclasses__()",  # escape de sandbox
            "settings",  # cualquier nombre
            "[x for x in range(10)]",  # comprensiones
        ],
    )
    def test_rechaza_todo_lo_que_no_sea_aritmetica(self, ataque):
        # `ValueError` y no cualquier excepción: es el tipo que el agente sabe
        # traducir a un `tool_result` con `is_error`. Un `NameError` suelto
        # sería un fallo inesperado y se manejaría distinto.
        with pytest.raises(ValueError):
            calculate(ataque)

    @pytest.mark.parametrize("dos", ["9 ** 999999999", "2 ** (99999 * 99999)"])
    def test_acota_el_exponente(self, dos):
        """Sin este techo, estas dos líneas cuelgan el proceso.

        Es una vulnerabilidad que SOBREVIVE a la allowlist: `**` es una
        operación aritmética perfectamente legítima. La allowlist te protege de
        lo ilegítimo; lo legítimo también necesita límites.
        """
        with pytest.raises(ValueError, match="exponente"):
            calculate(dos)

    def test_acota_el_tamano_del_input(self):
        with pytest.raises(ValueError, match="larga"):
            calculate("1+" * MAX_EXPRESSION_LENGTH)

    @pytest.mark.parametrize("entrada", ["1 / 0", "2 +", "raíz cuadrada de 16"])
    def test_errores_honestos_tambien_son_controlados(self, entrada):
        with pytest.raises(ValueError):
            calculate(entrada)


class TestClock:
    def test_incluye_offset_de_zona(self):
        """Sin offset, el timestamp es ambiguo y el modelo asume lo que quiere."""
        ahora = get_current_time()
        # Un ISO con zona termina en '+HH:MM', '-HH:MM' o 'Z'.
        assert ahora[-6] in "+-" or ahora.endswith("Z")

    def test_respeta_la_zona_pedida(self):
        assert get_current_time(timezone="UTC").endswith("+00:00")

    def test_zona_invalida_da_error_util(self):
        # El mensaje lo lee el modelo, así que tiene que decirle qué formato
        # espera. Testeamos eso, no sólo que falle.
        with pytest.raises(ValueError, match="IANA"):
            get_current_time(timezone="Buenos Aires")


class TestSearch:
    def test_encuentra(self):
        assert search("fastapi")

    def test_sin_resultados_devuelve_lista_vacia(self):
        # No levanta: "no encontré nada" es un resultado válido, y el modelo
        # sabe qué hacer con una lista vacía porque el docstring se lo dice.
        assert search("quantum blockchain") == []

    def test_acota_la_cantidad(self):
        # 'a' matchea con todo. Sin el tope, esto devolvería el corpus entero
        # al contexto del modelo — y lo pagarías en cada vuelta del loop.
        assert len(search("a")) <= MAX_RESULTS

    def test_acota_el_tamano_de_cada_fragmento(self):
        for resultado in search("a"):
            assert len(resultado["snippet"]) <= MAX_SNIPPET_CHARS
