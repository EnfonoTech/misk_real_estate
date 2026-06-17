# apps/misk_real_estate/misk_real_estate/real_estate/doctype/property_booking/property_booking.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, cstr, today, add_days, add_months, getdate


class PropertyBooking(Document):
    def validate(self):
        # Auto-fill taxes_and_charges only on new documents (don't override if user cleared it)
        if self.is_new() and not self.taxes_and_charges and self.company and not self.quotation:
            self.taxes_and_charges = _get_default_taxes(self.company)
        self.calculate_payment_schedule()
        # Default the down payment date to booking date + configured days
        if self.booking_date and not self.down_payment_date:
            settings = frappe.get_cached_doc("Misk Real Estate Settings")
            self.down_payment_date = add_days(getdate(self.booking_date), cint(settings.down_payment_days) or 2)
        self.validate_duplicate_booking()
        self._check_unit_availability()
        # Generate the installment + OA schedule on first save (only when a plan is set).
        # Booking Amount and Down Payment are handled separately, NOT in this table.
        # Use "Regenerate PDC Schedule" button to rebuild manually if needed.
        if self.docstatus == 0 and not self.pdc_schedule \
                and self.unit_price and self.payment_plan:
            self.generate_pdc_schedule()
        self._compute_totals()
        self._compute_installment_progress()
        self._set_status()

    def _advance_received(self, purpose):
        """True when a submitted invoice for this purpose is fully paid."""
        outstanding = frappe.db.get_value(
            "Sales Invoice",
            {"custom_property_booking": self.name, "custom_payment_purpose": purpose, "docstatus": 1},
            "outstanding_amount",
        )
        return outstanding is not None and flt(outstanding) <= 0.01

    def _set_status(self):
        """Payment status field — separate from the approval workflow_state.
        Booking Amount / Down Payment receipts (which may land before or after
        submission) take precedence, so they stay visible at any stage."""
        if self.docstatus == 2:
            self.status = "Cancelled"
            return
        if self.status in ("Closed", "Lost"):
            return  # terminal — Closed via Mark Unit Sold, Lost via Mark Lost
        if self._advance_received("Down Payment"):
            self.status = "Down Payment Received"
        elif self._advance_received("Booking Amount"):
            self.status = "Booking Amount Received"
        elif self.docstatus == 1:
            self.status = "Confirmed"
        else:
            self.status = "Draft"

    def before_submit(self):
        self.validate_required_fields()
        # Generate if somehow still empty and a plan exists (e.g. created programmatically)
        if not self.pdc_schedule and self.payment_plan:
            self.generate_pdc_schedule()
        # Validate cheque_no mandatory for PDC rows (installments + OA)
        for row in self.pdc_schedule:
            if row.get("is_pdc") and not row.cheque_no:
                frappe.throw(
                    _("Row {0}: Cheque No is required for PDC rows.").format(row.idx)
                )
        # Hard block — the PDC table must add up to the expected Installments + OA total
        self._compute_totals()
        if abs(flt(self.table_difference)) > 0.01:
            frappe.throw(
                _("PDC Schedule total ({0} OMR) does not match the expected Installments + OA "
                  "total ({1} OMR). Difference: {2} OMR. Adjust the rows so the difference is "
                  "zero before submitting.").format(
                    flt(self.table_total), flt(self.expected_table_total),
                    flt(self.table_difference)),
                title=_("PDC Amount Mismatch"),
            )
        # Payment status — advance milestone if received, else Confirmed
        if self._advance_received("Down Payment"):
            self.status = "Down Payment Received"
        elif self._advance_received("Booking Amount"):
            self.status = "Booking Amount Received"
        else:
            self.status = "Confirmed"

    def on_submit(self):
        self._set_unit_status("Booked")
        if self.invoice_generation == "All at Once":
            self._generate_all_invoices_now()
        if self.quotation:
            self._update_quotation_status()
        update_booking_payment_status(self.name)

    def on_cancel(self):
        self.status = "Cancelled"
        self._cancel_pdc_entries()
        self._set_unit_status("Available")
        if self.quotation:
            self._clear_quotation_booking_link()
            self._update_quotation_status()

    def after_insert(self):
        """Reserve the unit as soon as the booking is created (draft stage).
        Only claim a free unit — never downgrade a unit already Booked/Sold."""
        if not self.unit:
            return
        current = frappe.db.get_value("Item", self.unit, "unit_status")
        if current in (None, "", "Available"):
            self._set_unit_status("Reserved")

    def on_trash(self):
        """Release a draft reservation if this booking is deleted and no other
        active booking holds the unit (avoid orphaned 'Reserved' units)."""
        if self.unit and self.docstatus == 0:
            current = frappe.db.get_value("Item", self.unit, "unit_status")
            if current == "Reserved" and not self._unit_reserved_by_other():
                self._set_unit_status("Available")

    # ── Validation ────────────────────────────────────────────────────────────

    def _check_unit_availability(self):
        """Block booking if the unit is taken by a DIFFERENT booking.
        A unit Reserved by *this* same booking (draft) must not block its own saves."""
        if not self.unit:
            return
        if self.docstatus == 1:
            return  # allow edits on an already-submitted booking
        unit_status = frappe.db.get_value("Item", self.unit, "unit_status")
        if unit_status in ("Sold", "Booked"):
            frappe.throw(
                _("Unit {0} is currently {1} and cannot be booked.").format(
                    self.unit, unit_status
                )
            )
        if unit_status == "Reserved":
            other = self._unit_reserved_by_other()
            if other:
                frappe.throw(
                    _("Unit {0} is Reserved under another booking ({1}).").format(
                        self.unit, other
                    )
                )

    def _unit_reserved_by_other(self):
        """Name of another active booking (not cancelled) holding this unit, else None.
        Lets us tell 'my own reservation' apart from a genuine conflict."""
        if not self.unit:
            return None
        return frappe.db.get_value(
            "Property Booking",
            {
                "unit": self.unit,
                "name": ("!=", self.name or ""),
                "status": ("not in", ["Cancelled", "Lost"]),
                "docstatus": ("<", 2),
            },
            "name",
        )

    def _set_unit_status(self, status):
        """Update unit_status custom field on the linked Item."""
        if not self.unit:
            return
        frappe.db.set_value("Item", self.unit, "unit_status", status)

    def _generate_all_invoices_now(self):
        """
        All at Once mode: create Sales Invoices for every PDC schedule row
        immediately on booking submit.
        posting_date = booking_date (today), due_date = each row's cheque_date.
        Runs via background job to avoid timeout on large schedules.
        """
        frappe.enqueue(
            method="misk_real_estate.real_estate.doctype.property_booking.property_booking.generate_invoices_for_booking",
            queue="default",
            timeout=600,
            enqueue_after_commit=True,
            job_name=f"gen_invoices_{self.name}",
            booking_name=self.name,
        )

    def validate_duplicate_booking(self):
        """Block double-booking the same unit (A3)."""
        if not self.unit:
            return
        existing = frappe.db.get_value(
            "Property Booking",
            {
                "unit": self.unit,
                "docstatus": 1,
                "name": ("!=", self.name or ""),
                "status": ("not in", ["Cancelled"]),
            },
            "name",
        )
        if existing:
            frappe.throw(
                _("Unit {0} is already booked under {1}. Duplicate booking blocked (A3).").format(
                    self.unit, existing
                )
            )

    def validate_required_fields(self):
        if not self.unit_price or flt(self.unit_price) <= 0:
            frappe.throw(_("Unit Price is required and must be greater than zero."))
        if not self.booking_amount or flt(self.booking_amount) <= 0:
            frappe.throw(_("Booking Amount is required and must be greater than zero."))
        if not self.booking_date:
            frappe.throw(_("Booking Date is required."))

    def calculate_payment_schedule(self):
        """Auto-calculate down payment and installment amounts.
        Supports two modes:
          Percentage — user sets down_payment_percentage, amount is derived
          Fixed Amount — user sets down_payment_amount directly, % is back-calculated
        """
        unit_price = flt(self.unit_price)
        booking_amount = flt(self.booking_amount)

        if not unit_price or not booking_amount:
            return  # wait until user fills required fields

        # Down payment %/amount conversion — depends only on unit_price, NOT on a
        # payment plan. Whichever the user entered drives the other.
        dp_amount = flt(self.down_payment_amount)
        dp_pct = flt(self.down_payment_percentage)
        if dp_amount > 0:
            self.down_payment_percentage = round(dp_amount / unit_price * 100, 3)
        elif dp_pct > 0:
            self.down_payment_amount = round(unit_price * dp_pct / 100, 3)

        # The installment split is the only part that genuinely needs a plan.
        if not self.payment_plan:
            return
        plan_doc = frappe.db.get_value(
            "Payment Plan", self.payment_plan,
            ["number_of_installments", "is_full_payment"], as_dict=True
        )
        if not plan_doc:
            return
        if plan_doc.is_full_payment or not plan_doc.number_of_installments:
            # Full Payment — no down payment, no installments
            self.number_of_installments = 0
            self.down_payment_percentage = 0
            self.down_payment_amount = 0
            self.monthly_installment = 0
            return
        self.number_of_installments = cint(plan_doc.number_of_installments)

        remaining = unit_price - booking_amount
        # Default to 50% only when neither was entered (and a plan is present)
        if not dp_amount and not dp_pct:
            self.down_payment_percentage = 50
            self.down_payment_amount = round(unit_price * 0.50, 3)

        after_dp = remaining - flt(self.down_payment_amount)
        n = cint(self.number_of_installments)
        if n > 0 and after_dp > 0:
            self.monthly_installment = round(after_dp / n, 3)

    # ── PDC Schedule generation (A7) ─────────────────────────────────────────

    def generate_pdc_schedule(self):
        """
        Populate pdc_schedule child table with Installment + OA Fee rows only.
        Booking Amount and Down Payment are collected separately (cash / bank /
        cheque) via their own Sales Invoices — they are NOT part of this table.
        No GL, no Payment Entry — only the plan (B7 requirement).
        """
        booking_date = getdate(self.booking_date)
        seq = 1

        settings = frappe.get_cached_doc("Misk Real Estate Settings")
        dp_days = cint(settings.down_payment_days) or 2

        plan_doc = frappe.db.get_value(
            "Payment Plan", self.payment_plan,
            ["number_of_installments", "is_full_payment"], as_dict=True
        ) if self.payment_plan else None
        is_full = (not plan_doc) or plan_doc.is_full_payment or not plan_doc.number_of_installments

        if not is_full:
            # Monthly installment rows
            n = cint(self.number_of_installments)
            # Precise installment portion (incl. tax) = unit total − booking − down payment.
            # The last row absorbs any per-row rounding so the table matches exactly.
            _x, _y, unit_total = self._get_unit_tax_breakdown(flt(self.unit_price))
            _x, _y, booking_total = self._get_unit_tax_breakdown(flt(self.booking_amount))
            _x, _y, dp_total = self._get_unit_tax_breakdown(flt(self.down_payment_amount))
            inst_target = round(unit_total - booking_total - dp_total, 3)

            running = 0.0
            for i in range(1, n + 1):
                inst_date = add_months(booking_date, i)
                row = self._pdc_row(seq, "Installment", inst_date, flt(self.monthly_installment))
                if i == n:
                    total = round(inst_target - running, 3)
                    rate = (flt(row["tax_amount"]) / flt(row["net_amount"]) * 100) if flt(row["net_amount"]) else 0
                    net = round(total / (1 + rate / 100), 3) if rate else total
                    row["amount"] = total
                    row["net_amount"] = net
                    row["tax_amount"] = round(total - net, 3)
                running = round(running + flt(row["amount"]), 3)
                self.append("pdc_schedule", row)
                seq += 1
            oa_date = add_months(booking_date, n)
        else:
            oa_date = add_days(booking_date, dp_days)

        # Owners Association Fee row — use OA item's tax rate
        if flt(self.owners_association_fee) > 0:
            oa_bd = self._get_oa_tax_breakdown(flt(self.owners_association_fee))
            self.append("pdc_schedule", self._pdc_row(seq, "Owners Association Fee", oa_date, flt(self.owners_association_fee), breakdown=oa_bd))

    def _compute_totals(self):
        """Compute totals and the helper fields that guide PDC table entry.
        table_total          = sum of PDC schedule rows (installments + OA)
        expected_table_total = Grand Total − Booking Amount − Down Payment (all incl. tax)
        table_difference     = table_total − expected_table_total (must be 0 to submit)
        """
        unit_price = flt(self.unit_price)
        oa_fee = flt(self.owners_association_fee)

        self.total_amount = unit_price + oa_fee  # pre-tax subtotal

        # Unit price tax (taxes_and_charges if set, else unit item's Item Tax Template)
        _net, unit_tax, unit_total = self._get_unit_tax_breakdown(unit_price)

        # OA fee tax (uses OA-FEE item's Item Tax Template, falls back to taxes_and_charges)
        if oa_fee:
            _net, oa_tax, oa_total = self._get_oa_tax_breakdown(oa_fee)
        else:
            oa_tax, oa_total = 0.0, 0.0

        self.tax_amount = round(unit_tax + oa_tax, 3)
        self.total_after_tax = round(unit_total + oa_total, 3)

        # Booking Amount and Down Payment are collected outside the table (incl. tax)
        _n, _t, booking_total = self._get_unit_tax_breakdown(flt(self.booking_amount))
        _n, _t, dp_total = self._get_unit_tax_breakdown(flt(self.down_payment_amount))
        self.expected_table_total = round(self.total_after_tax - booking_total - dp_total, 3)

        self.table_total = round(sum(flt(r.amount) for r in self.pdc_schedule), 3) if self.pdc_schedule else 0.0
        self.table_difference = round(flt(self.table_total) - flt(self.expected_table_total), 3)

    def _compute_installment_progress(self):
        """Percentage of (non-cancelled) PDC schedule rows that are Cleared."""
        rows = [r for r in (self.pdc_schedule or []) if r.status != "Cancelled"]
        total = len(rows)
        if not total:
            self.installment_progress = 0
            return
        cleared = len([r for r in rows if r.status == "Cleared"])
        self.installment_progress = round(cleared / total * 100, 1)

    def _get_oa_tax_breakdown(self, base_amount):
        """
        Tax breakdown for OA Fee row.
        Priority:
          1. OA-FEE item's Item Tax Template
          2. OA-FEE item's item_group Item Tax Template
          3. Fallback: booking's taxes_and_charges template
        Item Tax Template rates are always exclusive (added on top of base).
        """
        settings = frappe.get_cached_doc("Misk Real Estate Settings")
        oa_item = getattr(settings, "oa_fee_item", None)

        if oa_item:
            rate = _item_tax_rate(oa_item)
            if rate is None:
                # No template on item → check item group
                item_group = frappe.db.get_value("Item", oa_item, "item_group")
                if item_group:
                    rate = _item_tax_rate(item_group)
            if rate is not None:
                # Template explicitly defined (even if 0%) → use it, don't fall through
                if rate:
                    net   = flt(base_amount)
                    tax   = round(net * rate / 100, 3)
                    total = round(net + tax, 3)
                    return net, tax, total
                else:
                    return flt(base_amount), 0.0, flt(base_amount)

        # No oa_fee_item or no template anywhere → fall back to booking taxes_and_charges
        return self._get_tax_breakdown(base_amount)

    def _pdc_row(self, seq, installment_type, cheque_date, base_amount, cheque_no="", breakdown=None):
        """Build a PDC Schedule row dict with tax breakdown applied to base_amount.
        breakdown: optional (net, tax, total) tuple; if None, uses _get_unit_tax_breakdown.
        """
        if breakdown:
            net, tax, total = breakdown
        else:
            net, tax, total = self._get_unit_tax_breakdown(base_amount)
        return {
            "sequence_no":    seq,
            "installment_type": installment_type,
            "is_pdc":         1,
            "cheque_date":    cheque_date,
            "net_amount":     net,
            "tax_amount":     tax,
            "amount":         total,
            "cheque_no":      cheque_no,
            "status":         "Pending",
        }

    def _get_unit_tax_breakdown(self, base_amount):
        """Tax breakdown for unit price rows.
        Uses taxes_and_charges template if set (handles inclusive/exclusive).
        Falls back to: unit item's Item Tax Template → item group's Item Tax Template.
        """
        if self.taxes_and_charges:
            return self._get_tax_breakdown(base_amount)
        if self.unit and base_amount:
            rate = _item_tax_rate(self.unit)
            if rate is None:
                # Check item group
                item_group = frappe.db.get_value("Item", self.unit, "item_group")
                if item_group:
                    rate = _item_tax_rate(item_group)
            if rate:
                net   = flt(base_amount)
                tax   = round(net * rate / 100, 3)
                total = round(net + tax, 3)
                return net, tax, total
        return flt(base_amount), 0.0, flt(base_amount)

    def _get_tax_breakdown(self, base_amount):
        """Return (net_amount, tax_amount, total_cheque_amount).
        Inclusive: tax extracted from base_amount; total = base_amount.
        Exclusive: tax added on top;               total = base_amount + tax.
        """
        if not self.taxes_and_charges or not base_amount:
            return flt(base_amount), 0.0, flt(base_amount)

        tax_rows = frappe.db.get_all(
            "Sales Taxes and Charges",
            filters={"parent": self.taxes_and_charges, "parenttype": "Sales Taxes and Charges Template"},
            fields=["rate", "included_in_print_rate", "charge_type"],
        )
        effective_rate = sum(
            flt(t.rate) for t in tax_rows
            if t.charge_type in ("On Net Total", "On Previous Row Total")
        )
        if not effective_rate:
            return flt(base_amount), 0.0, flt(base_amount)

        is_inclusive = any(t.included_in_print_rate for t in tax_rows)

        if is_inclusive:
            net  = round(flt(base_amount) / (1 + effective_rate / 100), 3)
            tax  = round(flt(base_amount) - net, 3)
            total = flt(base_amount)
        else:
            net   = flt(base_amount)
            tax   = round(flt(base_amount) * effective_rate / 100, 3)
            total = round(net + tax, 3)

        return net, tax, total

    def _update_schedule_amounts(self):
        """Recalculate amounts for fixed rows, using the correct breakdown per row type."""
        for row in self.pdc_schedule:
            if row.installment_type == "Owners Association Fee":
                base = flt(self.owners_association_fee)
                net, tax, total = self._get_oa_tax_breakdown(base)
            elif row.installment_type == "Booking Amount":
                base = flt(self.booking_amount)
                net, tax, total = self._get_unit_tax_breakdown(base)
            elif row.installment_type == "Down Payment":
                base = flt(self.down_payment_amount)
                net, tax, total = self._get_unit_tax_breakdown(base)
            else:
                continue
            row.net_amount = net
            row.tax_amount = tax
            row.amount     = total

    def _update_quotation_status(self):
        """Set Quotation status: Ordered / Partially Ordered / Open based on linked bookings."""
        settings = frappe.get_cached_doc("Misk Real Estate Settings")
        oa_item = getattr(settings, "oa_fee_item", None)

        items = frappe.get_all(
            "Quotation Item",
            filters={"parent": self.quotation},
            fields=["item_code", "property_booking"],
        )
        unit_lines = [i for i in items if i.item_code != oa_item]
        if not unit_lines:
            return

        converted = [i for i in unit_lines if i.property_booking]
        if len(converted) == len(unit_lines):
            status = "Ordered"
        elif converted:
            status = "Partially Ordered"
        else:
            status = "Open"

        frappe.db.set_value("Quotation", self.quotation, "status", status)

    def _clear_quotation_booking_link(self):
        """On booking cancel, clear the property_booking link from its Quotation Item row."""
        frappe.db.set_value(
            "Quotation Item",
            {"parent": self.quotation, "property_booking": self.name},
            "property_booking",
            "",
        )

    def _cancel_pdc_entries(self):
        """Cancel linked PDC Entries that haven't been cleared."""
        pdc_entries = frappe.get_all(
            "PDC Entry",
            filters={"booking": self.name, "status": ("not in", ["Cleared", "Bounced"])},
            fields=["name", "status"],
        )
        for entry in pdc_entries:
            frappe.db.set_value("PDC Entry", entry.name, "status", "Cancelled")


