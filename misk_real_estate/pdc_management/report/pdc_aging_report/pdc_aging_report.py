# apps/misk_real_estate/misk_real_estate/pdc_management/report/pdc_aging_report/pdc_aging_report.py

import frappe
from frappe import _
from frappe.utils import flt, getdate, today


def execute(filters=None):
    filters = filters or {}
    as_of = getdate(filters.get("as_of_date") or today())
    columns = get_columns()
    data = get_data(filters, as_of)
    chart = get_chart(data)
    summary = get_summary(data)
    return columns, data, None, chart, summary


def get_columns():
    return [
        {"label": _("Customer"),      "fieldname": "customer",     "fieldtype": "Link",     "options": "Customer",   "width": 160},
        {"label": _("Building"),       "fieldname": "building",     "fieldtype": "Link",     "options": "Item Group", "width": 140},
        {"label": _("Unit"),           "fieldname": "unit",         "fieldtype": "Link",     "options": "Item",       "width": 110},
        {"label": _("Type"),           "fieldname": "purpose",      "fieldtype": "Data",     "width": 120},
        {"label": _("Cheque No"),      "fieldname": "cheque_no",    "fieldtype": "Data",     "width": 130},
        {"label": _("Cheque Date"),    "fieldname": "cheque_date",  "fieldtype": "Date",     "width": 110},
        {"label": _("Amount (OMR)"),   "fieldname": "amount",       "fieldtype": "Currency", "width": 120},
        {"label": _("Status"),         "fieldname": "status",       "fieldtype": "Data",     "width": 110},
        {"label": _("Days Overdue"),   "fieldname": "days_overdue", "fieldtype": "Int",      "width": 110},
        {"label": _("Aging Bucket"),   "fieldname": "aging_bucket", "fieldtype": "Data",     "width": 120},
        {"label": _("Booking"),        "fieldname": "booking",      "fieldtype": "Link",     "options": "Property Booking", "width": 140},
    ]


def get_data(filters, as_of):
    conditions = ["pe.status NOT IN ('Cleared')"]
    values = {"as_of": str(as_of)}

    if filters.get("customer"):
        conditions.append("pe.customer = %(customer)s")
        values["customer"] = filters["customer"]

    if filters.get("building"):
        conditions.append("a.building = %(building)s")
        values["building"] = filters["building"]

    if filters.get("status"):
        conditions.append("pe.status = %(status)s")
        values["status"] = filters["status"]

    where = " AND ".join(conditions)

    rows = frappe.db.sql(
        f"""
        SELECT
            pe.customer,
            GROUP_CONCAT(DISTINCT a.building) AS building,
            GROUP_CONCAT(DISTINCT a.unit) AS unit,
            GROUP_CONCAT(DISTINCT a.purpose) AS purpose,
            pe.cheque_no,
            pe.cheque_date,
            pe.amount AS amount,
            pe.status,
            GROUP_CONCAT(DISTINCT a.property_booking) AS booking,
            DATEDIFF(%(as_of)s, pe.cheque_date) AS days_overdue
        FROM `tabPDC Entry` pe
        LEFT JOIN `tabPDC Allocation` a ON a.parent = pe.name
        WHERE {where}
        GROUP BY pe.name
        ORDER BY pe.cheque_date ASC
        """,
        values,
        as_dict=True,
    )

    for row in rows:
        row.days_overdue = max(0, row.days_overdue or 0)
        row.aging_bucket = _get_bucket(row.days_overdue)

    return rows


def _get_bucket(days):
    if days <= 0:
        return _("Not Yet Due")
    elif days <= 30:
        return _("1–30 Days")
    elif days <= 60:
        return _("31–60 Days")
    elif days <= 90:
        return _("61–90 Days")
    else:
        return _("90+ Days")


def get_chart(data):
    if not data:
        return None

    BUCKETS = [_("Not Yet Due"), _("1–30 Days"), _("31–60 Days"), _("61–90 Days"), _("90+ Days")]
    bucket_amounts = {b: 0 for b in BUCKETS}
    for row in data:
        b = row.aging_bucket or _("Not Yet Due")
        bucket_amounts[b] = bucket_amounts.get(b, 0) + flt(row.amount)

    return {
        "title": _("PDC Aging by Bucket"),
        "data": {
            "labels": BUCKETS,
            "datasets": [{"name": _("Amount (OMR)"), "values": [bucket_amounts[b] for b in BUCKETS]}],
        },
        "type": "bar",
        "colors": ["#2490EF", "#F39C12", "#E74C3C", "#8E44AD", "#2C3E50"],
    }


def get_summary(data):
    if not data:
        return []

    BUCKETS = [_("Not Yet Due"), _("1–30 Days"), _("31–60 Days"), _("61–90 Days"), _("90+ Days")]
    bucket_amounts = {b: 0.0 for b in BUCKETS}
    for row in data:
        b = row.aging_bucket or _("Not Yet Due")
        bucket_amounts[b] = bucket_amounts.get(b, 0) + flt(row.amount)

    total = sum(flt(r.amount) for r in data)
    overdue = sum(flt(r.amount) for r in data if (r.days_overdue or 0) > 0)

    result = [
        {"label": _("Total Outstanding"), "value": total,   "datatype": "Currency"},
        {"label": _("Total Overdue"),      "value": overdue, "datatype": "Currency", "color": "red"},
    ]
    for b in BUCKETS:
        result.append({"label": b, "value": bucket_amounts[b], "datatype": "Currency"})
    return result
