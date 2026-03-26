import asyncpg, asyncio

async def main():
    conn = await asyncpg.connect(host='postgres', port=5432, user='postgres', password='postgres', database='workshoppro')
    cols = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='parts_catalogue' ORDER BY ordinal_position")
    print("parts_catalogue columns:")
    for c in cols:
        print(f"  {c['column_name']}")
    await conn.close()

asyncio.run(main())
