#!/usr/bin/env python3
"""Test Stripe API key directly."""
import asyncio
import asyncpg
import json

async def test():
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
        from app.core.encryption import envelope_decrypt_str
        try:
            decrypted = envelope_decrypt_str(encrypted)
            config = json.loads(decrypted)
            secret_key = config.get("secret_key", "")
            if secret_key:
                print("Testing key:", secret_key[:15] + "...")
                import stripe
                stripe.api_key = secret_key
                try:
                    balance = stripe.Balance.retrieve()
                    print("SUCCESS! Balance object:", balance.get("object"))
                    print("Available:", balance.get("available"))
                except stripe.error.AuthenticationError as e:
                    print("AUTH ERROR:", str(e))
                except stripe.error.APIConnectionError as e:
                    print("CONNECTION ERROR:", str(e))
                except Exception as e:
                    print("ERROR:", type(e).__name__, str(e))
            else:
                print("No secret_key in config")
        except Exception as e:
            print("Decryption error:", type(e).__name__, str(e))
    else:
        print("No stripe config found")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(test())
