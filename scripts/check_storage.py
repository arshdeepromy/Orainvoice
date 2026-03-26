"""Check storage calculation for demo org."""
import asyncpg, asyncio

async def main():
    conn = await asyncpg.connect(host='postgres', port=5432, user='postgres', password='postgres', database='workshoppro')
    
    # Get demo org
    org = await conn.fetchrow("SELECT id, name, storage_quota_gb, storage_used_bytes FROM organisations WHERE name ILIKE '%demo%' LIMIT 1")
    if not org:
        org = await conn.fetchrow("SELECT id, name, storage_quota_gb, storage_used_bytes FROM organisations LIMIT 1")
    
    print(f"Org: {org['name']}")
    print(f"  storage_quota_gb: {org['storage_quota_gb']}")
    print(f"  storage_used_bytes (cached): {org['storage_used_bytes']}")
    org_id = org['id']
    
    # Check invoice_data_json
    inv_sample = await conn.fetchrow("SELECT id, invoice_data_json IS NULL as json_null, octet_length(invoice_data_json::text) as json_bytes FROM invoices WHERE org_id = $1 LIMIT 1", org_id)
    if inv_sample:
        print(f"\nSample invoice:")
        print(f"  invoice_data_json is NULL: {inv_sample['json_null']}")
        print(f"  json bytes: {inv_sample['json_bytes']}")
    
    # Total invoice JSON bytes
    inv_total = await conn.fetchrow("SELECT COUNT(*) as cnt, COALESCE(SUM(octet_length(invoice_data_json::text)), 0) as total_bytes FROM invoices WHERE org_id = $1", org_id)
    print(f"\nInvoice storage:")
    print(f"  count: {inv_total['cnt']}")
    print(f"  total bytes: {inv_total['total_bytes']}")
    
    # Customer bytes
    cust_total = await conn.fetchrow("""
        SELECT COUNT(*) as cnt, COALESCE(SUM(
            octet_length(COALESCE(first_name,'')) + octet_length(COALESCE(last_name,'')) +
            octet_length(COALESCE(email,'')) + octet_length(COALESCE(phone,'')) +
            octet_length(COALESCE(address,'')) + octet_length(COALESCE(notes,''))
        ), 0) as total_bytes FROM customers WHERE org_id = $1
    """, org_id)
    print(f"\nCustomer storage:")
    print(f"  count: {cust_total['cnt']}")
    print(f"  total bytes: {cust_total['total_bytes']}")
    
    # Check if invoice_data_json column exists and what type it is
    col = await conn.fetchrow("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='invoices' AND column_name='invoice_data_json'")
    print(f"\ninvoice_data_json column: {col}")
    
    # Check if storage_quota_gb column exists on organisations
    quota_col = await conn.fetchrow("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='organisations' AND column_name='storage_quota_gb'")
    print(f"storage_quota_gb column: {quota_col}")
    
    await conn.close()

asyncio.run(main())
