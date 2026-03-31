#!/usr/bin/env python3
"""Check Stripe config in database."""
import asyncio
import asyncpg
import json

async def check():
    conn = await asyncpg.connect(
        user="postgres",
        password="postgres",
        database="workshoppro",
        host="postgres"
    )
    row = await conn.fetchrow(
        "SELECT config_encrypted FROM integration_configs WHERE name = $1",
        "stripe"
    )
    if row:
        encrypted = row["config_encrypted"]
        print("Encrypted data length:", len(encrypted) if encrypted else 0)
        from app.core.encryption import envelope_decrypt_str
        try:
            decrypted = envelope_decrypt_str(encrypted)
            config = json.loads(decrypted)
            secret_key = config.get("secret_key", "")
            if secret_key:
                print("Key prefix:", secret_key[:15])
                print("Key suffix:", secret_key[-10:])
                print("Key length:", len(secret_key))
                # Check if it looks reversed
                reversed_key = secret_key[::-1]
                print("Reversed prefix:", reversed_key[:15])
            else:
                print("No secret_key in config")
                print("Config keys:", list(config.keys()))
        except Exception as e:
            print("Decryption error:", type(e).__name__, str(e))
    else:
        print("No stripe config found")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