# ── Advance Payments (Booking Amount & Down Payment) ───────────────────────────

def update_booking_payment_status(booking_name):
    """Recompute booking payment status and installment progress from linked
    submitted Sales Invoices and the PDC schedule.
    Safe to call on submitted bookings (writes directly, no version bump)."""
    if not booking_name or not frappe.db.exists("Property Booking", booking_name):
        return

    docstatus = frappe.db.get_value("Property Booking", booking_name, "docstatus")
    updates = {}
    received = {}
    for purpose in ("Booking Amount", "Down Payment"):
        si = frappe.db.get_value(
            "Sales Invoice",
            {"custom_property_booking": booking_name,
             "custom_payment_purpose": purpose,
             "docstatus": 1},
            ["name", "outstanding_amount"],
            as_dict=True,
        )
        received[purpose] = bool(si) and flt(si.outstanding_amount) <= 0.01

    # Payment status — milestones take precedence; never override a terminal state
    current = frappe.db.get_value("Property Booking", booking_name, "status")
    if current not in ("Closed", "Cancelled"):
        if received["Down Payment"]:
            updates["status"] = "Down Payment Received"
        elif received["Booking Amount"]:
            updates["status"] = "Booking Amount Received"
        elif docstatus == 1:
            updates["status"] = "Confirmed"
        else:
            updates["status"] = "Draft"

    # Installment progress (percent)
    rows = frappe.get_all("PDC Schedule", filters={"parent": booking_name}, fields=["status"])
    active = [r for r in rows if r.status != "Cancelled"]
    if active:
        cleared = len([r for r in active if r.status == "Cleared"])
        updates["installment_progress"] = round(cleared / len(active) * 100, 1)

    frappe.db.set_value("Property Booking", booking_name, updates, update_modified=False)


