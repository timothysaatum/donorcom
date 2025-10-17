import sqlite3
from datetime import date, timedelta

# Connect to SQLite database
conn = sqlite3.connect("db.sqlite3")
cursor = conn.cursor()

# Get total distributions
cursor.execute("SELECT COUNT(*) FROM blood_distributions")
total = cursor.fetchone()[0]
print(f"\n=== Total distributions: {total} ===\n")

if total > 0:
    # Get recent distributions
    cursor.execute(
        """
        SELECT id, dispatched_from_id, dispatched_to_id, date_delivered, 
               status, quantity, blood_product, created_at
        FROM blood_distributions
        ORDER BY created_at DESC
        LIMIT 5
    """
    )

    rows = cursor.fetchall()
    print(f"Recent {len(rows)} distributions:")
    print("-" * 100)
    for r in rows:
        print(f"ID: {r[0][:8]}... | From: {r[1][:8]}... | To: {r[2][:8]}...")
        print(f"  Delivered: {r[3]} | Status: {r[4]} | Qty: {r[5]} | Product: {r[6]}")
        print(f"  Created: {r[7]}")
        print("-" * 100)

    # Check delivered in last 7 days
    seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
    cursor.execute(
        """
        SELECT COUNT(*) FROM blood_distributions
        WHERE date_delivered IS NOT NULL
        AND DATE(date_delivered) >= ?
    """,
        (seven_days_ago,),
    )
    recent_delivered = cursor.fetchone()[0]
    print(f"\nDelivered in last 7 days: {recent_delivered}")

    # Check by status
    print("\nBy status:")
    for status in ["pending_receive", "in transit", "delivered", "cancelled"]:
        cursor.execute(
            "SELECT COUNT(*) FROM blood_distributions WHERE status = ?", (status,)
        )
        count = cursor.fetchone()[0]
        print(f"  {status}: {count}")

conn.close()
