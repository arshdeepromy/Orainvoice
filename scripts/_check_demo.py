import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect(host="postgres", port=5432, user="postgres", password="postgres", database="workshoppro")
    # Check if demo user has a hashed password
    rows = await conn.fetch("SELECT email, role, org_id, is_active FROM users WHERE email = 'demo@orainvoice.com'")
    for r in rows:
        print("email:", r["email"], "| role:", r["role"], "| org_id:", r["org_id"], "| active:", r["is_active"])
    
    # Try the nerdytech user too
    rows2 = await conn.fetch("SELECT email, role, org_id, is_active FROM users WHERE email = 'admin@nerdytech.co.nz'")
    for r in rows2:
        print("email:", r["email"], "| role:", r["role"], "| org_id:", r["org_id"], "| active:", r["is_active"])
    
    await conn.close()

asyncio.run(check())
