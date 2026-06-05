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
        self._compute_and_validate_total()
        # Generate PDC schedule only on first save — never overwrite after that.
        # Use "Regenerate PDC Schedule" button to rebuild manually if needed.
        if self.docstatus == 0 and not self.pdc_schedule \
                and self.unit_price and self.booking_amount and self.payment_plan:
            self.generate_pdc_schedule()

    def before_submit(self):
        self.status = "Confirmed"
        self.validate_payment_plan()
        # Generate if somehow still empty (e.g. created programmatically)
        if not self.pdc_schedule:
            self.generate_pdc_schedule()

    def on_submit(self):
        self._set_unit_status("Booked")
        # Always create SIs immediately for Booking Amount and Down Payment
        self._create_upfront_invoices()
        # Installments follow invoice_generation setting
        if self.invoice_generation == "All at Once":
            self._generate_all_invoices_now()

    def _create_upfront_invoices(self):
        """Create Sales Invoices immediately on submit for Booking Amount and Down Payment rows."""
        from misk_real_estate.pdc_management.cron.auto_invoice import _create_invoice
        company = self.company or frappe.defaults.get_user_default("company") or "Misk Real Estate"
        for row in self.pdc_schedule:
            if row.installment_type in ("Booking Amount", "Down Payment") and not row.sales_invoice:
                try:
                    row_data = frappe._dict({
                        "schedule_row": row.name,
                        "booking": self.name,
                        "cheque_date": row.cheque_date or today(),
                        "amount": row.amount,
                        "cheque_no": row.cheque_no or "",
                        "installment_type": row.installment_type,
                        "customer": self.customer,
                        "unit": self.unit,
                        "company": company,
                        "status": row.status,
                    })
                    si_name = _create_invoice(row_data)
                    frappe.db.set_value("PDC Schedule", row.name, "sales_invoice", si_name)
                except Exception:
                    frappe.log_error(frappe.get_traceback(),
                        f"Upfront SI failed: {row.installment_type} — {self.name}")

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
        dp_amount = flt(self.down_payment_amount)
        dp_pct = flt(self.down_payment_percentage)

        if dp_amount > 0:
            # Amount entered — back-calculate % against full unit_price
            self.down_payment_percentage = round(dp_amount / unit_price * 100, 3)
        elif dp_pct > 0:
            # Percentage entered — calculate amount against full unit_price
            self.down_payment_amount = round(unit_price * dp_pct / 100, 3)
        else:
            # Neither set — default to 50% of unit_price
            self.down_payment_percentage = 50
            self.down_payment_amount = round(unit_price * 0.50, 3)

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

        plan_doc = frappe.db.get_value(
            "Payment Plan", self.payment_plan,
            ["number_of_installments", "is_full_payment"], as_dict=True
        ) if self.payment_plan else None
        is_full = (not plan_doc) or plan_doc.is_full_payment or not plan_doc.number_of_installments

        if is_full:
            # Full payment — one more row for balance
            balance = flt(self.unit_price) - flt(self.booking_amount)
            if balance > 0:
                settings = frappe.get_cached_doc("Misk Real Estate Settings")
                dp_days = cint(settings.down_payment_days) or 2
                self.append("pdc_schedule", {
                    "sequence_no": seq,
                    "installment_type": "Down Payment",
                    "cheque_date": add_days(booking_date, dp_days),
                    "amount": balance,
                    "status": "Pending",
                })
                seq += 1
            # OA fee for full payment — default date = balance cheque date
            if flt(self.owners_association_fee) > 0:
                self.append("pdc_schedule", {
                    "sequence_no": seq,
                    "installment_type": "Owners Association Fee",
                    "cheque_date": add_days(booking_date, dp_days),
                    "amount": flt(self.owners_association_fee),
                    "status": "Pending",
                })
            return

        # 2. Down Payment row
        settings = frappe.get_cached_doc("Misk Real Estate Settings")
        dp_days = cint(settings.down_payment_days) or 2
        dp_date = add_days(booking_date, dp_days)
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

        # 4. Owners Association Fee row — default date = last installment date
        if flt(self.owners_association_fee) > 0:
            last_inst_date = add_months(booking_date, n)
            self.append("pdc_schedule", {
                "sequence_no": seq,
                "installment_type": "Owners Association Fee",
                "cheque_date": last_inst_date,
                "amount": flt(self.owners_association_fee),
                "status": "Pending",
            })

    def _compute_and_validate_total(self):
        self.total_amount = flt(self.unit_price) + flt(self.owners_association_fee)
        if self.pdc_schedule:
            schedule_total = sum(flt(r.amount) for r in self.pdc_schedule)
            diff = abs(schedule_total - self.total_amount)
            if diff > 0.01:
                frappe.msgprint(
                    _("PDC Schedule total ({0} OMR) does not match Unit Price + OA Fee ({1} OMR). "
                      "Difference: {2} OMR.").format(
                        round(schedule_total, 3),
                        round(self.total_amount, 3),
                        round(diff, 3),
                    ),
                    title=_("Amount Mismatch"),
                    indicator="orange",
                )

    def _update_schedule_amounts(self):
        """
        Recalculate amounts for header rows only.
        Installment rows are left untouched so user can manually adjust
        individual amounts (e.g. last installment as rounding remainder).
        """
        amount_map = {
            "Booking Amount":         flt(self.booking_amount),
            "Down Payment":           flt(self.down_payment_amount),
            "Owners Association Fee": flt(self.owners_association_fee),
        }
        for row in self.pdc_schedule:
            new_amount = amount_map.get(row.installment_type)
            if new_amount is not None:
                row.amount = new_amount

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
        entry = frappe.get_doc({
            "doctype": "PDC Entry",
            "cheque_no": row.cheque_no or f"TBC-{row.sequence_no}",
            "cheque_date": row.cheque_date,
            "amount": row.amount,
            "customer": booking.customer,
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
def create_bookings_from_quotation(quotation_name):
    """
    Create one Property Booking per line item in an approved Quotation.
    If party_type is Lead, converts Lead to Customer first.
    Called from the Quotation form "Create Property Booking" button.
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

    created = []
    skipped = []

    for item in quotation.items:
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
            "payment_plan": payment_plan,
            "price_list": price_list,
            "down_payment_percentage": dp_pct or None,
            "booking_date": today(),
            "company": company,
            "invoice_generation": "Monthly",
            "status": "Draft",
        })
        booking.flags.ignore_permissions = True
        booking.insert()
        created.append(booking.name)

    # Mark Quotation as Ordered
    if created:
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
    # Check if customer already exists for this lead
    existing = frappe.db.get_value("Customer", {"lead_name": lead_name}, "name")
    if existing:
        return existing

    from erpnext.crm.doctype.lead.lead import make_customer
    customer_doc = make_customer(lead_name)
    customer_doc.flags.ignore_permissions = True
    customer_doc.insert()
    return customer_doc.name
