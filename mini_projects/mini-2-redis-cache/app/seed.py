import asyncio

from sqlalchemy import select

from app.database import async_session, init_db
from app.models.note import Note
from app.services import cache

SAMPLE_NOTES = [
    {"title": "Welcome", "content": "This is your first note."},
    {"title": "FastAPI", "content": "FastAPI makes building APIs fast and fun."},
    {"title": "Redis Cache", "content": "This mini adds a caching layer with Redis."},
]


async def seed() -> None:
    await init_db()  # make sure tables exist before inserting

    async with async_session() as session:
        # Idempotency check: skip if the table already has any rows, so running
        # this twice (or after a plain `docker-compose down`/`up`) never duplicates data
        result = await session.execute(select(Note.id).limit(1))
        if result.scalar_one_or_none() is not None:
            print("notes table already has data — skipping seed")
            return

        session.add_all(Note(**data) for data in SAMPLE_NOTES)
        await session.commit()

    # In case the app was already running and cached an (empty) list before this ran
    await cache.invalidate()
    print(f"seeded {len(SAMPLE_NOTES)} notes")


if __name__ == "__main__":
    asyncio.run(seed())
