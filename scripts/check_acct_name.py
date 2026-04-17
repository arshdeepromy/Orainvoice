"""Check what name fields the connected Stripe account has."""
import asyncio, json, asyncpg, httpx

async def check():
    conn = await asyncpg.connect(host="postgres", port=5432, user="postgres", password="postgres", database="workshoppro")
    acct_id = await conn.fetchval("SELECT stripe_connect_account_id FROM organisations WHERE name = 'Demo Workshop'")
    config_enc = await conn.fetchval("SELECT config_encrypted FROM integration_configs WHERE name = 'stripe'")
    from app.core.encryption import envelope_decrypt_str
    sk = json.loads(envelope_decrypt_str(config_enc)).get("secret_key", "")

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.stripe.com/v1/accounts/{acct_id}", auth=(sk, ""))
        data = resp.json()

    bp = data.get("business_profile", {})
    settings = data.get("settings", {})
    print(f"business_profile.name: {bp.get('name')!r}")
    print(f"business_profile.support_email: {bp.get('support_email')!r}")
    print(f"settings.dashboard.display_name: {settings.get('dashboard', {}).get('display_name')!r}")
    print(f"business_type: {data.get('business_type')!r}")
    print(f"company.name: {data.get('company', {}).get('name')!r}")
    print(f"individual.first_name: {data.get('individual', {}).get('first_name')!r}")
    print(f"email: {data.get('email')!r}")

    await conn.close()

asyncio.run(check())
