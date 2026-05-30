# apps/misk_real_estate/misk_real_estate/misk_real_estate/real_estate/verify_counts.py
"""Verify final PDC counts with docstatus filter."""
import frappe

def run():
    print("=== ACTIVE (docstatus=1) PDCs for Fatima ===")
    for s in ["Cleared", "Pending Deposit", "Deposited", "Bounced"]:
        c = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabPayment Entry` WHERE party=%s AND cheque_status=%s AND docstatus=1 AND mode_of_payment='Cheque'",
            ("Fatima Al Zadjali", s)
        )[0][0]
        print(f"  {s}: {c}")

    total = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabPayment Entry` WHERE party=%s AND docstatus=1 AND mode_of_payment='Cheque'",
        ("Fatima Al Zadjali",)
    )[0][0]
    print(f"  TOTAL: {total}")

    # Cancel extra
    if total > 24:
        # Find one to cancel
        rows = frappe.db.sql(
            "SELECT name FROM `tabPayment Entry` WHERE party=%s AND cheque_status='Pending Deposit' AND docstatus=1 AND mode_of_payment='Cheque' ORDER BY creation ASC LIMIT 1",
            ("Fatima Al Zadjali",)
        )
        if rows:
            pe_name = rows[0][0]
            pe = frappe.get_doc("Payment Entry", pe_name)
            pe.cancel()
            frappe.db.commit()
            print(f"\nCancelled: {pe_name}")

            # Recount
            for s in ["Cleared", "Pending Deposit"]:
                c = frappe.db.sql(
                    "SELECT COUNT(*) FROM `tabPayment Entry` WHERE party=%s AND cheque_status=%s AND docstatus=1 AND mode_of_payment='Cheque'",
                    ("Fatima Al Zadjali", s)
                )[0][0]
                print(f"  {s}: {c}")
            total = frappe.db.sql(
                "SELECT COUNT(*) FROM `tabPayment Entry` WHERE party=%s AND docstatus=1 AND mode_of_payment='Cheque'",
                ("Fatima Al Zadjali",)
            )[0][0]
            print(f"  TOTAL: {total}")

if __name__ == "__main__":
    run()
