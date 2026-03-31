#!/usr/bin/env python3
"""Test Stripe API key directly with v15 API."""
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
                
                # Check stripe version
                print("Stripe version:", stripe.VERSION)
                
                # In stripe v15, you need to use a client
                try:
                    client = stripe.StripeClient(secret_key)
                    balance = client.balance.retrieve()
                    print("SUCCESS with client!")
                    print("Balance object type:", type(balance))
                    print("Balance:", balance)
                except Exception as e1:
                    print("Client method error:", type(e1).__name__, str(e1))
                    
                    # Try the old way
                    try:
                        stripe.api_key = secret_key
                        balance = stripe.Balance.retrieve()
                        print("SUCCESS with old method!")
                        print("Balance:", balance)
                    except Exception as e2:
                        print("Old method error:", type(e2).__name__, str(e2))
            else:
                print("No secret_key in config")
        except Exception as e:
            print("Decryption error:", type(e).__name__, str(e))
    else:
        print("No stripe config found")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(test())
