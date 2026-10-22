"""
One-off: re-links a cancelled PDC Entry to the Payment Entry that actually
settled it.

record_manual_payment() handles "customer cancelled the cheque and paid by
cash/transfer instead" — it posts a Payment Entry and cancels the cheque. It
only started stamping that Payment Entry back onto PDC Entry.payment_entry
later, so cheques settled before then look identical in the list and in the
PDC Status Report to a cheque that was simply cancelled with nothing
received. The money is in the GL either way; only the link back is missing.

The Payment Entry is unambiguous because record_manual_payment writes
reference_no = "Manual-<pdc entry name>", so this reads the cheque straight
out of the Payment Entry rather than guessing by customer/amount/date.

Cancelled cheques with no such Payment Entry are left alone — those are
genuinely cancelled, nothing was collected, and that is exactly the
distinction this restores.

SAFE BY DEFAULT: run() only PREVIEWS what it would change, writes nothing.
Pass apply=True to actually write the links.

Usage:
    bench --site <site> execute misk_real_estate.utils.link_manual_payment_entries.run
    # review the printed list, then:
    bench --site <site> execute misk_real_estate.utils.link_manual_payment_entries.run --kwargs "{'apply': True}"
"""

import frappe
from frappe.utils import flt

PREFIX = "Manual-"


def run(apply=False):
    rows = frappe.db.sql(
        """
        SELECT pe.name AS payment_entry, pe.reference_no, pe.mode_of_payment,
               pe.paid_amount, pe.posting_date, pe.docstatus
        FROM `tabPayment Entry` pe
        WHERE pe.reference_no LIKE %(pattern)s
        ORDER BY pe.posting_date
        """,
        {"pattern": PREFIX + "%"},
        as_dict=True,
    )

    todo, skipped = [], []
    for r in rows:
        pdc = r.reference_no[len(PREFIX):]
        entry = frappe.db.get_value(
            "PDC Entry", pdc, ["name", "cheque_no", "amount", "status", "payment_entry"], as_dict=True
        )
        if not entry:
            skipped.append((r.payment_entry, f"PDC Entry {pdc} no longer exists"))
        elif r.docstatus != 1:
            skipped.append((r.payment_entry, f"Payment Entry is docstatus {r.docstatus}, not submitted"))
        elif entry.payment_entry == r.payment_entry:
            skipped.append((r.payment_entry, f"{pdc} already linked"))
        elif entry.payment_entry:
            skipped.append((r.payment_entry, f"{pdc} already points at {entry.payment_entry} — left alone"))
        else:
            todo.append((entry, r))

    print(f"{len(rows)} manual-payment Payment Entries found\n")
    print(f"=== {len(todo)} cheque(s) to link ===")
    for entry, r in todo:
        short = "  PARTIAL!" if abs(flt(r.paid_amount) - flt(entry.amount)) > 0.005 else ""
        print(f"  {entry.name} (cheque {entry.cheque_no}, {entry.amount}, {entry.status})"
              f" -> {r.payment_entry}  {r.paid_amount} {r.mode_of_payment} on {r.posting_date}{short}")

    print(f"\n=== {len(skipped)} skipped ===")
    for pe_name, why in skipped:
        print(f"  {pe_name}: {why}")

    if not apply:
        print("\nDRY RUN ONLY — nothing written. Re-run with apply=True to write the links.")
        return

    for entry, r in todo:
        # update_modified=False: this restores a link that should always have
        # been there, it is not an edit of the cheque by anyone.
        frappe.db.set_value("PDC Entry", entry.name, "payment_entry", r.payment_entry,
                            update_modified=False)

    frappe.db.commit()
    print(f"\nLinked {len(todo)} PDC Entries to their Payment Entry")
