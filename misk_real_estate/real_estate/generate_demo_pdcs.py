# apps/misk_real_estate/misk_real_estate/misk_real_estate/real_estate/generate_demo_pdcs.py
"""Generate demo PDC entries for Fatima Al Zadjali via bench console."""
import frappe
from frappe.utils import today, add_days, add_months


def generate():
    customer = "Fatima Al Zadjali"
    so_name = "SAL-ORD-2026-00002"
    item_code = "BLDG-02-120"
    company = "Misk Real Estate"
    cheque_amount = 520.83
    paid_from = "Debtors - MRE"
    paid_to = "Cash - MRE"

    created_invoices = []
    created_payments = []

    for i in range(20):
        if i == 0:
            chq_date = add_months(today(), -2)
            chq_status = "Cleared"
        else:
            chq_date = add_months(today(), i + 1)
            chq_status = "Pending Deposit"

        due_date = add_days(chq_date, 30)
        chq_no = f"CHQ-{100238 + i:06d}"

        print(f"[{i+1}/20] Creating {chq_no} ({chq_status})...")

        try:
            # Step 1: Sales Invoice
            si = frappe.get_doc({
                "doctype": "Sales Invoice",
                "customer": customer,
                "company": company,
                "posting_date": chq_date,
                "due_date": due_date,
                "items": [{
                    "item_code": item_code,
                    "qty": 1,
                    "rate": cheque_amount,
                    "sales_order": so_name,
                }],
            })
            si.insert()
            si.submit()
            created_invoices.append(si.name)
            frappe.db.commit()
            print(f"  -> Invoice: {si.name}")

            # Step 2: Payment Entry
            pe = frappe.get_doc({
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "company": company,
                "paid_from": paid_from,
                "paid_from_account_currency": "OMR",
                "paid_to": paid_to,
                "paid_to_account_currency": "OMR",
                "paid_amount": cheque_amount,
                "received_amount": cheque_amount,
                "source_exchange_rate": 1.0,
                "target_exchange_rate": 1.0,
                "mode_of_payment": "Cheque",
                "reference_no": chq_no,
                "reference_date": chq_date,
                "cheque_status": chq_status,
                "cheque_date": chq_date,
                "references": [{
                    "reference_doctype": "Sales Invoice",
                    "reference_name": si.name,
                    "allocated_amount": cheque_amount,
                }],
            })
            pe.insert()
            pe.submit()
            created_payments.append(pe.name)
            frappe.db.commit()
            print(f"  -> Payment: {pe.name} | OK")

        except Exception:
            import traceback
            frappe.db.rollback()
            traceback.print_exc()
            print(f"  -> FAILED {chq_no}")

    print(f"\n=== SUMMARY ===")
    print(f"Sales Invoices created: {len(created_invoices)}")
    print(f"Payment Entries created: {len(created_payments)}")
    for status in ["Cleared", "Pending Deposit", "Deposited", "Bounced"]:
        count = frappe.db.count("Payment Entry", {
            "party": "Fatima Al Zadjali",
            "cheque_status": status
        })
        print(f"  {status}: {count}")
    total = frappe.db.count("Payment Entry", {
        "party": "Fatima Al Zadjali",
        "mode_of_payment": "Cheque"
    })
    print(f"  TOTAL: {total}")


if __name__ == "__main__":
    generate()
