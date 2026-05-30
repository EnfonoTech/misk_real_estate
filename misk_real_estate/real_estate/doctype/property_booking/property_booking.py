# apps/misk_real_estate/misk_real_estate/real_estate/doctype/property_booking/property_booking.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, cstr, today, add_days, add_months, getdate


class PropertyBooking(Document):
    def validate(self):
        self.calculate_payment_schedule()
        self.validate_duplicate_booking()
        self._check_unit_availability()

    def before_submit(self):
        if self.status == "Draft":
            self.status = "Confirmed"
        self.validate_payment_plan()   # strict check only at submit
        self.generate_pdc_schedule()

    def on_submit(self):
        self._set_unit_status("Booked")
        if self.invoice_generation == "All at Once":
            self._generate_all_invoices_now()

    def on_cancel(self):
        self.status = "Cancelled"
        self._cancel_pdc_entries()
        self._set_unit_status("Available")

    # ── Validation ────────────────────────────────────────────────────────────

    def _check_unit_availability(self):
        """Block booking if unit_status is Sold or Booked (from Item custom field)."""
        if not self.unit:
            return
        unit_status = frappe.db.get_value("Item", self.unit, "unit_status")
        if unit_status in ("Sold", "Booked", "Reserved"):
            # Allow edit on existing submitted booking (re-validate after submit)
            if self.docstatus == 1:
                return
            frappe.throw(
                _("Unit {0} is currently {1} and cannot be booked.").format(
                    self.unit, unit_status
                )
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

    def validate_payment_plan(self):
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

        plan = cstr(self.payment_plan)
        if "12M" in plan:
            self.number_of_installments = 12
        elif "24M" in plan:
            self.number_of_installments = 24
        elif "36M" in plan:
            self.number_of_installments = 36
        else:
            # Full Payment — no down payment, no installments
            self.number_of_installments = 0
            self.down_payment_percentage = 0
            self.down_payment_amount = 0
            self.monthly_installment = 0
            return

        remaining = unit_price - booking_amount
        # down_payment_type is Check: 1 = Fixed Amount, 0 = Percentage
        if cint(self.down_payment_type):
            dp_amount = flt(self.down_payment_amount)
            if not dp_amount:
                dp_amount = round(remaining * 0.50, 3)
                self.down_payment_amount = dp_amount
            # Back-calculate percentage for reference
            if remaining > 0:
                self.down_payment_percentage = round(dp_amount / remaining * 100, 3)
        else:
            # Percentage mode
            dp_pct = flt(self.down_payment_percentage)
            if not dp_pct:
                dp_pct = 50
                self.down_payment_percentage = dp_pct
            self.down_payment_amount = round(remaining * dp_pct / 100, 3)

        after_dp = remaining - flt(self.down_payment_amount)
        n = cint(self.number_of_installments)
        if n > 0 and after_dp > 0:
            self.monthly_installment = round(after_dp / n, 3)

    # ── PDC Schedule generation (A7) ─────────────────────────────────────────

    def generate_pdc_schedule(self):
        """
        Populate pdc_schedule child table on submission.
        Creates rows for:
          1. Booking Amount
          2. Down Payment (if installment plan)
          3. Monthly Installments (n rows)
        No GL, no Payment Entry — only the plan (B7 requirement).
        """
        if self.pdc_schedule:
            # Already generated (e.g. amendment)
            return

        booking_date = getdate(self.booking_date)
        seq = 1

        # 1. Booking Amount row
        self.append("pdc_schedule", {
            "sequence_no": seq,
            "installment_type": "Booking Amount",
            "cheque_date": booking_date,
            "amount": flt(self.booking_amount),
            "status": "Pending",
        })
        seq += 1

        plan = cstr(self.payment_plan)
        if "Full" in plan:
            # Full payment — one more row for balance
            balance = flt(self.unit_price) - flt(self.booking_amount)
            if balance > 0:
                self.append("pdc_schedule", {
                    "sequence_no": seq,
                    "installment_type": "Down Payment",
                    "cheque_date": add_days(booking_date, 7),
                    "amount": balance,
                    "status": "Pending",
                })
            return

        # 2. Down Payment row
        dp_date = add_days(booking_date, 7)
        self.append("pdc_schedule", {
            "sequence_no": seq,
            "installment_type": "Down Payment",
            "cheque_date": dp_date,
            "amount": flt(self.down_payment_amount),
            "status": "Pending",
        })
        seq += 1

        # 3. Monthly installment rows
        n = cint(self.number_of_installments)
        for i in range(1, n + 1):
            inst_date = add_months(booking_date, i)
            self.append("pdc_schedule", {
                "sequence_no": seq,
                "installment_type": "Installment",
                "cheque_date": inst_date,
                "amount": flt(self.monthly_installment),
                "status": "Pending",
            })
            seq += 1

    def _cancel_pdc_entries(self):
        """Cancel linked PDC Entries that haven't been cleared."""
        pdc_entries = frappe.get_all(
            "PDC Entry",
            filters={"booking": self.name, "status": ("not in", ["Cleared", "Bounced"])},
            fields=["name", "status"],
        )
        for entry in pdc_entries:
            frappe.db.set_value("PDC Entry", entry.name, "status", "Cancelled")


# ── Whitelisted API ───────────────────────────────────────────────────────────

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

    created = []
    for row in booking.pdc_schedule:
        if row.pdc_entry:
            continue  # already has an entry
        entry = frappe.get_doc({
            "doctype": "PDC Entry",
            "cheque_no": row.cheque_no or f"TBC-{row.sequence_no}",
            "cheque_date": row.cheque_date,
            "amount": row.amount,
            "customer": booking.customer,
            "building": booking.building,
            "unit": booking.unit,
            "booking": booking_name,
            "company": frappe.defaults.get_user_default("company") or "Misk Real Estate",
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
    company = frappe.defaults.get_user_default("company") or "Misk Real Estate"

    for row in booking.pdc_schedule:
        if row.sales_invoice:
            continue  # already has SI
        if row.status in ("Cancelled",):
            continue

        item_code = booking.unit or _get_or_create_default_item(company)
        type_label = row.installment_type or "Installment"
        description = f"{type_label} — Cheque {row.cheque_no or 'TBC'} — Due {formatdate(row.cheque_date)}"

        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": booking.customer,
            "company": company,
            "posting_date": booking.booking_date,   # posting = booking date
            "due_date": row.cheque_date,             # due = cheque date
            "items": [{
                "item_code": item_code,
                "qty": 1,
                "rate": flt(row.amount),
                "description": description,
            }],
            "custom_pdc_schedule_row": row.name,
            "custom_property_booking": booking_name,
        })
        si.flags.ignore_permissions = True
        si.insert()
        si.submit()

        # Link SI to PDC Schedule row and PDC Entry
        frappe.db.set_value("PDC Schedule", row.name, "sales_invoice", si.name)
        if row.pdc_entry:
            frappe.db.set_value("PDC Entry", row.pdc_entry, "sales_invoice", si.name)

    frappe.db.commit()
    frappe.logger().info(f"generate_invoices_for_booking: completed for {booking_name}")


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
    frappe.db.set_value("Property Booking", booking_name, "status", "Converted")
    frappe.msgprint(_("Unit {0} marked as Sold.").format(booking.unit), alert=True)


@frappe.whitelist()
def create_sales_order(booking_name):
    """Create a Sales Order from a confirmed Property Booking (A6)."""
    frappe.has_permission("Property Booking", "write", throw=True)

    booking = frappe.get_doc("Property Booking", booking_name)
    if booking.status == "Converted" and booking.sales_order:
        frappe.throw(_("Sales Order already created: {0}").format(booking.sales_order))
    if booking.status == "Cancelled":
        frappe.throw(_("Cannot create Sales Order from a cancelled booking."))
    if booking.docstatus != 1:
        frappe.throw(_("Submit the booking first."))

    company = frappe.defaults.get_user_default("company") or "Misk Real Estate"
    so = frappe.get_doc({
        "doctype": "Sales Order",
        "customer": booking.customer,
        "company": company,
        "transaction_date": today(),
        "delivery_date": add_months(today(), 1),
        "items": [{
            "item_code": booking.unit,
            "qty": 1,
            "rate": flt(booking.unit_price),
        }],
    })
    so.insert(ignore_permissions=True)
    so.submit()

    frappe.db.set_value("Property Booking", booking_name, {
        "sales_order": so.name,
        "status": "Converted",
    })
    frappe.msgprint(_("Sales Order {0} created.").format(so.name), alert=True)
    return so.name
