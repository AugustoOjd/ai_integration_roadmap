"""Punto de entrada de Alembic: de dónde saca la URL y contra qué compara.

Importa `app.core.models` para que todas las clases queden registradas en
`Base.metadata` antes del autogenerate. Un modelo que no se importe acá es un
modelo que el autogenerate no ve y una tabla que la migración no crea.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# La URL sale del .env vía settings, no de alembic.ini: un solo lugar con
# credenciales. str() porque PostgresDsn es un objeto Url, no un string.
config.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL))

# Lo que el autogenerate compara contra la base.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse, para revisarlo o aplicarlo a mano."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica las migraciones contra la base."""
    # NullPool: este proceso corre una migración y se muere, no tiene sentido
    # mantener un pool abierto.
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detecta cambios de tipo de una columna existente. Apagado por
            # default, y sin esto un String(64) que pasa a String(128) no genera
            # migración.
            compare_type=True,
            # Ídem para cambios de server_default.
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
