# apps/misk_real_estate/misk_real_estate/real_estate/report/pdc_status_report/pdc_status_report.py

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    summary = get_summary(data)
    return columns, data, None, chart, summary


def get_columns():
    return [
        {"label": _("Cheque No"),      "fieldname": "cheque_no",      "fieldtype": "Data",     "width": 130},
        {"label": _("Customer"),        "fieldname": "customer",       "fieldtype": "Link",     "options": "Customer", "width": 160},
        {"label": _("Building"),        "fieldname": "building",       "fieldtype": "Link",     "options": "Item Group", "width": 140},
        {"label": _("Unit"),            "fieldname": "unit",           "fieldtype": "Link",     "options": "Item",  "width": 110},
        {"label": _("Type"),            "fieldname": "purpose",        "fieldtype": "Data",     "width": 120},
        {"label": _("Cheque Date"),     "fieldname": "cheque_date",    "fieldtype": "Date",     "width": 110},
        {"label": _("Amount (OMR)"),    "fieldname": "amount",         "fieldtype": "Currency", "width": 120},
        {"label": _("Status"),          "fieldname": "status",         "fieldtype": "Data",     "width": 110},
        {"label": _("Booking"),         "fieldname": "booking",        "fieldtype": "Link",     "options": "Property Booking", "width": 140},
        {"label": _("Batch"),           "fieldname": "batch",          "fieldtype": "Link",     "options": "PDC Batch", "width": 130},
        {"label": _("Deposited Date"),  "fieldname": "deposited_date", "fieldtype": "Date",     "width": 120},
        {"label": _("Cleared Date"),    "fieldname": "cleared_date",   "fieldtype": "Date",     "width": 110},
        {"label": _("Payment Entry"),   "fieldname": "payment_entry",  "fieldtype": "Link",     "options": "Payment Entry", "width": 150},
    ]


def get_data(filters):
    conditions = ["1=1"]
    values = {}

    if filters.get("customer"):
        conditions.append("pe.customer = %(customer)s")
        values["customer"] = filters["customer"]

    if filters.get("building"):
        conditions.append("a.building = %(building)s")
        values["building"] = filters["building"]

    if filters.get("status"):
        conditions.append("pe.status = %(status)s")
        values["status"] = filters["status"]

    if filters.get("from_date"):
        conditions.append("pe.cheque_date >= %(from_date)s")
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions.append("pe.cheque_date <= %(to_date)s")
        values["to_date"] = filters["to_date"]

    where = " AND ".join(conditions)

    return frappe.db.sql(
        f"""
        SELECT
            pe.name,
            pe.cheque_no,
            pe.customer,
            GROUP_CONCAT(DISTINCT a.building) AS building,
            GROUP_CONCAT(DISTINCT a.unit) AS unit,
            GROUP_CONCAT(DISTINCT a.purpose) AS purpose,
            pe.cheque_date,
            pe.amount AS amount,
            pe.status,
            GROUP_CONCAT(DISTINCT a.property_booking) AS booking,
            pe.batch,
            pe.deposited_date,
            pe.cleared_date,
            pe.payment_entry
        FROM `tabPDC Entry` pe
        LEFT JOIN `tabPDC Allocation` a ON a.parent = pe.name
        WHERE {where}
        GROUP BY pe.name
        ORDER BY pe.cheque_date ASC
        """,
        values,
        as_dict=True,
    )


def get_chart(data):
    if not data:
        return None
    buckets = {}
    for row in data:
        s = row.status or "Unknown"
        buckets[s] = buckets.get(s, 0) + flt(row.amount)
    return {
        "title": _("PDC Amount by Status"),
        "data": {
            "labels": list(buckets.keys()),
            "datasets": [{"name": _("Amount (OMR)"), "values": list(buckets.values())}],
        },
        "type": "pie",
    }


def get_summary(data):
    if not data:
        return []
    total = sum(flt(r.amount) for r in data)
    by_status = {}
    for r in data:
        s = r.status or "Unknown"
        by_status[s] = by_status.get(s, 0) + flt(r.amount)
    return [
        {"label": _("Total PDCs"),   "value": len(data),                         "datatype": "Int"},
        {"label": _("Total Amount"), "value": total,                             "datatype": "Currency"},
        {"label": _("Pending"),      "value": by_status.get("Pending", 0),       "datatype": "Currency", "color": "orange"},
        {"label": _("Sent to Bank"), "value": by_status.get("Sent to Bank", 0),  "datatype": "Currency", "color": "purple"},
        {"label": _("Deposited"),    "value": by_status.get("Deposited", 0),     "datatype": "Currency", "color": "blue"},
        {"label": _("In Batch"),     "value": by_status.get("In Batch", 0),      "datatype": "Currency", "color": "purple"},
        {"label": _("Cleared"),      "value": by_status.get("Cleared", 0),       "datatype": "Currency", "color": "green"},
        {"label": _("Bounced"),      "value": by_status.get("Bounced", 0),       "datatype": "Currency", "color": "red"},
    ]
