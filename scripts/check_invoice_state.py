"""Check invoice state and payment records for debugging."""
import asyncio
from sqlalchemy import text
from app.core.database import async_session_factory


async def check():
    async with async_session_factory() as db:
        async with db.begin():
            row = await db.execute(text(
                "SELECT id, invoice_number, status, balance_due, amount_paid, "
                "stripe_payment_intent_id, payment_page_url, "
                "invoice_data_json->>'payment_gateway' as gateway "
                "FROM invoices WHERE invoice_number = 'dem-0005'"
            ))
            r = row.fetchone()
            if r:
                print(f"Invoice: {r.invoice_number}")
                print(f"  Status: {r.status}")
                print(f"  Balance Due: {r.balance_due}")
                print(f"  Amount Paid: {r.amount_paid}")
                print(f"  PI ID: {r.stripe_payment_intent_id}")
                print(f"  Gateway: {r.gateway}")
                print(f"  URL: {r.payment_page_url}")

                pay_row = await db.execute(text(
                    "SELECT COUNT(*) FROM payments WHERE invoice_id = :iid"
                ), {"iid": r.id})
                cnt = pay_row.scalar()
                print(f"  Payments recorded: {cnt}")
            else:
                print("Invoice dem-0005 not found")

            # Check webhook logs
            wh_row = await db.execute(text(
                "SELECT COUNT(*) FROM audit_log WHERE action LIKE '%webhook%' "
                "AND created_at > NOW() - INTERVAL '1 hour'"
            ))
            wh_cnt = wh_row.scalar()
            print(f"\nWebhook audit entries (last hour): {wh_cnt}")


asyncio.run(check())
