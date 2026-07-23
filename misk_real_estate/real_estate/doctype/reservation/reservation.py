# apps/misk_real_estate/misk_real_estate/real_estate/doctype/reservation/reservation.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, today

DEFAULT_VALIDITY_DAYS = 15
TERMINAL_STATUSES = ("Rejected", "Expired", "Cancelled", "Converted to Booking")


class Reservation(Document):
    def validate(self):
        self._set_default_sales_person()
        self._set_reservation_validity_date()
        self._validate_duplicate_rows()
        self._check_units_availability()
        self._calculate_taxes_and_totals()
        self._sync_status()

    def before_submit(self):
        if not self.items:
            frappe.throw(_("At least one unit is required."))
        for row in self.items:
            if not row.selling_price or flt(row.selling_price) <= 0:
                frappe.throw(_("Row {0}: Selling Price is required and must be greater than zero.").format(row.idx))

    def on_submit(self):
        """GM Approval moves docstatus 0 -> 1. Units are reserved only now —
        Draft / Pending GM Approval no longer locks the Item itself; concurrent
        reservations are still blocked by _check_units_availability's
        _unit_held_by_other lookup, independent of the Item's own unit_status."""
        for row in self.items:
            self._set_unit_status(row.unit, "Reserved")

    def on_cancel(self):
        self.status = "Cancelled"
        self._release_units_if_unclaimed()

    def on_trash(self):
        if self.docstatus == 0:
            self._release_units_if_unclaimed()

    # ── Validation / calculated fields ──────────────────────────────────────

    def _set_reservation_validity_date(self):
        """Default validity date from reservation_date + validity_days. Only fills
        it in when blank so a manager can override it after the fact."""
        if self.reservation_date and not self.reservation_validity_date:
            days = cint(self.validity_days) or DEFAULT_VALIDITY_DAYS
            self.reservation_validity_date = add_days(getdate(self.reservation_date), days)

    def _validate_duplicate_rows(self):
        seen = set()
        for row in self.items:
            if not row.unit:
                continue
            if row.unit in seen:
                frappe.throw(_("Row {0}: Unit {1} is listed more than once.").format(row.idx, row.unit))
            seen.add(row.unit)

    def _check_units_availability(self):
        """Block reserving a unit that is Sold/Booked, or already held by another
        active Reservation / Property Booking. Checked regardless of this unit's
        own unit_status, since a Draft/Pending GM Approval reservation no longer
        flips that field itself (only on_submit does) — without this, a second
        Draft reservation for the same still-"Available"-flagged unit would slip
        through."""
        if self.docstatus == 1:
            return
        for row in self.items:
            if not row.unit:
                continue
            unit_status = frappe.db.get_value("Item", row.unit, "unit_status")
            if unit_status in ("Sold", "Booked"):
                frappe.throw(
                    _("Row {0}: Unit {1} is currently {2} and cannot be reserved.").format(
                        row.idx, row.unit, unit_status
                    )
                )
            other = self._unit_held_by_other(row.unit)
            if other:
                frappe.throw(
                    _("Row {0}: Unit {1} is already held by another active Reservation/Booking ({2}).").format(
                        row.idx, row.unit, other
                    )
                )

    def _calculate_taxes_and_totals(self):
        """Sum unit selling prices into `total`, then apply the taxes table on top,
        row by row, the same way Quotation's tax table works (row_id references an
        earlier row for "On Previous Row" charge types). Rates are always exclusive
        here — Selling Price is the pre-tax base, so included_in_print_rate is not
        supported."""
        self.total = flt(
            sum(flt(row.selling_price) + flt(row.owners_association_fee) for row in self.items), 3
        )

        running_total = flt(self.total)
        for i, row in enumerate(self.taxes):
            if row.charge_type == "Actual":
                tax_amount = flt(row.tax_amount)
            elif row.charge_type == "On Net Total":
                tax_amount = flt(self.total) * flt(row.rate) / 100
            elif row.charge_type in ("On Previous Row Amount", "On Previous Row Total"):
                ref_idx = cint(row.row_id) - 1
                if ref_idx < 0 or ref_idx >= i:
                    frappe.throw(
                        _("Row {0}: Invalid reference row for {1}.").format(row.idx, row.charge_type)
                    )
                ref_row = self.taxes[ref_idx]
                base = flt(ref_row.tax_amount) if row.charge_type == "On Previous Row Amount" else flt(ref_row.total)
                tax_amount = base * flt(row.rate) / 100
            else:
                tax_amount = 0.0

            running_total = flt(running_total + tax_amount, 3)
            row.tax_amount = flt(tax_amount, 3)
            row.total = running_total

        self.total_taxes_and_charges = flt(running_total - flt(self.total), 3)
        self.grand_total = running_total

    def _unit_held_by_other(self, unit):
        """Name of another active Reservation or Property Booking holding this unit."""
        other_reservation = frappe.db.sql(
            """
            SELECT ri.parent
            FROM `tabReservation Item` ri
            INNER JOIN `tabReservation` r ON r.name = ri.parent
            WHERE ri.unit = %(unit)s
              AND ri.parent != %(name)s
              AND r.status NOT IN %(terminal)s
              AND r.docstatus < 2
            LIMIT 1
            """,
            {"unit": unit, "name": self.name or "", "terminal": TERMINAL_STATUSES},
        )
        if other_reservation:
            return other_reservation[0][0]
        # unit lives on Property Booking's child table (Property Booking Unit), not
        # the parent doctype — resolve via the shared helper there.
        from misk_real_estate.real_estate.doctype.property_booking.property_booking import (
            get_active_booking_for_unit,
        )
        return get_active_booking_for_unit(unit)

    def _sync_status(self):
        """Business status mirrors the approval workflow_state (Draft / Pending GM
        Approval / Approved / Rejected). Expired, Cancelled and Converted to
        Booking are applied outside the workflow (auto-release job, on_cancel,
        Property Booking creation) — never overwrite those here."""
        if self.status in ("Expired", "Cancelled", "Converted to Booking"):
            return
        if self.workflow_state:
            self.status = self.workflow_state

    def _set_default_sales_person(self):
        if not self.is_new() or self.sales_person:
            return
        sales_person = _resolve_sales_person(frappe.session.user)
        if sales_person:
            self.sales_person = sales_person

    def _set_unit_status(self, unit, status):
        if not unit:
            return
        frappe.db.set_value("Item", unit, "unit_status", status)

    def _release_units_if_unclaimed(self):
        for row in self.items:
            if not row.unit:
                continue
            current = frappe.db.get_value("Item", row.unit, "unit_status")
            if current == "Reserved" and not self._unit_held_by_other(row.unit):
                self._set_unit_status(row.unit, "Available")


