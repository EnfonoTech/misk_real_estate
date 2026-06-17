# apps/misk_real_estate/misk_real_estate/pdc_management/doctype/pdc_entry/pdc_entry.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, today, getdate


class PDCEntry(Document):
    def validate(self):
        if flt(self.amount) <= 0:
            frappe.throw(_("Amount must be greater than zero."))
        if not self.cheque_no:
            frappe.throw(_("Cheque No is required."))

    def on_update(self):
        self._sync_booking_schedule_status()

    def _sync_booking_schedule_status(self):
        """Keep PDC Schedule row in Property Booking in sync with this entry's status.
        Uses db_set to bypass allow_on_submit check on submitted Property Booking."""
        if not self.booking:
            return
        try:
            row_name = frappe.db.get_value(
                "PDC Schedule", {"pdc_entry": self.name, "parent": self.booking}, "name"
            )
            if not row_name:
                return
            update = {"status": self.status}
            if self.status == "Cleared" and self.payment_entry:
                update["payment_entry"] = self.payment_entry
            frappe.db.set_value("PDC Schedule", row_name, update)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "PDC Entry: sync booking schedule failed")


@frappe.whitelist()
def mark_cleared(pdc_entry_name, cleared_date=None):
    """
    Mark a PDC Entry as Cleared and create the Payment Entry (GL posts here — B7).
    Called from the UI Confirm Clearance button.
    """
    frappe.has_permission("PDC Entry", "write", throw=True)

    entry = frappe.get_doc("PDC Entry", pdc_entry_name)

    if entry.status == "Cleared" and entry.gl_posted:
        frappe.throw(_("PDC Entry {0} is already cleared and GL posted.").format(pdc_entry_name))

    if entry.status not in ("Deposited", "In Batch", "Cleared"):
        frappe.throw(
            _("Cannot post GL for entry with status: {0}").format(entry.status)
        )

    if entry.gl_posted:
        frappe.throw(_("GL already posted for {0}.").format(pdc_entry_name))

    if not entry.sales_invoice:
        frappe.throw(_("Cannot create Payment Entry for {0}: no Sales Invoice linked. Create an invoice first.").format(pdc_entry_name))

    pe_name = _create_payment_entry(entry, cleared_date or today())
    entry.status = "Cleared"
    entry.cleared_date = cleared_date or today()
    entry.gl_posted = 1
    entry.payment_entry = pe_name  # set on object — no db_set, no timestamp conflict
    entry.save(ignore_permissions=True)

    frappe.msgprint(
        _("Payment Entry created and GL posted for cheque {0}.").format(entry.cheque_no),
        alert=True,
    )
    return entry.payment_entry


@frappe.whitelist()
def mark_bounced(pdc_entry_name, notes=None):
    """Mark a PDC Entry as Bounced. Invoice stays outstanding."""
    frappe.has_permission("PDC Entry", "write", throw=True)

    entry = frappe.get_doc("PDC Entry", pdc_entry_name)
    if entry.status not in ("Deposited", "In Batch"):
        frappe.throw(_("Only Deposited or In Batch entries can be marked Bounced."))

    entry.status = "Bounced"
    if notes:
        entry.notes = (entry.notes or "") + f"\nBounced: {notes}"
    entry.save(ignore_permissions=True)
    frappe.msgprint(_("Cheque {0} marked as Bounced.").format(entry.cheque_no), alert=True)


@frappe.whitelist()
def mark_sent_to_bank(pdc_entry_name, sent_date=None):
    """Move a PDC Entry to 'Sent to Bank' (cheque handed to the bank, pre-deposit)."""
    frappe.has_permission("PDC Entry", "write", throw=True)

    entry = frappe.get_doc("PDC Entry", pdc_entry_name)
    if entry.status not in ("Pending", "In Batch"):
        frappe.throw(
            _("Only Pending or In Batch cheques can be sent to the bank (current: {0}).").format(entry.status)
        )

    entry.status = "Sent to Bank"
    entry.sent_to_bank_date = sent_date or today()
    entry.save(ignore_permissions=True)
    frappe.msgprint(_("Cheque {0} marked as Sent to Bank.").format(entry.cheque_no), alert=True)


