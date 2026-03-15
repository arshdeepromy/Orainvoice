"""Authenticate and hit job-cards endpoint to reproduce the 502."""
import asyncio
import httpx
import os


async def check():
    base = "http://localhost:8000"
    async with httpx.AsyncClient(base_url=base) as client:
        # Login
        login_r = await client.post("/api/v1/auth/login", json={
            "email": os.environ.get("TEST_EMAIL", "admin@oraflows.co.nz"),
            "password": os.environ.get("TEST_PASSWORD", "admin123"),
            "remember_me": False,
        })
        print(f"Login: {login_r.status_code}")
        if login_r.status_code != 200:
            print(login_r.text[:500])
            return

        token = login_r.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}

        # Hit job-cards
        r = await client.get("/api/v1/job-cards", params={"limit": 20, "offset": 0}, headers=headers)
        print(f"Job cards: {r.status_code}")
        print(f"Body: {r.text[:1000]}")


asyncio.run(check())
