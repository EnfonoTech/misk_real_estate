# apps/misk_real_estate/misk_real_estate/real_estate/report/building_status_report/building_status_report.py
"""
Building Status Report — the live, per-building equivalent of the old
"<Building> BUILDING.xlsx" tracking sheets (Floor/Unit/Type/Buyer/Sales
Person/Selling Price/Booking Amount/Down Payment/monthly installments/
Total/Maintenance), driven by Property Booking + PDC Schedule instead of a
manually maintained spreadsheet.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate


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
        {"label": _("Selling Price"), "fieldname": "unit_price", "fieldtype": "Currency", "width": 110},
        {"label": _("Booking Amount"), "fieldname": "booking_amount", "fieldtype": "Currency", "width": 110},
        {"label": _("Down Payment"), "fieldname": "down_payment", "fieldtype": "Currency", "width": 110},
    ]
    for d in month_keys:
        columns.append({
            "label": d.strftime("%b %Y"),
            "fieldname": _month_fieldname(d),
            "fieldtype": "Currency",
            "width": 90,
        })
    columns += [
        {"label": _("Total"), "fieldname": "total", "fieldtype": "Currency", "width": 110},
        {"label": _("Diff"), "fieldname": "diff", "fieldtype": "Currency", "width": 90},
        {"label": _("Maintenance"), "fieldname": "maintenance", "fieldtype": "Currency", "width": 100},
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
               pb.first_installment_date AS first_installment_date,
               pbu.unit_price AS unit_price, pbu.booking_amount AS booking_amount,
               pbu.down_payment_amount AS down_payment_amount,
               pbu.owners_association_fee AS owners_association_fee,
               pbu.monthly_installment AS monthly_installment,
               pbu.number_of_installments AS number_of_installments
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

    # Every unit's own monthly_installment, grouped by booking — used below
    # to split a PDC row that has neither `unit` nor `unit_breakdown` set.
    unit_weights_by_booking = {}
    for b in bookings:
        unit_weights_by_booking.setdefault(b.booking, {})[b.unit] = flt(b.monthly_installment)

    booking_names = list({b.booking for b in booking_by_unit.values()})

    pdc_rows = []
    if booking_names:
        pdc_rows = frappe.db.sql(
            """
            SELECT parent AS booking, unit, cheque_date, amount, unit_breakdown
            FROM `tabPDC Schedule`
            WHERE parent IN %(names)s AND installment_type = 'Installment'
            """,
            {"names": booking_names},
            as_dict=True,
        )

    month_key_set = set(month_keys)
    month_amounts = {}   # (booking, unit) -> {month_date: amount}
    full_total = {}      # (booking, unit) -> total installment amount (whole schedule)

    for row in pdc_rows:
        if row.unit:
            contributions = [(row.unit, flt(row.amount))]
        elif row.unit_breakdown:
            try:
                parsed = json.loads(row.unit_breakdown)
            except ValueError:
                parsed = []
            contributions = [(c.get("unit"), flt(c.get("amount"))) for c in parsed if c.get("unit")]
        else:
            # Neither recorded — split this row's own real amount across the
            # booking's units by their own monthly_installment weight (same
            # per-unit split principle a Sales Invoice would apply), purely
            # from these two tables. The row's date/amount are trusted as-is;
            # this only decides how much of it belongs to which unit.
            weights = {u: w for u, w in unit_weights_by_booking.get(row.booking, {}).items() if w}
            total_weight = sum(weights.values())
            if total_weight:
                contributions = [
                    (u, round(flt(row.amount) * w / total_weight, 3)) for u, w in weights.items()
                ]
            else:
                contributions = []

        month_key = getdate(row.cheque_date).replace(day=1) if row.cheque_date else None
        for unit_code, amount in contributions:
            key = (row.booking, unit_code)
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
