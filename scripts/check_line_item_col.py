import asyncpg, asyncio

async def main():
    conn = await asyncpg.connect(host='postgres', port=5432, user='postgres', password='postgres', database='workshoppro')
    cols = await conn.fetch("""
        SELECT column_name, character_maximum_length, data_type
        FROM information_schema.columns
        WHERE table_name = 'line_items'
        ORDER BY ordinal_position
    """)
    for c in cols:
        print(f"  {c['column_name']}: {c['data_type']}({c['character_maximum_length']})")
    await conn.close()

asyncio.run(main())
