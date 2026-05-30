# apps/misk_real_estate/misk_real_estate/misk_real_estate/real_estate/cancel_one_pdc.py
"""Cancel one pending PDC to get exactly 24 total."""
import frappe

def run():
    # Cancel one pending to get 19 pending instead of 20
    target = "ACC-PAY-2026-00005"  # from first attempt
    try:
        pe = frappe.get_doc("Payment Entry", target)
        if pe.docstatus == 1:
            pe.cancel()
            print(f"Cancelled: {target}")
        else:
            print(f"{target} already cancelled/draft")
    except Exception as e:
        print(f"Error: {e}")

    frappe.db.commit()
    print("\n=== FINAL ===")
    for s in ["Cleared", "Pending Deposit", "Deposited", "Bounced"]:
        c = frappe.db.count("Payment Entry", {"party": "Fatima Al Zadjali", "cheque_status": s})
        print(f"  {s}: {c}")
    print(f"  TOTAL: {frappe.db.count('Payment Entry', {'party': 'Fatima Al Zadjali', 'mode_of_payment': 'Cheque'})}")

if __name__ == "__main__":
    run()