def on_sales_invoice_change(doc, method=None):
    """doc_event hook — keep the booking's advance-payment status in sync."""
    booking = doc.get("custom_property_booking")
    if booking:
        update_booking_payment_status(booking)


def on_payment_entry_change(doc, method=None):
    """doc_event hook — recompute status for every booking touched by this PE,
    whether linked directly (property_booking) or via the invoices it pays."""
    bookings = set()
    if doc.get("property_booking"):
        bookings.add(doc.property_booking)
    for ref in (doc.get("references") or []):
        if ref.reference_doctype == "Sales Invoice" and ref.reference_name:
            b = frappe.db.get_value("Sales Invoice", ref.reference_name, "custom_property_booking")
            if b:
                bookings.add(b)
    for b in bookings:
        update_booking_payment_status(b)


@frappe.whitelist()
def make_advance_invoice(booking_name, purpose):
    """Create (as Draft) and return a Sales Invoice for the Booking Amount or
    Down Payment. If one already exists (draft or submitted), return it instead."""
    frappe.has_permission("Property Booking", "write", throw=True)
    if purpose not in ("Booking Amount", "Down Payment"):
        frappe.throw(_("Invalid payment purpose."))

    booking = frappe.get_doc("Property Booking", booking_name)

    existing = frappe.db.get_value(
        "Sales Invoice",
        {"custom_property_booking": booking_name,
         "custom_payment_purpose": purpose,
         "docstatus": ("<", 2)},
        "name",
        order_by="docstatus desc, creation desc",
    )
    if existing:
        return existing

    base = flt(booking.booking_amount) if purpose == "Booking Amount" else flt(booking.down_payment_amount)
    if base <= 0:
        frappe.throw(_("{0} is zero — nothing to invoice.").format(purpose))

    net, _tax, total = booking._get_unit_tax_breakdown(base)
    company = booking.company or frappe.defaults.get_user_default("company") or "Misk Real Estate"
    if purpose == "Booking Amount":
        invoice_date = booking.booking_date or today()
    else:
        invoice_date = booking.down_payment_date or booking.booking_date or today()
    row = frappe._dict({
        "schedule_row": "",
        "booking": booking_name,
        "cheque_date": invoice_date,
        "amount": total,
        "net_amount": net,
        "cheque_no": "",
        "installment_type": purpose,
        "customer": booking.customer,
        "unit": booking.unit,
        "company": company,
        "taxes_and_charges": booking.taxes_and_charges or "",
        "status": "Pending",
    })
    from misk_real_estate.pdc_management.cron.auto_invoice import _create_invoice
    si_name = _create_invoice(row, submit=False, payment_purpose=purpose)
    update_booking_payment_status(booking_name)
    return si_name


