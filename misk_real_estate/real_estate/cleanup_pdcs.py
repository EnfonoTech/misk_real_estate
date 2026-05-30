# apps/misk_real_estate/misk_real_estate/misk_real_estate/real_estate/cleanup_pdcs.py
"""Clean up extra PDC entry and verify final counts."""
import frappe

def cleanup():
    # Find pending entries without invoice references
    extra = []
    pes = frappe.db.get_all("Payment Entry", filters={
        "party": "Fatima Al Zadjali",
        "cheque_status": "Pending Deposit"
    }, fields=["name", "reference_no", "cheque_date"])

    for p in pes:
        refs = frappe.db.sql(
            "SELECT reference_name FROM `tabPayment Entry Reference` WHERE parent = %s",
            (p.name,)
        )
        has_invoice = bool([r for r in refs if r[0]])
        if not has_invoice:
            extra.append(p['name'])
            print(f"  NO INVOICE: {p['name']} {p['reference_no']} {p['cheque_date']}")

    if extra:
        for name in extra:
            pe = frappe.get_doc("Payment Entry", name)
            pe.cancel()
            frappe.db.commit()
            print(f"  Cancelled: {name}")

    print("\n=== FINAL COUNTS ===")
    for s in ["Cleared", "Pending Deposit", "Deposited", "Bounced"]:
        c = frappe.db.count("Payment Entry", {
            "party": "Fatima Al Zadjali",
            "cheque_status": s
        })
        print(f"  {s}: {c}")
    total = frappe.db.count("Payment Entry", {
        "party": "Fatima Al Zadjali",
        "mode_of_payment": "Cheque"
    })
    print(f"  TOTAL: {total}")

if __name__ == "__main__":
    cleanup()