def _resolve_sales_person(user):
    """Sales Person linked to a user via Employee.user_id -> Sales Person.employee."""
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        return None
    return frappe.db.get_value("Sales Person", {"employee": employee}, "name")


@frappe.whitelist()
def get_default_sales_person():
    """Used by reservation.js to pre-fill Sales Person on a new, unsaved Reservation."""
    return _resolve_sales_person(frappe.session.user) or ""


def mark_unit_converted(unit, booking_name):
    """Link a newly created Property Booking back to whichever active Reservation
    Item row held this unit, and flip that Reservation to Converted to Booking
    once every row on it has been converted. Returns the Reservation name that
    was converted, or None if no matching active Reservation Item row exists
    for this unit (e.g. the booking wasn't created from a Reservation)."""
    row = frappe.db.sql(
        """
        SELECT ri.name, ri.parent
        FROM `tabReservation Item` ri
        INNER JOIN `tabReservation` r ON r.name = ri.parent
        WHERE ri.unit = %(unit)s
          AND (ri.property_booking IS NULL OR ri.property_booking = '')
          AND r.status NOT IN %(terminal)s
          AND r.docstatus < 2
        ORDER BY r.creation DESC
        LIMIT 1
        """,
        {"unit": unit, "terminal": TERMINAL_STATUSES},
        as_dict=True,
    )
    if not row:
        return None
    row = row[0]
    frappe.db.set_value("Reservation Item", row.name, "property_booking", booking_name, update_modified=False)
    _sync_conversion_status(row.parent)
    return row.parent


def _sync_conversion_status(reservation_name):
    rows = frappe.get_all("Reservation Item", filters={"parent": reservation_name}, fields=["property_booking"])
    if rows and all(r.property_booking for r in rows):
        frappe.db.set_value("Reservation", reservation_name, "status", "Converted to Booking", update_modified=False)


# ── Auto-release (scheduled) ────────────────────────────────────────────────

def release_expired_reservations():
    """Daily scheduler job: expire reservations past their validity date and
    release units that were never converted (no linked Property Booking on
    their row). A reservation's overall status only flips to Expired once
    every row is either released or already converted."""
    candidates = frappe.get_all(
        "Reservation",
        filters={
            "reservation_validity_date": ("<", getdate(today())),
            "status": ("not in", list(TERMINAL_STATUSES)),
            "docstatus": ("<", 2),
        },
        pluck="name",
    )
    expired_count = 0
    for name in candidates:
        doc = frappe.get_doc("Reservation", name)
        any_converted = False
        for row in doc.items:
            if row.property_booking:
                any_converted = True
                continue
            if not row.unit:
                continue
            current = frappe.db.get_value("Item", row.unit, "unit_status")
            if current == "Reserved" and not doc._unit_held_by_other(row.unit):
                frappe.db.set_value("Item", row.unit, "unit_status", "Available", update_modified=False)

        if not any_converted:
            frappe.db.set_value("Reservation", name, "status", "Expired", update_modified=False)
            expired_count += 1

    if candidates:
        frappe.db.commit()
        frappe.logger().info(
            f"release_expired_reservations: processed {len(candidates)}, expired {expired_count}"
        )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_quotation_units(doctype, txt, searchfield, start, page_len, filters):
    """Restrict the Unit dropdown (in the Units grid) to items on the selected Quotation."""
    quotation = (filters or {}).get("quotation") or ""
    if not quotation:
        return []
    return frappe.db.sql(
        """
        SELECT qi.item_code, qi.item_name
        FROM `tabQuotation Item` qi
        WHERE qi.parent = %(quotation)s
          AND qi.item_code LIKE %(txt)s
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        {"quotation": quotation, "txt": f"%{txt}%", "page_len": page_len, "start": start},
    )


@frappe.whitelist()
def get_quotation_reserved_units(quotation):
    """Unit item codes on this quotation that already have an active (non-terminal)
    Reservation — used to hide their 'Create Reservation' button on the Quotation."""
    rows = frappe.db.sql(
        """
        SELECT ri.unit
        FROM `tabReservation Item` ri
        INNER JOIN `tabReservation` r ON r.name = ri.parent
        WHERE r.quotation = %(quotation)s
          AND r.status NOT IN %(terminal)s
          AND r.docstatus < 2
        """,
        {"quotation": quotation, "terminal": TERMINAL_STATUSES},
        as_dict=True,
    )
    return list({r.unit for r in rows if r.unit})