@frappe.whitelist()
def get_advance_invoice_status(booking_name):
    """Return submitted Sales Invoice names for Booking Amount and Down Payment.
    Used by JS to determine button state without storing link fields on the booking."""
    result = {}
    for purpose in ("Booking Amount", "Down Payment"):
        result[purpose] = frappe.db.get_value(
            "Sales Invoice",
            {"custom_property_booking": booking_name, "custom_payment_purpose": purpose, "docstatus": 1},
            "name",
        ) or None
    return result


@frappe.whitelist()
def make_advance_payment(booking_name, purpose):
    """Build (but DO NOT save) a Payment Entry against the submitted advance
    invoice. Returned as a dict so the UI opens it as a fresh, unsaved Payment
    Entry — the user picks the mode of payment and (for bank transfers) fills in
    the mandatory Reference No / Reference Date before submitting."""
    frappe.has_permission("Property Booking", "write", throw=True)
    booking = frappe.get_doc("Property Booking", booking_name)

    si_name = frappe.db.get_value(
        "Sales Invoice",
        {"custom_property_booking": booking_name, "custom_payment_purpose": purpose, "docstatus": 1},
        "name",
    )
    if not si_name:
        frappe.throw(_("No submitted {0} invoice found. Submit the invoice first.").format(purpose))

    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
    pe = get_payment_entry("Sales Invoice", si_name)
    pe.property_booking = booking_name
    pe.property_unit = booking.unit
    if booking.customer_bank_account:
        pe.party_bank_account = booking.customer_bank_account
    return pe.as_dict()


