# apps/misk_real_estate/misk_real_estate/pdc_management/doctype/pdc_entry/pdc_entry.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, today, getdate


class PDCEntry(Document):
    def validate(self):
        if not self.cheque_no:
            frappe.throw(_("Cheque No is required."))
        if not self.allocations:
            frappe.throw(_("Add at least one payment row (building / unit / booking / type / amount)."))
        self._validate_allocations()
        if flt(self.amount) <= 0:
            frappe.throw(_("Cheque amount must be greater than zero."))

    @property
    def is_allocated(self):
        """True when this cheque uses the allocation table (one cheque -> many
        bookings/purposes) rather than the legacy single-booking fields."""
        return bool(self.allocations)

    def _validate_allocations(self):
        """The allocation table is the source of truth. One cheque, one customer;
        cheque amount = sum of rows. Each row's building/unit are auto-filled from its
        booking, and the primary row is mirrored into the (hidden) header fields so
        existing reports / cron / batch logic keep working."""
        if not self.allocations:
            return
        total = 0.0
        for row in self.allocations:
            if flt(row.allocated_amount) <= 0:
                frappe.throw(_("Allocation row {0}: Amount must be greater than zero.").format(row.idx))
            if not row.purpose:
                frappe.throw(_("Allocation row {0}: Type is required.").format(row.idx))
            bk = frappe.db.get_value(
                "Property Booking", row.property_booking,
                ["customer", "unit", "building"], as_dict=True
            ) or {}
            if not self.customer:
                self.customer = bk.get("customer")
            if bk.get("customer") and self.customer and bk["customer"] != self.customer:
                frappe.throw(
                    _("Allocation row {0}: Booking {1} belongs to {2}, not {3}. One cheque is for a single customer.").format(
                        row.idx, row.property_booking, bk["customer"], self.customer
                    )
                )
            if not row.unit:
                row.unit = bk.get("unit")
            if not row.building:
                row.building = bk.get("building")
            total += flt(row.allocated_amount)

        # Cheque amount = sum of rows.
        self.amount = round(total, 3)

    def on_update(self):
        self._sync_booking_schedule_status()

    def _sync_booking_schedule_status(self):
        """Mirror this cheque's status onto every PDC Schedule row that points to it.
        One cheque may back several installment rows (across bookings), so sync them
        all. Uses db_set to bypass allow_on_submit on submitted bookings."""
        try:
            rows = frappe.get_all(
                "PDC Schedule", filters={"pdc_entry": self.name}, fields=["name", "parent"]
            )
            if not rows:
                return
            update = {"status": self.status}
            if self.status == "Cleared" and self.payment_entry:
                update["payment_entry"] = self.payment_entry
            for r in rows:
                frappe.db.set_value("PDC Schedule", r.name, update)
            # Recompute the affected booking(s) AFTER the rows are synced, so
            # installment_progress reflects this status change (not the prior state).
            from misk_real_estate.real_estate.doctype.property_booking.property_booking import (
                update_booking_payment_status,
            )
            for booking in {r.parent for r in rows}:
                update_booking_payment_status(booking)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "PDC Entry: sync booking schedule failed")


def link_invoice_to_allocation(pdc_entry_name, booking, purpose, si_name):
    """Attach a Sales Invoice to the matching allocation row of a PDC Entry.
    Used when invoices are generated after the cheque was recorded."""
    if not pdc_entry_name or not si_name:
        return
    base = {"parent": pdc_entry_name, "property_booking": booking}
    alloc = (frappe.db.get_value("PDC Allocation", {**base, "purpose": purpose}, "name")
             or frappe.db.get_value("PDC Allocation", base, "name"))
    if alloc:
        frappe.db.set_value("PDC Allocation", alloc, "sales_invoice", si_name)


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

    # A cheque clears in one shot — block unless EVERY allocation has an invoice.
    missing = [str(a.idx) for a in entry.allocations if not a.sales_invoice]
    if missing:
        frappe.throw(
            _("Every allocation must have a Sales Invoice before this cheque can be cleared. "
              "Missing on row(s): {0}.").format(", ".join(missing))
        )
    pe_name = _create_allocated_payment_entry(entry, cleared_date or today())
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
def mark_bounced(pdc_entry_name, bounce_reason=None, notes=None):
    """Mark a PDC Entry as Bounced (with a reason). Invoice stays outstanding."""
    frappe.has_permission("PDC Entry", "write", throw=True)

    entry = frappe.get_doc("PDC Entry", pdc_entry_name)
    if entry.status not in ("Deposited", "In Batch", "Sent to Bank"):
        frappe.throw(_("Only Sent to Bank, Deposited or In Batch entries can be marked Bounced."))

    entry.status = "Bounced"
    if bounce_reason:
        entry.bounce_reason = bounce_reason
    if notes:
        entry.notes = (entry.notes or "") + f"\nBounced: {notes}"
    entry.save(ignore_permissions=True)
    frappe.msgprint(_("Cheque {0} marked as Bounced.").format(entry.cheque_no), alert=True)


