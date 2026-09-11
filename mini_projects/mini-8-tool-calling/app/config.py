from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Todo lo que cambia entre entornos (local, CI, prod).

    Cada campo se llena desde una variable de entorno con el mismo nombre. Los
    que tienen default son preferencias; el que NO tiene default es un requisito.
    """

    # La credencial. `SecretStr` no la encripta ni la protege: lo único que hace
    # es que su `repr()` sea `SecretStr('**********')`. Eso importa más de lo que
    # parece, porque los objetos de settings terminan impresos sin querer en
    # trazas de excepciones, logs de debug y reportes de error de terceros.
    # Para usarla hay que pedirla explícitamente con `.get_secret_value()`, y
    # esa fricción es el punto: filtrarla pasa a ser una decisión, no un descuido.
    #
    # Sin default a propósito: si falta, Pydantic tira ValidationError al
    # importar este módulo y el proceso no arranca. Es el comportamiento que
    # querés — un arranque que falla es mucho más barato de diagnosticar que una
    # app viva que devuelve 401 en el primer request de un usuario real.
    ANTHROPIC_API_KEY: SecretStr

    # Haiku 4.5: barato ($1/$5 por millón de tokens in/out) y rápido, que es lo
    # que importa en un mini donde cada request son VARIAS llamadas al modelo.
    #
    # Tres particularidades de Haiku 4.5 respecto de los modelos más nuevos, que
    # conviene tener presentes antes de chocarlas:
    #   - Contexto de 200K, no 1M. El historial de un loop de tools crece rápido.
    #   - Thinking no es adaptativo: si lo quisieras, va explícito como
    #     `thinking={"type": "enabled", "budget_tokens": N}`. Acá va apagado.
    #   - `output_config.effort` no existe para este modelo: da error.
    ANTHROPIC_MODEL: str = "claude-haiku-4-5"

    # Techo de tokens GENERADOS por respuesta. No es un presupuesto de costo: es
    # un cuchillo. Si el modelo lo toca, la respuesta se corta donde sea que
    # estuviera y `stop_reason` vuelve como "max_tokens".
    #
    # 4096 es deliberadamente bajo y alcanza de sobra: los turnos de este mini
    # son cortos (un bloque `tool_use` son unos pocos tokens de JSON). Para
    # generación de texto largo el default sano ronda los 16000.
    ANTHROPIC_MAX_TOKENS: int = 4096

    # Cuánto esperamos UNA llamada al modelo antes de abandonarla.
    #
    # El default del SDK son 10 minutos, pensado para trabajos largos. Detrás de
    # un endpoint HTTP eso es un bug esperando: un request colgado ocupa un
    # worker de uvicorn los 10 minutos enteros. 30s es un presupuesto realista
    # para un turno de Haiku, y hace que un problema de red se manifieste como
    # un error rápido en vez de como una app que "se puso lenta".
    ANTHROPIC_TIMEOUT: float = 30.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Una sola instancia, importada por todos los módulos. Se construye al importar:
# si falta la API key, el proceso muere al arrancar y no a mitad de una request.
settings = Settings()
