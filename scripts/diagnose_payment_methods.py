"""Diagnostic: Check what payment methods Stripe returns for PaymentIntents."""
import asyncio, json, os, sys
import httpx

async def main():
    secret_key = os.environ.get("STRIPE_KEY", "")
    connected_account = os.environ.get("CONNECTED_ACCT", "")

    if not secret_key:
        try:
            import app.main
            from app.integrations.stripe_billing import get_stripe_secret_key
            secret_key = await get_stripe_secret_key()
        except Exception as e:
            print(f"App load failed: {e}"); sys.exit(1)

    if not connected_account:
        try:
            from app.core.database import async_session_factory
            from app.modules.admin.models import Organisation
            from sqlalchemy import select
            async with async_session_factory() as db:
                async with db.begin():
                    result = await db.execute(
                        select(Organisation.name, Organisation.stripe_connect_account_id).where(
                            Organisation.stripe_connect_account_id.isnot(None)))
                    rows = result.all()
            if rows:
                for name, acct in rows:
                    print(f"Found: {name} -> {acct}")
                connected_account = rows[0][1]
        except Exception as e:
            print(f"DB error: {e}"); sys.exit(1)

    if not secret_key or not connected_account:
        print("ERROR: Need STRIPE_KEY and CONNECTED_ACCT"); sys.exit(1)

    print(f"Key: {secret_key[:12]}...{secret_key[-4:]}")
    print(f"Acct: {connected_account}")
    auth = (secret_key, "")
    hdr = {"Stripe-Account": connected_account}

    client = httpx.AsyncClient(timeout=30)
    try:
        # Test 1: No shipping
        print("\n--- Test 1: PaymentIntent WITHOUT shipping ---")
        r = await client.post("https://api.stripe.com/v1/payment_intents",
            data={"amount":"2875","currency":"nzd","automatic_payment_methods[enabled]":"true"},
            auth=auth, headers=hdr)
        pi = r.json()
        pi_id = pi.get("id","")
        print(f"  types: {pi.get('payment_method_types')}")
        print(f"  apm: {json.dumps(pi.get('automatic_payment_methods'))}")
        if pi_id:
            await client.post(f"https://api.stripe.com/v1/payment_intents/{pi_id}/cancel", auth=auth, headers=hdr)

        # Test 2: With shipping country=NZ
        print("\n--- Test 2: PaymentIntent WITH shipping country=NZ ---")
        r = await client.post("https://api.stripe.com/v1/payment_intents",
            data={"amount":"2875","currency":"nzd","automatic_payment_methods[enabled]":"true",
                  "shipping[name]":"Test","shipping[address][line1]":"123 St",
                  "shipping[address][city]":"Auckland","shipping[address][country]":"NZ",
                  "shipping[address][postal_code]":"1010"},
            auth=auth, headers=hdr)
        pi = r.json()
        pi_id = pi.get("id","")
        print(f"  types: {pi.get('payment_method_types')}")
        print(f"  apm: {json.dumps(pi.get('automatic_payment_methods'))}")
        if pi_id:
            await client.post(f"https://api.stripe.com/v1/payment_intents/{pi_id}/cancel", auth=auth, headers=hdr)

        # Test 3: With shipping country=New Zealand (full name)
        print("\n--- Test 3: PaymentIntent WITH shipping country='New Zealand' ---")
        r = await client.post("https://api.stripe.com/v1/payment_intents",
            data={"amount":"2875","currency":"nzd","automatic_payment_methods[enabled]":"true",
                  "shipping[name]":"Test","shipping[address][line1]":"123 St",
                  "shipping[address][city]":"Auckland","shipping[address][country]":"New Zealand",
                  "shipping[address][postal_code]":"1010"},
            auth=auth, headers=hdr)
        pi = r.json()
        pi_id = pi.get("id","")
        if r.status_code != 200:
            print(f"  ERROR: {r.status_code} - {r.text[:300]}")
        else:
            print(f"  types: {pi.get('payment_method_types')}")
            print(f"  apm: {json.dumps(pi.get('automatic_payment_methods'))}")
        if pi_id:
            await client.post(f"https://api.stripe.com/v1/payment_intents/{pi_id}/cancel", auth=auth, headers=hdr)

        # Test 4: With shipping country="" (empty)
        print("\n--- Test 4: PaymentIntent WITH shipping country='' (empty) ---")
        r = await client.post("https://api.stripe.com/v1/payment_intents",
            data={"amount":"2875","currency":"nzd","automatic_payment_methods[enabled]":"true",
                  "shipping[name]":"Test","shipping[address][line1]":"N/A",
                  "shipping[address][city]":"","shipping[address][country]":"",
                  "shipping[address][postal_code]":""},
            auth=auth, headers=hdr)
        pi = r.json()
        pi_id = pi.get("id","")
        if r.status_code != 200:
            print(f"  ERROR: {r.status_code} - {r.text[:300]}")
        else:
            print(f"  types: {pi.get('payment_method_types')}")
        if pi_id:
            await client.post(f"https://api.stripe.com/v1/payment_intents/{pi_id}/cancel", auth=auth, headers=hdr)

        # Test 5: Check existing invoice PI
        print("\n--- Test 5: Existing invoice PaymentIntents ---")
        try:
            from app.modules.invoices.models import Invoice
            from sqlalchemy import select as sel
            from app.core.database import async_session_factory
            async with async_session_factory() as db:
                async with db.begin():
                    result = await db.execute(
                        sel(Invoice.invoice_number, Invoice.stripe_payment_intent_id).where(
                            Invoice.stripe_payment_intent_id.isnot(None)
                        ).order_by(Invoice.created_at.desc()).limit(3))
                    inv_rows = result.all()
            for inv_num, pi_id in inv_rows:
                r = await client.get(f"https://api.stripe.com/v1/payment_intents/{pi_id}",
                    auth=auth, headers=hdr)
                if r.status_code == 200:
                    pi = r.json()
                    print(f"  {inv_num} ({pi_id}): types={pi.get('payment_method_types')}, shipping={json.dumps(pi.get('shipping'))}")
                else:
                    print(f"  {inv_num} ({pi_id}): ERROR {r.status_code}")
        except Exception as e:
            print(f"  Skipped: {e}")

        # Test 6: Payment Method Configuration
        print("\n--- Test 6: Payment Method Configuration ---")
        r = await client.get("https://api.stripe.com/v1/payment_method_configurations",
            auth=auth, headers=hdr)
        if r.status_code == 200:
            for cfg in r.json().get("data", []):
                print(f"  Config {cfg['id']} (default={cfg.get('is_default')})")
                for m in ["card","klarna","afterpay_clearpay","apple_pay","google_pay","link","zip"]:
                    d = cfg.get(m, {})
                    if d:
                        print(f"    {m}: available={d.get('available')}, pref={d.get('display_preference',{}).get('value')}")
        else:
            print(f"  ERROR: {r.status_code}")

    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
