# apps/misk_real_estate/misk_real_estate/pdc_management/doctype/pdc_batch/pdc_batch.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, today


class PDCBatch(Document):
    def validate(self):
        if not self.mode_of_payment:
            self.mode_of_payment = frappe.db.get_single_value(
                "Misk Real Estate Settings", "pdc_payment_mode"
            )
        self._validate_items()
        self._calc_totals()

    def _validate_items(self):
        if not self.items:
            frappe.throw(_("Add at least one PDC Entry to the batch."))
        seen = set()
        for row in self.items:
            if row.pdc_entry in seen:
                frappe.throw(_("Duplicate PDC Entry {0} in batch.").format(row.pdc_entry))
            seen.add(row.pdc_entry)
            current_status = frappe.db.get_value("PDC Entry", row.pdc_entry, "status")
            if current_status not in ("Pending",):
                frappe.throw(
                    _("PDC Entry {0} has status '{1}'. Only Pending entries can be batched.").format(
                        row.pdc_entry, current_status
                    )
                )

    def _calc_totals(self):
        self.total_cheques = len(self.items)
        self.total_amount = sum(flt(r.amount) for r in self.items)

    def on_submit(self):
        """Mark all PDC Entries in batch as In Batch."""
        for row in self.items:
            frappe.db.set_value("PDC Entry", row.pdc_entry, {
                "status": "In Batch",
                "batch": self.name,
            })

    def on_cancel(self):
        """Revert PDC Entries to Pending on batch cancellation."""
        for row in self.items:
            current = frappe.db.get_value("PDC Entry", row.pdc_entry, "status")
            if current == "In Batch":
                frappe.db.set_value("PDC Entry", row.pdc_entry, {
                    "status": "Pending",
                    "batch": None,
                })


@frappe.whitelist()
def mark_sent_to_bank(batch_name):
    """Mark all entries in batch as Deposited when physically sent to bank."""
    frappe.has_permission("PDC Batch", "write", throw=True)

    batch = frappe.get_doc("PDC Batch", batch_name)
    if batch.batch_status != "Draft":
        frappe.throw(_("Batch is already sent or completed."))

    for row in batch.items:
        status = frappe.db.get_value("PDC Entry", row.pdc_entry, "status")
        if status == "In Batch":
            frappe.db.set_value("PDC Entry", row.pdc_entry, {
                "status": "Deposited",
                "deposited_date": today(),
            })

    frappe.db.set_value("PDC Batch", batch_name, "batch_status", "Sent to Bank")
    frappe.msgprint(
        _("Batch {0} marked Sent to Bank. {1} cheques updated to Deposited.").format(
            batch_name, len(batch.items)
        ),
        alert=True,
    )
