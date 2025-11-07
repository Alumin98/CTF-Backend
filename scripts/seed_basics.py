import asyncio

import app.database as database
from sqlalchemy import text


async def main() -> None:
    """Create base tables and seed a few default categories."""

    # Ensure engine is configured using current env (DATABASE_URL normalised inside database.py)
    await database.init_models()
    async with database.async_session() as session:
        await session.execute(
            text(
                "INSERT INTO categories (name, slug) VALUES "
                "('Misc','misc'),('Web','web'),('Pwn','pwn'),('Crypto','crypto') "
                "ON CONFLICT DO NOTHING;"
            )
        )
        await session.commit()
    print("Seeded default categories.")


if __name__ == "__main__":
    asyncio.run(main())
