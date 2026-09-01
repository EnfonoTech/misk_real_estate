"""
One-off: re-syncs Property Booking.customer_name (a fetch_from snapshot of
Customer.customer_name) to match the Customer master, wherever they've
drifted apart. Happens because customer_name isn't allow_on_submit — once a
booking is submitted, nothing re-fetches it, so if the Customer is later
renamed (Customer.customer_name changed — which, with cust_master_name set
to "Customer Name", also renames the Customer document itself, so the
booking's own `customer` Link field already correctly follows the rename;
only this plain cached Data field is left behind), the booking keeps
showing the OLD name forever.

Scoped to Property Booking only, on purpose — not Reservation/Quotation or
any other doctype with a similar fetched customer_name field.

SAFE BY DEFAULT: run() only PREVIEWS what it would change, writes nothing.
Pass apply=True to actually perform the correction.

Usage:
    bench --site <site> execute misk_real_estate.utils.fix_stale_customer_name.run
    # review the printed list, then:
    bench --site <site> execute misk_real_estate.utils.fix_stale_customer_name.run --kwargs "{'apply': True}"
"""

import frappe


def run(apply=False):
    rows = frappe.db.sql("""
        SELECT pb.name AS booking, pb.customer_name AS stale_name, c.customer_name AS correct_name
        FROM `tabProperty Booking` pb
        INNER JOIN `tabCustomer` c ON c.name = pb.customer
        WHERE pb.customer_name != c.customer_name
    """, as_dict=True)

    print(f"{len(rows)} Property Bookings with a stale customer_name")
    for r in rows[:50]:
        print(f"  {r.booking}: has '{r.stale_name}' -> master says '{r.correct_name}'")

    if not apply:
        print("\nDRY RUN ONLY — nothing written. Re-run with apply=True to perform the correction.")
        return

    for r in rows:
        frappe.db.set_value("Property Booking", r.booking, "customer_name", r.correct_name, update_modified=False)

    frappe.db.commit()
    print(f"\nCorrected {len(rows)} Property Bookings")
