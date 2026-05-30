import frappe
from frappe.utils import today, add_days, flt

COMPANY = "Misk Real Estate"
BOOKINGS = [
    {"customer": "Ahmed Al Rashidi",  "building": "Al Misk Tower",      "unit": "AMT-101", "booking_date": add_days(today(), -60), "payment_plan": "Full Payment",    "booking_amount": 5000, "down_payment_percentage": 0},
    {"customer": "Fatima Al Balushi", "building": "Al Misk Tower",      "unit": "AMT-201", "booking_date": add_days(today(), -45), "payment_plan": "Installment 12M", "booking_amount": 5000, "down_payment_percentage": 50},
    {"customer": "Mohammed Al Kindi", "building": "Al Misk Residences", "unit": "AMR-A01", "booking_date": add_days(today(), -30), "payment_plan": "Installment 12M", "booking_amount": 8000, "down_payment_percentage": 40},
]

def run():
    frappe.set_user("Administrator")

    # Create bookings
    for spec in BOOKINGS:
        existing = frappe.db.exists("Property Booking", {"unit": spec["unit"]})
        if existing:
            print(f"SKIP {spec['unit']}: {existing}")
            continue
        unit_price = flt(frappe.db.get_value("Item", spec["unit"], "standard_rate"))
        b = frappe.get_doc({"doctype": "Property Booking", "company": COMPANY, **spec, "unit_price": unit_price})
        b.insert(ignore_permissions=True)
        b.submit()
        frappe.db.commit()
        print(f"CREATED {b.name} | {spec['customer']} → {spec['unit']} | {spec['payment_plan']} | {unit_price} OMR")

    # Create PDC entries
    from misk_real_estate.real_estate.doctype.property_booking.property_booking import create_pdc_entries
    all_bookings = frappe.get_all("Property Booking", filters={"docstatus": 1}, pluck="name")
    for bname in all_bookings:
        try:
            result = create_pdc_entries(bname)
            if result:
                print(f"PDC {bname}: {len(result)} entries created")
            else:
                print(f"PDC {bname}: already had entries, skipped")
        except Exception as e:
            print(f"PDC {bname} ERROR: {e}")

    # Set statuses for test coverage
    def pending(customer, limit):
        return frappe.get_all("PDC Entry", filters={"customer": customer, "status": "Pending"}, fields=["name"], order_by="cheque_date asc", limit=limit)

    def deposited(customer, limit):
        return frappe.get_all("PDC Entry", filters={"customer": customer, "status": "Deposited"}, fields=["name"], order_by="cheque_date asc", limit=limit)

    # Fatima: deposit 3, clear 2
    for e in pending("Fatima Al Balushi", 3):
        frappe.db.set_value("PDC Entry", e.name, {"status": "Deposited", "deposited_date": add_days(today(), -10)})
    for e in deposited("Fatima Al Balushi", 2):
        frappe.db.set_value("PDC Entry", e.name, {"status": "Cleared", "cleared_date": add_days(today(), -5), "gl_posted": 1})
        print(f"  Cleared {e.name}")

    # Mohammed: deposit 2, bounce 1
    for e in pending("Mohammed Al Kindi", 2):
        frappe.db.set_value("PDC Entry", e.name, {"status": "Deposited", "deposited_date": add_days(today(), -8)})
    bounced_list = deposited("Mohammed Al Kindi", 1)
    if bounced_list:
        frappe.db.set_value("PDC Entry", bounced_list[0].name, {"status": "Bounced"})
        print(f"  Bounced {bounced_list[0].name}")

    # Ahmed: deposit 2 from the 24M booking
    for e in pending("Ahmed Al Rashidi", 2):
        frappe.db.set_value("PDC Entry", e.name, {"status": "Deposited", "deposited_date": add_days(today(), -12)})
        print(f"  Deposited {e.name}")

    frappe.db.commit()
    print("Seed complete.")