@frappe.whitelist()
def mark_returned(pdc_entry_name, notes=None):
    """Mark a PDC Entry as Returned (handed back to the customer)."""
    frappe.has_permission("PDC Entry", "write", throw=True)
    entry = frappe.get_doc("PDC Entry", pdc_entry_name)
    if entry.status in ("Cleared", "Cancelled", "Returned"):
        frappe.throw(_("A {0} cheque cannot be returned.").format(entry.status))
    entry.status = "Returned"
    if notes:
        entry.notes = (entry.notes or "") + f"\nReturned: {notes}"
    entry.save(ignore_permissions=True)
    frappe.msgprint(_("Cheque {0} marked as Returned.").format(entry.cheque_no), alert=True)


@frappe.whitelist()
def mark_cancelled(pdc_entry_name, notes=None):
    """Cancel a PDC Entry (void the cheque). No GL impact."""
    frappe.has_permission("PDC Entry", "write", throw=True)
    entry = frappe.get_doc("PDC Entry", pdc_entry_name)
    if entry.status in ("Cleared", "Cancelled"):
        frappe.throw(_("A {0} cheque cannot be cancelled.").format(entry.status))
    entry.status = "Cancelled"
    if notes:
        entry.notes = (entry.notes or "") + f"\nCancelled: {notes}"
    entry.save(ignore_permissions=True)
    frappe.msgprint(_("Cheque {0} cancelled.").format(entry.cheque_no), alert=True)


@frappe.whitelist()
def mark_substituted(pdc_entry_name, new_cheque_no, new_cheque_date, notes=None):
    """Mark this cheque Substituted and create a replacement PDC Entry — an exact
    copy (customer, bank, allocations) with a new cheque no/date, left Pending."""
    frappe.has_permission("PDC Entry", "write", throw=True)
    entry = frappe.get_doc("PDC Entry", pdc_entry_name)
    if entry.status in ("Cleared", "Cancelled", "Substituted"):
        frappe.throw(_("A {0} cheque cannot be substituted.").format(entry.status))
    if not new_cheque_no or not new_cheque_date:
        frappe.throw(_("New cheque number and date are required."))
    if frappe.db.exists("PDC Entry", {"cheque_no": new_cheque_no}):
        frappe.throw(_("A PDC Entry with cheque no {0} already exists.").format(new_cheque_no))

    replacement = frappe.get_doc({
        "doctype": "PDC Entry",
        "cheque_no": new_cheque_no,
        "cheque_date": new_cheque_date,
        "customer": entry.customer,
        "customer_bank_account": entry.customer_bank_account,
        "company": entry.company,
        "currency": entry.currency,
        "mode_of_payment": entry.mode_of_payment,
        "status": "Pending",
        "notes": _("Substitute for cheque {0}.").format(entry.cheque_no),
        "allocations": [{
            "property_booking": a.property_booking,
            "purpose": a.purpose,
            "building": a.building,
            "unit": a.unit,
            "sales_invoice": a.sales_invoice,
            "allocated_amount": a.allocated_amount,
        } for a in entry.allocations],
    })
    replacement.insert(ignore_permissions=True)

    entry.status = "Substituted"
    entry.substituted_by = replacement.name
    note_text = notes or _("Substituted by cheque {0}.").format(new_cheque_no)
    entry.notes = ((entry.notes or "") + f"\n{note_text}").strip()
    entry.save(ignore_permissions=True)

    frappe.msgprint(
        _("Cheque {0} substituted by new PDC Entry {1} (Pending).").format(entry.cheque_no, replacement.name),
        alert=True,
    )
    return replacement.name


@frappe.whitelist()
def pending_pdcs_card(filters=None):
    """Custom Number Card: count of Pending cheques due today or earlier, plus the
    route + filters so clicking the card opens that exact list. Computing here (not
    via a dynamic filter) keeps BOTH the count and the click-through correct."""
    as_of = frappe.utils.nowdate()
    count = frappe.db.count("PDC Entry", {"status": "Pending", "cheque_date": ["<=", as_of]})
    return {
        "value": count,
        "fieldtype": "Int",
        "route": ["List", "PDC Entry"],
        "route_options": {
            "status": "Pending",
            "cheque_date": ["<=", as_of],
        },
    }


