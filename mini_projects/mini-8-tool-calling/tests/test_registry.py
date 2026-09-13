"""Capa 1b: el registry, también sin modelo.

Derivar schemas y validar dicts es determinístico y local. Conviene testearlo
de cerca porque es lo que el modelo lee en CADA request: un schema mal derivado
no da error, da un agente que se porta raro.
"""

import pytest

from app.tools.registry import (
    InvalidToolInputError,
    ToolRegistry,
    UnknownToolError,
    registry,
)


class TestSchemaDerivado:
    def test_las_tres_tools_estan_registradas(self):
        nombres = {param["name"] for param in registry.to_params()}
        assert nombres == {"calculate", "get_current_time", "search"}

    def test_la_description_sale_del_docstring(self):
        param = next(p for p in registry.to_params() if p["name"] == "calculate")
        # El docstring ES el prompt. Si alguien lo vacía "porque es obvio", el
        # modelo pierde la única guía que tiene para saber cuándo usar la tool.
        assert "aritmética" in param["description"]

    def test_el_parametro_requerido_aparece_en_required(self):
        param = next(p for p in registry.to_params() if p["name"] == "calculate")
        assert param["input_schema"]["required"] == ["expression"]

    def test_el_parametro_opcional_no_aparece_en_required(self):
        """`timezone` tiene default en la firma, así que es opcional en el schema.

        Esa correspondencia sale sola del registry; es justo lo que en
        `toolbox.py` había que sostener a mano en dos lugares.
        """
        param = next(p for p in registry.to_params() if p["name"] == "get_current_time")
        assert "timezone" not in param["input_schema"].get("required", [])

    def test_prohibe_campos_extra(self):
        """`additionalProperties: false` es lo que exige `strict: true`."""
        for param in registry.to_params():
            assert param["input_schema"]["additionalProperties"] is False


class TestValidacion:
    def test_ejecuta_y_devuelve_string(self):
        # Siempre string: es lo que exige el bloque `tool_result`. Devolver un
        # float es el 400 que nos comimos con el `tool_runner` en la Fase 8.
        assert registry.execute("calculate", {"expression": "2+2"}) == "4.0"

    def test_rechaza_campo_inventado(self):
        # El modelo agrega un parámetro que le pareció razonable. Sin el
        # `extra="forbid"`, esto llegaría como `TypeError: unexpected keyword`.
        with pytest.raises(InvalidToolInputError):
            registry.execute("calculate", {"expression": "2+2", "precision": 4})

    def test_rechaza_requerido_faltante(self):
        with pytest.raises(InvalidToolInputError):
            registry.execute("calculate", {})

    def test_tool_alucinada(self):
        with pytest.raises(UnknownToolError) as exc:
            registry.execute("send_email", {"to": "x@y.com"})
        # El mensaje lista las tools disponibles, y eso no es cosmético: lo lee
        # el modelo y le permite corregirse en la vuelta siguiente.
        assert "calculate" in str(exc.value)


class TestContratoDelDecorador:
    def test_exige_docstring(self):
        propio = ToolRegistry()

        with pytest.raises(ValueError, match="docstring"):

            @propio.tool
            def sin_docs(x: int) -> int:
                return x

    def test_exige_tipos(self):
        propio = ToolRegistry()

        with pytest.raises(TypeError, match="tipo"):

            @propio.tool
            def sin_tipos(x) -> int:
                """Una tool sin anotación en su parámetro."""
                return x

    def test_devuelve_la_funcion_intacta(self):
        """Por esto los tests de `test_tools.py` pueden llamar a las tools directo."""
        propio = ToolRegistry()

        @propio.tool
        def duplicar(n: int) -> int:
            """Duplica un número."""
            return n * 2

        assert duplicar(21) == 42