# ── Whitelisted API ───────────────────────────────────────────────────────────

@frappe.whitelist()
def regenerate_pdc_schedule(booking_name):
    """Clear and rebuild the PDC Schedule. Called from UI button."""
    frappe.has_permission("Property Booking", "write", throw=True)
    booking = frappe.get_doc("Property Booking", booking_name)
    if booking.docstatus != 0:
        frappe.throw(_("PDC Schedule can only be regenerated on a Draft booking."))
    booking.pdc_schedule = []
    booking.generate_pdc_schedule()
    booking.save(ignore_permissions=True)
    frappe.msgprint(_("PDC Schedule regenerated."), alert=True)


@frappe.whitelist()
def trigger_invoice_generation(booking_name):
    """Re-queue invoice generation for an All at Once booking (e.g. after initial job failure)."""
    frappe.has_permission("Property Booking", "write", throw=True)
    booking = frappe.get_doc("Property Booking", booking_name)
    if booking.docstatus != 1:
        frappe.throw(_("Booking must be submitted."))
    if booking.invoice_generation != "All at Once":
        frappe.throw(_("Invoice Generation mode is not 'All at Once' for this booking."))
    frappe.enqueue(
        method="misk_real_estate.real_estate.doctype.property_booking.property_booking.generate_invoices_for_booking",
        queue="default",
        timeout=600,
        enqueue_after_commit=True,
        job_name=f"gen_invoices_{booking_name}",
        booking_name=booking_name,
    )
    return True


@frappe.whitelist()
def create_pdc_entries(booking_name):
    """
    Create PDC Entry records for all Pending schedule rows.
    Called from UI button after booking is confirmed.
    PDC Entries track physical cheques — no GL until cleared (B7).
    """
    frappe.has_permission("Property Booking", "write", throw=True)

    booking = frappe.get_doc("Property Booking", booking_name)
    if booking.docstatus != 1:
        frappe.throw(_("Booking must be submitted before creating PDC Entries."))

    company = booking.company or frappe.defaults.get_user_default("company") or "Misk Real Estate"
    created = []
    for row in booking.pdc_schedule:
        if row.pdc_entry:
            continue  # already has an entry
        if not row.get("is_pdc"):
            continue  # non-PDC row — no cheque entry needed
        settings = frappe.get_cached_doc("Misk Real Estate Settings")
        entry = frappe.get_doc({
            "doctype": "PDC Entry",
            "cheque_no": row.cheque_no or f"TBC-{row.sequence_no}",
            "cheque_date": row.cheque_date,
            "amount": row.amount,
            "installment_type": row.installment_type or "",
            "mode_of_payment": getattr(settings, "pdc_payment_mode", None) or "",
            "customer": booking.customer,
            "customer_bank_account": booking.customer_bank_account or "",
            "building": booking.building,
            "unit": booking.unit,
            "booking": booking_name,
            "company": company,
            "sales_invoice": row.sales_invoice or "",
            "status": "Pending",
        })
        entry.insert(ignore_permissions=True)
        frappe.db.set_value("PDC Schedule", row.name, "pdc_entry", entry.name)
        created.append(entry.name)

    frappe.db.commit()
    frappe.msgprint(
        _("{0} PDC Entries created for booking {1}.").format(len(created), booking_name),
        alert=True,
    )
    return created


