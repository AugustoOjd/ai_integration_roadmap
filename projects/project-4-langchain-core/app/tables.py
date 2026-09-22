"""Qué tablas creó LangChain por su cuenta, y qué guardó adentro.

    uv run python -m app.tables

Nunca escribiste un CREATE TABLE. PGVector eligió el esquema, y conviene verlo:
es lo que vas a tener que entender el día que algo no recupere lo que esperabas.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

TABLAS = """
select table_name
from information_schema.tables
where table_schema = 'public'
order by table_name
"""

COLUMNAS = """
select column_name, data_type
from information_schema.columns
where table_name = :tabla
order by ordinal_position
"""


async def main() -> None:
    engine = create_async_engine(str(settings.DATABASE_URL))

    async with engine.connect() as conn:
        tablas = [r[0] for r in await conn.execute(text(TABLAS))]
        print("tablas en public:")
        for t in tablas:
            print(f"  {t}")

        for t in tablas:
            print(f"\n─── {t}")
            for col, tipo in await conn.execute(text(COLUMNAS), {"tabla": t}):
                print(f"  {col:<20} {tipo}")

        if "langchain_pg_collection" in tablas:
            print("\n─── colecciones")
            filas = await conn.execute(
                text("select name, uuid from langchain_pg_collection order by name")
            )
            for nombre, uuid in filas:
                total = await conn.scalar(
                    text(
                        "select count(*) from langchain_pg_embedding "
                        "where collection_id = :cid"
                    ),
                    {"cid": uuid},
                )
                print(f"  {nombre:<32} {total} chunks")

            # Una fila de ejemplo, sin el vector: son cientos de floats.
            print("\n─── un chunk")
            fila = (
                await conn.execute(
                    text(
                        "select id, cmetadata, left(document, 90) "
                        "from langchain_pg_embedding limit 1"
                    )
                )
            ).first()
            if fila:
                print(f"  id        {fila[0]}")
                print(f"  cmetadata {fila[1]}")
                print(f"  document  {fila[2]}…")

            # La dimensionalidad del espacio vectorial, medida.
            dim = await conn.scalar(
                text(
                    "select vector_dims(embedding) from langchain_pg_embedding limit 1"
                )
            )
            print(f"\ndimensiones del vector: {dim}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
