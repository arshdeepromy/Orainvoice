"""Reset or create the global admin account."""
import asyncio
from app.core.database import async_session_factory
from app.modules.auth.password import hash_password
from sqlalchemy import text


async def main():
    async with async_session_factory() as db:
        # Check if admin@orainvoice.com exists
        result = await db.execute(
            text("SELECT id, email, role, is_active, is_email_verified FROM users WHERE email = 'admin@orainvoice.com'")
        )
        row = result.first()

        if row:
            print(f"Found: id={row[0]}, role={row[2]}, active={row[3]}, verified={row[4]}")
            # Reset password and unlock
            pw_hash = hash_password("Admin123!")
            await db.execute(
                text("UPDATE users SET password_hash = :pw, is_active = true, is_email_verified = true, failed_login_count = 0, locked_until = NULL WHERE email = 'admin@orainvoice.com'"),
                {"pw": pw_hash},
            )
            # Also delete any MFA methods so login doesn't require MFA
            await db.execute(
                text("DELETE FROM user_mfa_methods WHERE user_id = :uid"),
                {"uid": row[0]},
            )
            await db.commit()
            print("Password reset to Admin123! — MFA cleared, account unlocked")
        else:
            print("admin@orainvoice.com NOT FOUND")
            # Check for any global_admin
            result2 = await db.execute(
                text("SELECT id, email, role, is_active FROM users WHERE role = 'global_admin' LIMIT 5")
            )
            rows = result2.fetchall()
            if rows:
                for r in rows:
                    print(f"  global_admin: id={r[0]}, email={r[1]}, active={r[3]}")
                # Reset the first one
                uid = rows[0][0]
                email = rows[0][1]
                pw_hash = hash_password("Admin123!")
                await db.execute(
                    text("UPDATE users SET password_hash = :pw, is_active = true, is_email_verified = true, failed_login_count = 0, locked_until = NULL WHERE id = :uid"),
                    {"pw": pw_hash, "uid": uid},
                )
                await db.execute(
                    text("DELETE FROM user_mfa_methods WHERE user_id = :uid"),
                    {"uid": uid},
                )
                await db.commit()
                print(f"Reset password for {email} to Admin123!")
            else:
                print("No global_admin found — creating one")
                pw_hash = hash_password("Admin123!")
                await db.execute(
                    text("INSERT INTO users (email, password_hash, role, is_active, is_email_verified) VALUES ('admin@orainvoice.com', :pw, 'global_admin', true, true)"),
                    {"pw": pw_hash},
                )
                await db.commit()
                print("Created admin@orainvoice.com with password Admin123!")

        # Also reset the demo org_admin
        result3 = await db.execute(
            text("SELECT id, email, role, is_active, failed_login_count, locked_until FROM users WHERE email = 'demo@workshop.co.nz'")
        )
        demo = result3.first()
        if demo:
            print(f"\nDemo user: id={demo[0]}, role={demo[2]}, active={demo[3]}, failed={demo[4]}, locked={demo[5]}")
            pw_hash = hash_password("Demo123!")
            await db.execute(
                text("UPDATE users SET password_hash = :pw, is_active = true, is_email_verified = true, failed_login_count = 0, locked_until = NULL WHERE email = 'demo@workshop.co.nz'"),
                {"pw": pw_hash},
            )
            await db.execute(
                text("DELETE FROM user_mfa_methods WHERE user_id = :uid"),
                {"uid": demo[0]},
            )
            await db.commit()
            print("Demo password reset to Demo123! — MFA cleared, account unlocked")


asyncio.run(main())