def generate_invoices_for_booking(booking_name):
    """
    Background worker: create Sales Invoices for all PDC schedule rows
    in a booking (All at Once mode).
    posting_date = booking.booking_date, due_date = row.cheque_date.
    """
    from frappe.utils import add_days, formatdate
    booking = frappe.get_doc("Property Booking", booking_name)
    company = booking.company or frappe.defaults.get_user_default("company") or "Misk Real Estate"
    settings = frappe.get_cached_doc("Misk Real Estate Settings")
    oa_item = getattr(settings, "oa_fee_item", None)

    for row in booking.pdc_schedule:
        if row.sales_invoice:
            continue  # already has SI
        if row.status in ("Cancelled",):
            continue

        # Use OA-FEE item for OA rows, unit item for all others
        item_code = (oa_item if row.installment_type == "Owners Association Fee" and oa_item
                     else booking.unit or _get_or_create_default_item(company))
        type_label = row.installment_type or "Installment"
        description = f"{type_label} — Cheque {row.cheque_no or 'TBC'} — Due {formatdate(row.cheque_date)}"

        from misk_real_estate.pdc_management.cron.auto_invoice import (
            _invoice_item_rate, _build_tax_rows_from_item_template
        )
        taxes_and_charges = booking.taxes_and_charges or ""
        if taxes_and_charges:
            rate = _invoice_item_rate(
                frappe._dict(amount=row.amount, net_amount=row.net_amount),
                taxes_and_charges,
            )
            tax_rows = []
        else:
            tax_rows = _build_tax_rows_from_item_template(item_code)
            rate = flt(row.net_amount or row.amount) if tax_rows else flt(row.amount)

        posting_date = getdate(booking.booking_date)
        due_date = max(posting_date, getdate(row.cheque_date)) if row.cheque_date else posting_date

        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": booking.customer,
            "company": company,
            "posting_date": posting_date,
            "due_date": due_date,
            "taxes_and_charges": taxes_and_charges,
            "taxes": tax_rows,
            "items": [{
                "item_code": item_code,
                "qty": 1,
                "rate": rate,
                "description": description,
            }],
            "custom_pdc_schedule_row": row.name,
            "custom_property_booking": booking_name,
            "custom_payment_purpose": row.installment_type or "Installment",
        })
        si.flags.ignore_permissions = True
        si.insert()  # Draft — finance reviews and submits manually

        # Link SI to PDC Schedule row and PDC Entry
        frappe.db.set_value("PDC Schedule", row.name, "sales_invoice", si.name)
        if row.pdc_entry:
            frappe.db.set_value("PDC Entry", row.pdc_entry, "sales_invoice", si.name)

    frappe.db.commit()
    frappe.logger().info(f"generate_invoices_for_booking: completed for {booking_name}")


@frappe.whitelist()
def create_missing_invoices(booking_name):
    """
    Manually create Sales Invoices (as Draft) for all PDC Schedule rows
    that don't yet have one. Allows recovery when auto-creation failed,
    or lets user create invoices manually before the cron runs.
    Invoices are saved as Draft — user must submit them after review.
    """
    frappe.has_permission("Property Booking", "write", throw=True)
    booking = frappe.get_doc("Property Booking", booking_name)
    if booking.docstatus != 1:
        frappe.throw(_("Booking must be submitted."))

    from misk_real_estate.pdc_management.cron.auto_invoice import (
        _invoice_item_rate, _build_tax_rows_from_item_template
    )
    from frappe.utils import formatdate

    company = booking.company or frappe.defaults.get_user_default("company") or "Misk Real Estate"
    settings = frappe.get_cached_doc("Misk Real Estate Settings")
    oa_item = getattr(settings, "oa_fee_item", None)
    taxes_and_charges = booking.taxes_and_charges or ""

    created = []
    for row in booking.pdc_schedule:
        if row.sales_invoice or row.status == "Cancelled":
            continue

        item_code = (oa_item if row.installment_type == "Owners Association Fee" and oa_item
                     else booking.unit or _get_or_create_default_item(company))

        if taxes_and_charges:
            rate = _invoice_item_rate(
                frappe._dict(amount=row.amount, net_amount=row.net_amount),
                taxes_and_charges,
            )
            tax_rows = []
        else:
            tax_rows = _build_tax_rows_from_item_template(item_code)
            rate = flt(row.net_amount or row.amount) if tax_rows else flt(row.amount)

        posting_date = getdate(today())
        due_date = max(posting_date, getdate(row.cheque_date)) if row.cheque_date else posting_date
        description = (f"{row.installment_type or 'Installment'} — "
                       f"Cheque {row.cheque_no or 'TBC'} — Due {formatdate(row.cheque_date)}")

        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": booking.customer,
            "company": company,
            "posting_date": posting_date,
            "due_date": due_date,
            "taxes_and_charges": taxes_and_charges,
            "taxes": tax_rows,
            "items": [{
                "item_code": item_code,
                "qty": 1,
                "rate": rate,
                "description": description,
            }],
            "custom_pdc_schedule_row": row.name,
            "custom_property_booking": booking_name,
            "custom_payment_purpose": row.installment_type or "Installment",
        })
        si.flags.ignore_permissions = True
        si.insert()  # Draft — user reviews and submits manually
        frappe.db.set_value("PDC Schedule", row.name, "sales_invoice", si.name)
        if row.pdc_entry:
            frappe.db.set_value("PDC Entry", row.pdc_entry, "sales_invoice", si.name)
        created.append(si.name)

    frappe.db.commit()
    if not created:
        frappe.msgprint(_("All rows already have a Sales Invoice."), alert=True)
    else:
        frappe.msgprint(
            _("{0} draft Sales Invoice(s) created: {1}. Review and submit them from the Sales Invoices list.").format(
                len(created), ", ".join(created)
            ),
            title=_("Invoices Created (Draft)"),
        )
    return created