@frappe.whitelist()
def mark_deposited(pdc_entry_name, deposited_date=None):
    """Mark a PDC Entry as Deposited (in the bank, awaiting clearance/bounce)."""
    frappe.has_permission("PDC Entry", "write", throw=True)

    entry = frappe.get_doc("PDC Entry", pdc_entry_name)
    if entry.status not in ("Pending", "Sent to Bank", "In Batch"):
        frappe.throw(
            _("Only Pending, Sent to Bank or In Batch cheques can be deposited (current: {0}).").format(entry.status)
        )

    entry.status = "Deposited"
    entry.deposited_date = deposited_date or today()
    entry.save(ignore_permissions=True)
    frappe.msgprint(_("Cheque {0} marked as Deposited.").format(entry.cheque_no), alert=True)


@frappe.whitelist()
def bulk_action(names, action, date=None, notes=None):
    """Apply a PDC status action to many entries from the list view.
    action ∈ {sent_to_bank, deposited, cleared, bounced}.
    Returns {"ok": [names], "failed": [{"name", "error"}]} — per-entry errors are
    collected so one bad cheque doesn't abort the whole batch."""
    frappe.has_permission("PDC Entry", "write", throw=True)
    names = frappe.parse_json(names) if isinstance(names, str) else names

    dispatch = {
        "sent_to_bank": lambda n: mark_sent_to_bank(n, date),
        "deposited":    lambda n: mark_deposited(n, date),
        "cleared":      lambda n: mark_cleared(n, date),
        "bounced":      lambda n: mark_bounced(n, notes),
    }
    fn = dispatch.get(action)
    if not fn:
        frappe.throw(_("Unknown action: {0}").format(action))

    ok, failed = [], []
    for n in (names or []):
        savepoint = f"pdc_{action}_{len(ok) + len(failed)}"
        frappe.db.savepoint(savepoint)
        try:
            fn(n)
            ok.append(n)
        except Exception as e:
            frappe.db.rollback(save_point=savepoint)
            failed.append({"name": n, "error": str(e)})
    return {"ok": ok, "failed": failed}


def _create_payment_entry(pdc_entry, payment_date):
    """Create Payment Entry — GL posts only here (B7 requirement)."""
    company = pdc_entry.company or frappe.defaults.get_user_default("company")

    # Get the default receivable account for company
    receivable_account = frappe.db.get_value(
        "Company", company, "default_receivable_account"
    )
    # Get the bank account linked to the PDC Entry's batch (or entry field or company default)
    bank_account = _get_bank_account(pdc_entry, company)
    account_currency = (
        frappe.db.get_value("Account", bank_account, "account_currency")
        if bank_account
        else None
    ) or getattr(pdc_entry, "currency", None) or "OMR"

    pe = frappe.get_doc({
        "doctype": "Payment Entry",
        "payment_type": "Receive",
        "party_type": "Customer",
        "party": pdc_entry.customer,
        "company": company,
        "posting_date": payment_date,
        "paid_amount": flt(pdc_entry.amount),
        "received_amount": flt(pdc_entry.amount),
        "source_exchange_rate": 1,
        "target_exchange_rate": 1,
        "paid_to": bank_account,
        "paid_to_account_currency": account_currency,
        "paid_from": receivable_account,
        "mode_of_payment": getattr(pdc_entry, "mode_of_payment", None) or "Cheque",
        "reference_no": pdc_entry.cheque_no,
        "reference_date": pdc_entry.cheque_date,
        "remarks": f"PDC Clearance — {pdc_entry.cheque_no} / Booking: {pdc_entry.booking or 'N/A'}",
        "property_booking": pdc_entry.booking or "",
        "party_bank_account": getattr(pdc_entry, "customer_bank_account", None) or "",
        "cheque_status": "Cleared",
    })

    # Resolve Sales Invoice — from entry directly, or look up from PDC Schedule row
    si_name = pdc_entry.sales_invoice
    if not si_name and pdc_entry.booking:
        row_name = frappe.db.get_value(
            "PDC Schedule",
            {"pdc_entry": pdc_entry.name, "parent": pdc_entry.booking},
            "name",
        )
        if row_name:
            si_name = frappe.db.get_value("PDC Schedule", row_name, "sales_invoice")

    if si_name:
        outstanding = frappe.db.get_value("Sales Invoice", si_name, "outstanding_amount")
        if outstanding and flt(outstanding) > 0:
            pe.append("references", {
                "reference_doctype": "Sales Invoice",
                "reference_name": si_name,
                "allocated_amount": min(flt(pdc_entry.amount), flt(outstanding)),
            })

    pe.insert(ignore_permissions=True)
    pe.submit()

    # Do NOT db_set here — caller still holds the PDC Entry doc and will save() it.
    # db_set would bump modified timestamp → timestamp mismatch on caller's save().
    return pe.name


