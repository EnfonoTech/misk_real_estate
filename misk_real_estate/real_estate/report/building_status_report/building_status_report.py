# apps/misk_real_estate/misk_real_estate/real_estate/report/building_status_report/building_status_report.py
"""
Building Status Report — the live, per-building equivalent of the old
"<Building> BUILDING.xlsx" tracking sheets (Floor/Unit/Type/Buyer/Sales
Person/Selling Price/Booking Amount/Down Payment/monthly installments/
Total/Maintenance), driven by Property Booking + PDC Schedule instead of a
manually maintained spreadsheet.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate

from misk_real_estate.utils.company import split_amount_by_unit_weight


def execute(filters=None):
    filters = filters or {}
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("From Date and To Date are required."))

    month_keys = get_month_keys(filters)
    columns = get_columns(month_keys)
    data = get_data(filters, month_keys)
    summary = get_summary(data)
    return columns, data, None, None, summary


def get_month_keys(filters):
    start = getdate(filters["from_date"]).replace(day=1)
    end = getdate(filters["to_date"]).replace(day=1)
    keys = []
    cur = start
    while cur <= end:
        keys.append(cur)
        cur = add_months(cur, 1)
    return keys


def _month_fieldname(d):
    return "m_" + d.strftime("%Y_%m")


def get_columns(month_keys):
    columns = [
        {"label": _("Building"), "fieldname": "building", "fieldtype": "Link", "options": "Item Group", "width": 130},
        {"label": _("Floor"), "fieldname": "floor_number", "fieldtype": "Link", "options": "Floor", "width": 90},
        {"label": _("Unit No."), "fieldname": "unit_name", "fieldtype": "Data", "width": 90},
        {"label": _("Unit"), "fieldname": "unit_id", "fieldtype": "Link", "options": "Item", "width": 130},
        {"label": _("Type"), "fieldname": "unit_type", "fieldtype": "Link", "options": "Unit Type", "width": 90},
        {"label": _("Status"), "fieldname": "unit_status", "fieldtype": "Data", "width": 100},
        {"label": _("Buyer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 170},
        {"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 110},
        {"label": _("Selling Price"), "fieldname": "unit_price", "fieldtype": "Currency", "precision": 3, "width": 110},
        {"label": _("Booking Amount"), "fieldname": "booking_amount", "fieldtype": "Currency", "precision": 3, "width": 110},
        {"label": _("Down Payment"), "fieldname": "down_payment", "fieldtype": "Currency", "precision": 3, "width": 110},
    ]
    for d in month_keys:
        columns.append({
            "label": d.strftime("%b %Y"),
            "fieldname": _month_fieldname(d),
            "fieldtype": "Currency",
            "precision": 3,
            "width": 90,
        })
    columns += [
        {"label": _("Total"), "fieldname": "total", "fieldtype": "Currency", "precision": 3, "width": 110},
        {"label": _("Diff"), "fieldname": "diff", "fieldtype": "Currency", "precision": 3, "width": 90},
        {"label": _("Maintenance"), "fieldname": "maintenance", "fieldtype": "Currency", "precision": 3, "width": 100},
        {"label": _("Booking"), "fieldname": "booking", "fieldtype": "Link", "options": "Property Booking", "width": 130},
        {"label": _("Booking Date"), "fieldname": "booking_date", "fieldtype": "Date", "width": 100},
    ]
    return columns


def get_data(filters, month_keys):
    conditions = "WHERE i.disabled = 0 AND i.is_unit = 1"
    params = {}
    if filters.get("building"):
        conditions += " AND i.item_group = %(building)s"
        params["building"] = filters["building"]
    if filters.get("unit_status"):
        conditions += " AND COALESCE(i.unit_status, 'Available') = %(unit_status)s"
        params["unit_status"] = filters["unit_status"]

    units = frappe.db.sql(
        """
        SELECT i.item_code AS unit_id, i.item_name AS unit_name, i.item_group AS building,
               i.unit_type AS unit_type, i.floor_number AS floor_number,
               COALESCE(i.unit_status, 'Available') AS unit_status
        FROM `tabItem` i
        {conditions}
        ORDER BY i.item_group, i.floor_number, i.item_code
        """.format(conditions=conditions),
        params,
        as_dict=True,
    )
    if not units:
        return []

    unit_codes = [u.unit_id for u in units]

    bookings = frappe.db.sql(
        """
        SELECT pbu.unit AS unit, pb.name AS booking, pb.docstatus AS docstatus,
               pb.customer AS customer, pb.customer_name AS customer_name,
               pb.sales_person AS sales_person, pb.booking_date AS booking_date,
               pbu.unit_price AS unit_price, pbu.booking_amount AS booking_amount,
               pbu.down_payment_amount AS down_payment_amount,
               pbu.owners_association_fee AS owners_association_fee
        FROM `tabProperty Booking Unit` pbu
        INNER JOIN `tabProperty Booking` pb ON pb.name = pbu.parent
        WHERE pbu.unit IN %(units)s AND pb.docstatus < 2
              AND pb.status NOT IN ('Cancelled', 'Lost')
        ORDER BY pb.docstatus DESC, pb.creation DESC
        """,
        {"units": unit_codes},
        as_dict=True,
    )

    # First match per unit wins — already ordered submitted-first, newest-first.
    booking_by_unit = {}
    for b in bookings:
        if b.unit not in booking_by_unit:
            booking_by_unit[b.unit] = b

    booking_names = list({b.booking for b in booking_by_unit.values()})

    # Each unit's own remaining installment total (price minus booking
    # amount minus down payment), grouped by booking — used below to split
    # a PDC row across units. NOT based on the stored monthly_installment/
    # number_of_installments fields — those are only ever computed when a
    # Payment Plan is set, and are left at 0/blank for bookings imported
    # directly into PDC Schedule without one (confirmed on a real
    # production booking). unit_price/booking_amount/down_payment_amount
    # are reliably set either way. This is used purely as a ratio between
    # units, so dividing by the number of installments (which would give
    # the true per-month rate) is unnecessary — it cancels out in the split.
    #
    # Fetched separately from `bookings` above, scoped by booking name
    # rather than by unit_codes — a booking's units can span more than one
    # building, and `bookings`/unit_codes is filtered to whatever building
    # the report itself is currently scoped to. Building the weights from
    # that same filtered set would silently drop any of the booking's units
    # in a different building, making a shared PDC row's split (and the
    # rounding-correction target below) wrong the moment someone filters by
    # a single building — confirmed on a real production booking that
    # showed Diff = 0 unfiltered but a large phantom Diff once filtered to
    # one of its two buildings.
    unit_weights_by_booking = {}
    if booking_names:
        all_booking_units = frappe.db.sql(
            """
            SELECT parent AS booking, unit, unit_price, booking_amount, down_payment_amount
            FROM `tabProperty Booking Unit`
            WHERE parent IN %(names)s
            """,
            {"names": booking_names},
            as_dict=True,
        )
        for b in all_booking_units:
            if not b.unit:
                continue
            remaining = flt(b.unit_price) - flt(b.booking_amount) - flt(b.down_payment_amount)
            unit_weights_by_booking.setdefault(b.booking, {})[b.unit] = remaining

    pdc_rows = []
    if booking_names:
        pdc_rows = frappe.db.sql(
            """
            SELECT parent AS booking, cheque_date, amount
            FROM `tabPDC Schedule`
            WHERE parent IN %(names)s AND installment_type = 'Installment'
            ORDER BY cheque_date ASC
            """,
            {"names": booking_names},
            as_dict=True,
        )

    month_key_set = set(month_keys)
    # (booking, unit) -> [(month_key_or_None, amount), ...] in chronological
    # order — kept as a list rather than aggregating straight into
    # month_amounts/full_total so the very last entry can absorb the whole
    # schedule's rounding below, same as generate_pdc_schedule() itself does
    # for a freshly-generated schedule (its last installment row absorbs
    # rounding so the table matches the unit's price exactly).
    contributions_by_key = {}

    for row in pdc_rows:
        # Always split this row's own real amount across the booking's units
        # by weight — one uniform rule regardless of what's recorded on the
        # row itself (unit/unit_breakdown), since a recorded breakdown can be
        # incomplete (e.g. missing a unit added to the booking after the
        # schedule already existed) and there'd be no way to tell that apart
        # from a genuinely-correct recorded split. The row's date/amount are
        # trusted as-is; this only decides how much belongs to which unit.
        # Same helper (and so the exact same algorithm) used when building
        # the actual Sales Invoice line items — see build_pdc_row_invoice_items.
        contributions = split_amount_by_unit_weight(row.amount, unit_weights_by_booking.get(row.booking, {}))

        month_key = getdate(row.cheque_date).replace(day=1) if row.cheque_date else None
        for unit_code, amount in contributions:
            key = (row.booking, unit_code)
            contributions_by_key.setdefault(key, []).append([month_key, amount])

    # Correct each unit's very last contribution (chronologically, across
    # its whole schedule — not just within the report's date filter) so its
    # total exactly equals its own expected installment total, instead of
    # drifting by a cent or two from rounding every row's share to 3
    # decimals independently. Capped to a tiny threshold on purpose — a real
    # shortfall (the source data genuinely doesn't add up to the unit's
    # price, e.g. a buyer who never finished setting up their installment
    # plan) must keep showing as a real Diff, not get silently absorbed here.
    # Worst-case pure-rounding drift is bounded by roughly 0.0005 per row, so
    # even a 100-installment schedule tops out well under this.
    ROUNDING_THRESHOLD = 0.1
    for key, entries in contributions_by_key.items():
        _booking, unit = key
        target = unit_weights_by_booking.get(_booking, {}).get(unit)
        if target is None:
            continue
        current_total = round(sum(e[1] for e in entries), 3)
        residual = round(target - current_total, 3)
        if residual and abs(residual) <= ROUNDING_THRESHOLD:
            entries[-1][1] = round(entries[-1][1] + residual, 3)

    month_amounts = {}   # (booking, unit) -> {month_date: amount}
    full_total = {}      # (booking, unit) -> total installment amount (whole schedule)
    for key, entries in contributions_by_key.items():
        for month_key, amount in entries:
            full_total[key] = full_total.get(key, 0) + amount
            if month_key and month_key in month_key_set:
                month_amounts.setdefault(key, {})
                month_amounts[key][month_key] = month_amounts[key].get(month_key, 0) + amount

    data = []
    for u in units:
        row = {
            "building": u.building,
            "floor_number": u.floor_number,
            "unit_name": u.unit_name,
            "unit_id": u.unit_id,
            "unit_type": u.unit_type,
            "unit_status": u.unit_status,
        }
        b = booking_by_unit.get(u.unit_id)
        if b:
            key = (b.booking, u.unit_id)
            installment_total = full_total.get(key, 0)
            total = flt(b.booking_amount) + flt(b.down_payment_amount) + installment_total
            row.update({
                "customer_name": b.customer_name,
                "sales_person": b.sales_person,
                "unit_price": flt(b.unit_price),
                "booking_amount": flt(b.booking_amount),
                "down_payment": flt(b.down_payment_amount),
                "maintenance": flt(b.owners_association_fee),
                "booking": b.booking,
                "booking_date": b.booking_date,
                "total": total,
                "diff": round(total - flt(b.unit_price), 3),
            })
            for mk, amt in month_amounts.get(key, {}).items():
                row[_month_fieldname(mk)] = amt
        data.append(row)

    return data


def get_summary(data):
    total_units = len(data)
    with_booking = sum(1 for r in data if r.get("booking"))
    total_selling = sum(flt(r.get("unit_price")) for r in data)
    mismatches = sum(1 for r in data if abs(flt(r.get("diff"))) > 0.01)

    summary = [
        {"label": _("Total Units"), "value": total_units, "datatype": "Int"},
        {"label": _("Units with a Booking"), "value": with_booking, "datatype": "Int"},
        {"label": _("Total Selling Price"), "value": total_selling, "datatype": "Currency"},
    ]
    if mismatches:
        summary.append({
            "label": _("Rows with Diff ≠ 0"), "value": mismatches, "datatype": "Int", "color": "red",
        })
    return summary
