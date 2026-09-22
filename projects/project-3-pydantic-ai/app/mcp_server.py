"""Un server MCP mínimo, para tener qué consumir en la fase 11.

Corre como proceso aparte y habla por stdio. No importa nada de `app`: ese es
el punto de MCP — la tool vive afuera de tu proceso y de tu código.
"""

from fastmcp import FastMCP

mcp = FastMCP("envios")

# Datos de fantasía: lo que devolvería el sistema de la transportista.
_SEGUIMIENTO = {
    "ord_ana_1": "Entregado el 12/09 en portería.",
    "ord_ana_3": "En tránsito, llega el 24/09.",
    "ord_bruno_1": "Sin despachar.",
}


@mcp.tool
def tracking(order_id: str) -> str:
    """Estado del envío de una orden según la transportista."""
    return _SEGUIMIENTO.get(order_id, "Sin información de envío.")


if __name__ == "__main__":
    mcp.run()
