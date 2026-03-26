import asyncpg, asyncio

async def main():
    conn = await asyncpg.connect(host='postgres', port=5432, user='postgres', password='postgres', database='workshoppro')
    cols = await conn.fetch("""
        SELECT table_name, column_name, character_maximum_length
        FROM information_schema.columns
        WHERE column_name = 'description'
        AND character_maximum_length <= 500
        AND table_schema = 'public'
        ORDER BY table_name
    """)
    for c in cols:
        print(f"  {c['table_name']}.{c['column_name']}: VARCHAR({c['character_maximum_length']})")
    await conn.close()

asyncio.run(main())
