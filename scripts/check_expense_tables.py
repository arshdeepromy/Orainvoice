import asyncpg, asyncio

async def main():
    conn = await asyncpg.connect(host='postgres', port=5432, user='postgres', password='postgres', database='workshoppro')
    tables = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    for t in tables:
        name = t['tablename']
        if 'mileage' in name or 'expense' in name:
            print(name)
    # Check expenses columns
    cols = await conn.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='expenses' ORDER BY ordinal_position")
    print('\nexpenses columns:')
    for c in cols:
        print(f"  {c['column_name']}: {c['data_type']}")
    await conn.close()

asyncio.run(main())