@frappe.whitelist()
def get_allocation_defaults(booking, purpose=None):
    """Auto-fill values for an allocation row: building/unit from the booking, plus
    the suggested amount (tax-inclusive) and existing advance Sales Invoice when the
    type is Booking Amount / Down Payment."""
    b = frappe.get_doc("Property Booking", booking)
    out = {"building": b.building, "unit": b.unit, "amount": 0, "sales_invoice": None}

    base, breakdown = 0, None
    if purpose == "Booking Amount":
        base, breakdown = flt(b.booking_amount), b._get_unit_tax_breakdown
    elif purpose == "Down Payment":
        base, breakdown = flt(b.down_payment_amount), b._get_unit_tax_breakdown
    elif purpose == "Owners Association Fee":
        base, breakdown = flt(b.owners_association_fee), b._get_oa_tax_breakdown

    if base > 0 and breakdown:
        out["amount"] = breakdown(base)[2]  # (net, tax, total) -> total
        out["sales_invoice"] = frappe.db.get_value(
            "Sales Invoice",
            {"custom_property_booking": booking, "custom_payment_purpose": purpose, "docstatus": ("<", 2)},
            "name", order_by="docstatus desc, creation desc",
        )
    return out


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
def bulk_action(names, action, date=None, notes=None, bounce_reason=None):
    """Apply a PDC status action to many entries from the list view.
    action ∈ {sent_to_bank, deposited, cleared, bounced, returned, cancelled}.
    Returns {"ok": [names], "failed": [{"name", "error"}]} — per-entry errors are
    collected so one bad cheque doesn't abort the whole batch."""
    frappe.has_permission("PDC Entry", "write", throw=True)
    names = frappe.parse_json(names) if isinstance(names, str) else names

    dispatch = {
        "sent_to_bank": lambda n: mark_sent_to_bank(n, date),
        "deposited":    lambda n: mark_deposited(n, date),
        "cleared":      lambda n: mark_cleared(n, date),
        "bounced":      lambda n: mark_bounced(n, bounce_reason, notes),
        "returned":     lambda n: mark_returned(n, notes),
        "cancelled":    lambda n: mark_cancelled(n, notes),
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


def _create_allocated_payment_entry(pdc_entry, payment_date):
    """One physical cheque -> ONE Payment Entry that settles every allocated
    Sales Invoice (booking amount / down payment across one or more bookings)."""
    company = pdc_entry.company or frappe.defaults.get_user_default("company")
    receivable_account = frappe.db.get_value("Company", company, "default_receivable_account")
    bank_account = _get_bank_account(pdc_entry, company)
    account_currency = (
        frappe.db.get_value("Account", bank_account, "account_currency")
        if bank_account else None
    ) or getattr(pdc_entry, "currency", None) or "OMR"

    # Header property_booking / property_unit only when the whole cheque is for ONE
    # booking; otherwise leave blank (the per-invoice booking is on each SI reference).
    bookings = {a.property_booking for a in pdc_entry.allocations if a.property_booking}
    single_booking = next(iter(bookings)) if len(bookings) == 1 else ""
    single_unit = ""
    if single_booking:
        units = {a.unit for a in pdc_entry.allocations if a.unit}
        single_unit = (next(iter(units)) if len(units) == 1
                       else frappe.db.get_value("Property Booking", single_booking, "unit"))

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
        "remarks": f"PDC Clearance — {pdc_entry.cheque_no} / {len(pdc_entry.allocations)} allocation(s)",
        "property_booking": single_booking,
        "property_unit": single_unit,
        "party_bank_account": getattr(pdc_entry, "customer_bank_account", None) or "",
        "cheque_status": "Cleared",
    })

    for alloc in pdc_entry.allocations:
        outstanding = flt(frappe.db.get_value("Sales Invoice", alloc.sales_invoice, "outstanding_amount") or 0)
        if outstanding <= 0:
            continue  # already settled — skip, don't over-allocate
        pe.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": alloc.sales_invoice,
            "allocated_amount": min(flt(alloc.allocated_amount), outstanding),
        })

    if not pe.get("references"):
        frappe.throw(_("No outstanding Sales Invoice amount to settle for cheque {0}.").format(pdc_entry.cheque_no))

    pe.insert(ignore_permissions=True)
    pe.submit()
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

    if len(entry.allocations or []) > 1:
        frappe.throw(_("Record Manual Payment is not supported for a multi-allocation cheque."))

    if entry.status in ("Cleared", "Cancelled"):
        frappe.throw(
            _("PDC Entry {0} is already {1} — cannot record another payment.").format(
                pdc_entry_name, entry.status
            )
        )

    alloc = entry.allocations[0] if entry.allocations else None
    if not alloc or not alloc.sales_invoice:
        frappe.throw(
            _("No Sales Invoice linked to PDC Entry {0}. Link an invoice before recording manual payment.").format(
                pdc_entry_name
            )
        )
    si_name = alloc.sales_invoice
    booking_name = alloc.property_booking

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
        frappe.db.get_value("Sales Invoice", si_name, "outstanding_amount") or 0
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
        "property_booking": booking_name or "",
        "party_bank_account": getattr(entry, "customer_bank_account", None) or "",
        "references": [{
            "reference_doctype": "Sales Invoice",
            "reference_name": si_name,
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
        {"pdc_entry": pdc_entry_name, "parent": booking_name},
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