def _get_or_create_default_item(company):
    """Fallback item for invoice lines when unit item not usable."""
    item = frappe.db.get_value("Item", {"item_name": "Real Estate Installment", "disabled": 0}, "name")
    if item:
        return item
    i = frappe.get_doc({
        "doctype": "Item",
        "item_code": "RE-INSTALLMENT",
        "item_name": "Real Estate Installment",
        "item_group": "Services",
        "is_sales_item": 1,
        "is_purchase_item": 0,
        "is_stock_item": 0,
    })
    i.insert(ignore_permissions=True)
    return i.name


@frappe.whitelist()
def mark_unit_sold(booking_name):
    """
    Mark unit as Sold once full payment is received.
    Called manually from UI — finance confirms final PDC cleared.
    """
    frappe.has_permission("Property Booking", "write", throw=True)
    booking = frappe.get_doc("Property Booking", booking_name)
    if booking.docstatus != 1:
        frappe.throw(_("Booking must be submitted."))

    # Check all PDC schedule rows are Cleared
    pending = [r for r in booking.pdc_schedule if r.status not in ("Cleared", "Cancelled")]
    if pending:
        frappe.throw(
            _("{0} PDC schedule rows are not yet Cleared. Cannot mark unit as Sold.").format(
                len(pending)
            )
        )

    frappe.db.set_value("Item", booking.unit, "unit_status", "Sold")
    frappe.db.set_value("Property Booking", booking_name, "status", "Closed")
    frappe.msgprint(_("Unit {0} marked as Sold.").format(booking.unit), alert=True)


@frappe.whitelist()
def mark_lost(booking_name):
    """Mark a Draft booking as Lost and release its reserved unit.
    Only for drafts — submitted bookings are released via Cancel instead."""
    frappe.has_permission("Property Booking", "write", throw=True)
    booking = frappe.get_doc("Property Booking", booking_name)
    if booking.docstatus != 0:
        frappe.throw(_("Only a Draft booking can be marked Lost. Cancel a submitted booking instead."))

    # Release the unit if this booking is the only one holding it
    if booking.unit:
        current = frappe.db.get_value("Item", booking.unit, "unit_status")
        if current == "Reserved" and not booking._unit_reserved_by_other():
            frappe.db.set_value("Item", booking.unit, "unit_status", "Available")

    # Set terminal status directly (db_set avoids re-running validate / re-reserving)
    frappe.db.set_value("Property Booking", booking_name, "status", "Lost")
    frappe.msgprint(_("Booking marked Lost. Unit {0} released.").format(booking.unit or ""), alert=True)


@frappe.whitelist()
def resolve_customer_for_quotation(quotation_name):
    """Return (and auto-create if needed) the Customer for a Quotation.
    Converts Lead → Customer automatically when party_type is Lead."""
    quotation = frappe.get_doc("Quotation", quotation_name)
    if quotation.quotation_to == "Lead":
        return _get_or_create_customer_from_lead(quotation.party_name)
    return quotation.party_name


