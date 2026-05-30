# apps/misk_real_estate/misk_real_estate/misk_real_estate/real_estate/delete_cancelled.py
"""Delete cancelled ACC-PAY-2026-00005 and its linked invoice."""
import frappe

def run():
    # Find the cancelled PE's linked invoice
    refs = frappe.db.sql(
        "SELECT reference_name FROM `tabPayment Entry Reference` WHERE parent=%s AND reference_doctype='Sales Invoice'",
        ("ACC-PAY-2026-00005",)
    )
    for r in refs:
        si_name = r[0]
        try:
            si = frappe.get_doc("Sales Invoice", si_name)
            if si.docstatus == 1:
                si.cancel()
                print(f"Cancelled Invoice: {si_name}")
            if si.docstatus == 2:
                si.delete()
                print(f"Deleted Invoice: {si_name}")
        except Exception as e:
            print(f"Error with invoice {si_name}: {e}")

    # Delete the cancelled PE
    try:
        pe = frappe.get_doc("Payment Entry", "ACC-PAY-2026-00005")
        if pe.docstatus == 2:
            pe.delete()
            print(f"Deleted Payment Entry: ACC-PAY-2026-00005")
        else:
            print(f"PE ACC-PAY-2026-00005 has docstatus {pe.docstatus}")
    except Exception as e:
        print(f"Error: {e}")

    frappe.db.commit()

    print("\n=== FINAL COUNTS (docstatus=1 only) ===")
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

if __name__ == "__main__":
    run()
