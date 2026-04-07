"""Reset demo org_admin password."""
import asyncio
from app.core.database import async_session_factory
from app.modules.auth.password import hash_password
from sqlalchemy import text


async def main():
    async with async_session_factory() as db:
        result = await db.execute(
            text("SELECT id, email, role, is_active, failed_login_count, locked_until FROM users WHERE role = 'org_admin' LIMIT 10")
        )
        rows = result.fetchall()
        for r in rows:
            print(f"org_admin: id={r[0]}, email={r[1]}, active={r[3]}, failed={r[4]}, locked={r[5]}")
            pw_hash = hash_password("Demo123!")
            await db.execute(
                text("UPDATE users SET password_hash = :pw, is_active = true, is_email_verified = true, failed_login_count = 0, locked_until = NULL WHERE id = :uid"),
                {"pw": pw_hash, "uid": r[0]},
            )
            await db.execute(
                text("DELETE FROM user_mfa_methods WHERE user_id = :uid"),
                {"uid": r[0]},
            )
        await db.commit()
        print("All org_admin passwords reset to Demo123!")


asyncio.run(main())