@frappe.whitelist()
def create_bookings_from_quotation(quotation_name, item_name=None):
    """
    Create a Property Booking for one specific Quotation line (item_name).
    If item_name is None, creates for all remaining unconverted lines.
    """
    frappe.has_permission("Quotation", "read", throw=True)
    frappe.has_permission("Property Booking", "create", throw=True)

    quotation = frappe.get_doc("Quotation", quotation_name)

    if quotation.workflow_state != "Confirmed":
        frappe.throw(_("Quotation must be fully approved before creating bookings."))

    # Resolve or create customer
    if quotation.quotation_to == "Lead":
        customer = _get_or_create_customer_from_lead(quotation.party_name)
    else:
        customer = quotation.party_name

    company = quotation.company or frappe.defaults.get_user_default("company") or "Misk Real Estate"
    payment_plan = quotation.get("payment_plan") or ""
    price_list = quotation.selling_price_list or ""

    # Get OA fee item to exclude from booking creation
    settings = frappe.get_cached_doc("Misk Real Estate Settings")
    oa_item = getattr(settings, "oa_fee_item", None)

    created = []
    skipped = []

    # Filter: specific row if provided, skip already-converted and OA fee lines
    items_to_process = [
        item for item in quotation.items
        if (not item_name or item.name == item_name)
        and not item.get("property_booking")
        and item.item_code != oa_item
    ]

    for item in items_to_process:
        unit = item.item_code
        unit_status = frappe.db.get_value("Item", unit, "unit_status")
        if unit_status != "Available":
            skipped.append(f"{unit} ({unit_status})")
            continue

        booking_amount = flt(item.get("booking_amount") or 0)
        if not booking_amount:
            frappe.throw(
                _("Booking Amount is missing for unit {0} (row {1}). Please fill it in the Quotation items table.").format(
                    unit, item.idx
                )
            )

        building = frappe.db.get_value("Item", unit, "item_group") or item.get("building") or ""

        dp_pct = flt(item.get("down_payment_percentage") or 0)
        oa_fee = flt(item.get("owners_association_fee") or 0)

        # Per-item payment_plan and price_list override quotation header
        item_payment_plan = item.get("payment_plan") or payment_plan
        item_price_list   = item.get("price_list")   or price_list

        # Tax: add non-print-rate taxes proportionally to unit price
        unit_price = _effective_unit_price(quotation, item)

        booking = frappe.get_doc({
            "doctype": "Property Booking",
            "customer": customer,
            "quotation": quotation_name,
            "building": building,
            "unit": unit,
            "unit_price": unit_price,
            "booking_amount": booking_amount,
            "owners_association_fee": oa_fee,
            "taxes_and_charges": quotation.taxes_and_charges or _get_default_taxes(company),
            "payment_plan": item_payment_plan,
            "price_list": item_price_list,
            "down_payment_percentage": dp_pct or None,
            "booking_date": today(),
            "company": company,
            "invoice_generation": "Monthly",
            "status": "Draft",
        })
        booking.flags.ignore_permissions = True
        booking.insert()
        # Link booking back to this Quotation Item row
        frappe.db.set_value("Quotation Item", item.name, "property_booking", booking.name)
        created.append(booking.name)

    # Mark Quotation as Ordered only when all lines are converted
    all_converted = all(
        frappe.db.get_value("Quotation Item", r.name, "property_booking")
        for r in quotation.items
    )
    if all_converted:
        frappe.db.set_value("Quotation", quotation_name, "status", "Ordered")

    msg_parts = [_("{0} Property Booking(s) created: {1}").format(len(created), ", ".join(created))]
    if skipped:
        msg_parts.append(_("Skipped (not Available): {0}").format(", ".join(skipped)))

    frappe.msgprint("<br>".join(msg_parts), title=_("Property Bookings Created"))
    return created


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_price_lists_for_unit(doctype, txt, searchfield, start, page_len, filters):
    """Return Price Lists that have at least one Item Price for the given unit."""
    unit = (filters or {}).get("unit") or ""
    if not unit:
        return []
    return frappe.db.sql("""
        SELECT DISTINCT ip.price_list, pl.name
        FROM `tabItem Price` ip
        JOIN `tabPrice List` pl ON pl.name = ip.price_list
        WHERE ip.item_code = %(unit)s
          AND pl.selling = 1
          AND pl.enabled = 1
          AND ip.price_list LIKE %(txt)s
        LIMIT %(page_len)s OFFSET %(start)s
    """, {"unit": unit, "txt": f"%{txt}%", "page_len": page_len, "start": start})


def _item_tax_rate(parent):
    """Return sum of tax rates from an Item Tax Template linked to parent (Item or Item Group).
    Returns None if no template is defined, 0.0 if template exists but rate is 0.
    """
    item_tax_template = frappe.db.get_value("Item Tax", {"parent": parent}, "item_tax_template")
    if not item_tax_template:
        return None
    rate_rows = frappe.db.get_all(
        "Item Tax Template Detail",
        filters={"parent": item_tax_template},
        fields=["tax_rate"],
    )
    return sum(flt(r.tax_rate) for r in rate_rows)


def _get_default_taxes(company):
    """Return the default Sales Taxes and Charges Template (is_default=1) for company."""
    return frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"is_default": 1, "company": company},
        "name"
    ) or ""


@frappe.whitelist()
def get_tax_rate_from_template(taxes_and_charges, unit=None):
    """Return the effective tax rate for the unit.
    Priority: taxes_and_charges template → unit Item Tax Template → item group Item Tax Template.
    """
    if taxes_and_charges:
        rows = frappe.db.get_all(
            "Sales Taxes and Charges",
            filters={"parent": taxes_and_charges, "parenttype": "Sales Taxes and Charges Template"},
            fields=["rate", "charge_type"],
        )
        return sum(flt(r.rate) for r in rows if r.charge_type in ("On Net Total", "On Previous Row Total"))

    if unit:
        rate = _item_tax_rate(unit)
        if rate is None:
            item_group = frappe.db.get_value("Item", unit, "item_group")
            if item_group:
                rate = _item_tax_rate(item_group)
        if rate:
            return rate

    return 0


@frappe.whitelist()
def get_default_taxes_for_company(company):
    """Whitelisted: used by JS to fetch default tax template (is_default=1)."""
    return frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"is_default": 1, "company": company},
        "name"
    ) or ""


def _effective_unit_price(quotation, item):
    """
    Return item rate + proportional share of any non-included taxes.
    If a tax row has included_in_print_rate = True, the rate already contains it.
    If included_in_print_rate = False, we add the proportional tax on top.
    """
    base_rate = flt(item.rate)
    total = flt(quotation.total) or 1
    item_amount = flt(item.amount) or 0
    qty = flt(item.qty) or 1

    if not quotation.get("taxes"):
        return base_rate

    extra_tax = 0
    for tax in quotation.taxes:
        if not tax.included_in_print_rate:
            extra_tax += (item_amount / total) * flt(tax.tax_amount)

    return round(base_rate + extra_tax / qty, 3)


def _get_or_create_customer_from_lead(lead_name):
    """Convert a Lead to Customer using ERPNext standard mapper, or return existing."""
    # Check if Customer already linked to this lead
    existing = frappe.db.get_value("Customer", {"lead_name": lead_name}, "name")
    if existing:
        return existing

    # Also check lead.customer (set by ERPNext when lead is already converted)
    lead_customer = frappe.db.get_value("Lead", lead_name, "customer")
    if lead_customer and frappe.db.exists("Customer", lead_customer):
        return lead_customer

    try:
        from erpnext.crm.doctype.lead.lead import _make_customer
        customer_doc = _make_customer(lead_name, ignore_permissions=True)
        customer_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return customer_doc.name
    except Exception as e:
        frappe.throw(
            _("Could not convert Lead {0} to Customer: {1}. "
              "Please create the Customer manually and re-link the Quotation to them.").format(
                lead_name, str(e)
            )
        )