@frappe.whitelist()
def record_manual_payment(pdc_entry_name, mode_of_payment, payment_date, amount, notes=None):
    """
    Create a manual Payment Entry when customer cancels PDC cheque and pays by other means
    (cash / bank transfer).  Marks PDC Entry as Cancelled, overrides the PDC Schedule row
    to Cleared so the booking AR remains accurate.
    """
    frappe.has_permission("PDC Entry", "write", throw=True)

    entry = frappe.get_doc("PDC Entry", pdc_entry_name)

    if entry.status in ("Cleared", "Cancelled"):
        frappe.throw(
            _("PDC Entry {0} is already {1} — cannot record another payment.").format(
                pdc_entry_name, entry.status
            )
        )

    if not entry.sales_invoice:
        frappe.throw(
            _("No Sales Invoice linked to PDC Entry {0}. Link an invoice before recording manual payment.").format(
                pdc_entry_name
            )
        )

    company = entry.company or frappe.defaults.get_user_default("company")
    receivable_account = frappe.db.get_value("Company", company, "default_receivable_account")

    # Resolve paid_to from Mode of Payment → Company account mapping
    mop_account = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account",
    ) or _get_bank_account(entry, company)
    paid_to_currency = (
        frappe.db.get_value("Account", mop_account, "account_currency")
        if mop_account
        else None
    ) or getattr(entry, "currency", None) or "OMR"

    outstanding = flt(
        frappe.db.get_value("Sales Invoice", entry.sales_invoice, "outstanding_amount") or 0
    )
    allocated = min(flt(amount), outstanding) if outstanding > 0 else flt(amount)

    pe = frappe.get_doc({
        "doctype": "Payment Entry",
        "payment_type": "Receive",
        "party_type": "Customer",
        "party": entry.customer,
        "company": company,
        "posting_date": payment_date,
        "paid_amount": flt(amount),
        "received_amount": flt(amount),
        "source_exchange_rate": 1,
        "target_exchange_rate": 1,
        "paid_to": mop_account,
        "paid_to_account_currency": paid_to_currency,
        "paid_from": receivable_account,
        "mode_of_payment": mode_of_payment,
        "reference_no": f"Manual-{pdc_entry_name}",
        "reference_date": payment_date,
        "remarks": notes or _("Manual payment — PDC cheque {0} cancelled by customer").format(entry.cheque_no),
        "property_booking": entry.booking or "",
        "party_bank_account": getattr(entry, "customer_bank_account", None) or "",
        "references": [{
            "reference_doctype": "Sales Invoice",
            "reference_name": entry.sales_invoice,
            "allocated_amount": allocated,
        }],
    })
    pe.flags.ignore_permissions = True
    pe.insert()
    pe.submit()

    # Cancel PDC Entry — on_update will fire and set PDC Schedule row → Cancelled
    entry.status = "Cancelled"
    note_text = notes or _("Customer cancelled cheque. Manual payment {0} recorded.").format(pe.name)
    entry.notes = ((entry.notes or "") + f"\n{note_text}").strip()
    entry.save(ignore_permissions=True)

    # Override PDC Schedule row to Cleared (on_update sets Cancelled, we correct it)
    row_name = frappe.db.get_value(
        "PDC Schedule",
        {"pdc_entry": pdc_entry_name, "parent": entry.booking},
        "name",
    )
    if row_name:
        frappe.db.set_value("PDC Schedule", row_name, {
            "status": "Cleared",
            "payment_entry": pe.name,
        })

    frappe.db.commit()
    frappe.msgprint(
        _("Payment Entry {0} created. Cheque {1} cancelled. Schedule row marked Cleared.").format(
            pe.name, entry.cheque_no
        ),
        alert=True,
    )
    return pe.name


def _get_bank_account(pdc_entry, company):
    """Get bank account: PDC Entry MOP → batch MOP → company default."""
    for mop in [
        getattr(pdc_entry, "mode_of_payment", None),
        frappe.db.get_value("PDC Batch", pdc_entry.batch, "mode_of_payment") if pdc_entry.batch else None,
    ]:
        if mop:
            mop_account = frappe.db.get_value(
                "Mode of Payment Account",
                {"parent": mop, "company": company},
                "default_account",
            )
            if mop_account:
                return mop_account
    return frappe.db.get_value("Company", company, "default_bank_account")
