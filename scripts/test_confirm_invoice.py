"""
Test script: Simulates the "Confirm & Invoice" button flow end-to-end.

1. Logs in as demo user
2. Creates a test booking (scheduled)
3. Calls POST /bookings/{id}/convert?target=invoice
4. Verifies the response
5. Cleans up (optional)

Run: docker compose exec -w /app app python scripts/test_confirm_invoice.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = "http://localhost:8000/api/v1"
EMAIL = "demo@orainvoice.com"
PASSWORD = "demo123"


def main():
    client = httpx.Client(base_url=BASE, timeout=15.0)

    # Step 1: Login
    print("=" * 60)
    print("STEP 1: Login")
    r = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD, "remember_me": False})
    print(f"  Status: {r.status_code}")
    if r.status_code != 200:
        print(f"  FAILED: {r.text[:300]}")
        return
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"  OK — got access token")

    # Step 2: List scheduled bookings
    print("\nSTEP 2: List scheduled bookings")
    r = client.get("/bookings", params={"view": "month", "date": "2026-03-16T00:00:00Z"}, headers=headers)
    print(f"  Status: {r.status_code}")
    if r.status_code != 200:
        print(f"  FAILED: {r.text[:300]}")
        return
    bookings = r.json().get("bookings", [])
    scheduled = [b for b in bookings if b["status"] == "scheduled"]
    print(f"  Total bookings: {len(bookings)}, Scheduled: {len(scheduled)}")

    if not scheduled:
        # Create a test booking
        print("\n  No scheduled bookings — creating a test one...")
        # First get a customer
        r = client.get("/customers", params={"limit": 1}, headers=headers)
        if r.status_code != 200 or not r.json().get("items"):
            print(f"  FAILED to get customer: {r.status_code} {r.text[:200]}")
            return
        customer = r.json()["items"][0]
        cust_id = customer["id"]
        print(f"  Using customer: {customer.get('first_name')} {customer.get('last_name')} ({cust_id})")

        r = client.post("/bookings", json={
            "customer_id": cust_id,
            "service_type": "Test Service",
            "scheduled_at": "2026-03-20T10:00:00Z",
            "duration_minutes": 60,
            "send_email_confirmation": False,
        }, headers=headers)
        print(f"  Create booking status: {r.status_code}")
        if r.status_code != 200:
            print(f"  FAILED: {r.text[:300]}")
            return
        booking_id = r.json()["booking"]["id"]
        print(f"  Created booking: {booking_id}")
    else:
        booking = scheduled[0]
        booking_id = booking["id"]
        print(f"  Using booking: {booking_id} ({booking.get('customer_name')} — {booking.get('service_type')})")

    # Step 3: Convert booking to invoice (the "Confirm & Invoice" button)
    print(f"\nSTEP 3: POST /bookings/{booking_id}/convert?target=invoice")
    r = client.post(
        f"/bookings/{booking_id}/convert",
        params={"target": "invoice"},
        headers=headers,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.text[:500]}")

    if r.status_code == 200:
        data = r.json()
        print(f"\n  SUCCESS!")
        print(f"  booking_id:  {data.get('booking_id')}")
        print(f"  created_id:  {data.get('created_id')}")
        print(f"  target:      {data.get('target')}")
        print(f"  message:     {data.get('message')}")
        print(f"\n  Frontend would navigate to: /invoices/{data.get('created_id')}/edit")
    else:
        print(f"\n  FAILED!")
        print(f"  The frontend would show error toast: {r.json().get('detail', r.text[:200])}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
