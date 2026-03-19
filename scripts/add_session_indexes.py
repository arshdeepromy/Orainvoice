"""Add missing indexes to sessions table and clean up stale sessions."""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import os

async def main():
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        # Add indexes
        print("Creating indexes...")
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sessions_refresh_token_hash "
            "ON sessions (refresh_token_hash)"
        ))
        print("  idx_sessions_refresh_token_hash ✓")

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sessions_family_id "
            "ON sessions (family_id)"
        ))
        print("  idx_sessions_family_id ✓")

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id "
            "ON sessions (user_id)"
        ))
        print("  idx_sessions_user_id ✓")

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at "
            "ON sessions (expires_at)"
        ))
        print("  idx_sessions_expires_at ✓")

        # Clean up revoked and expired sessions
        result = await conn.execute(text(
            "DELETE FROM sessions WHERE is_revoked = true OR expires_at < now()"
        ))
        print(f"\nCleaned up {result.rowcount} stale sessions")

        # Final count
        count = (await conn.execute(text("SELECT count(*) FROM sessions"))).scalar()
        print(f"Remaining active sessions: {count}")

    await engine.dispose()

asyncio.run(main())
