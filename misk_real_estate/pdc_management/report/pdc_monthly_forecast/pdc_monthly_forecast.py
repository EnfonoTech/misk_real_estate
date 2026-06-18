# apps/misk_real_estate/misk_real_estate/pdc_management/report/pdc_monthly_forecast/pdc_monthly_forecast.py
"""
PDC Monthly Forecast — shows expected monthly cash inflow from PDC cheques.
Grouped by month, broken down by status bucket.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, add_months, get_first_day, get_last_day


def execute(filters=None):
    filters = filters or {}
    # Default to today .. +1 year so the report always renders (no "required" error)
    if not filters.get("from_date"):
        filters["from_date"] = getdate()
    if not filters.get("to_date"):
        filters["to_date"] = add_months(getdate(filters["from_date"]), 12)

    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    summary = get_summary(data)
    return columns, data, None, chart, summary


def get_columns():
    return [
        {"label": _("Month"),              "fieldname": "month_label",     "fieldtype": "Data",     "width": 120},
        {"label": _("Total PDCs"),         "fieldname": "total_count",     "fieldtype": "Int",      "width": 100},
        {"label": _("Total Amount (OMR)"), "fieldname": "total_amount",    "fieldtype": "Currency", "width": 150},
        {"label": _("Pending"),            "fieldname": "pending_amount",  "fieldtype": "Currency", "width": 130},
        {"label": _("In Batch"),           "fieldname": "inbatch_amount",  "fieldtype": "Currency", "width": 120},
        {"label": _("Deposited"),          "fieldname": "deposited_amount","fieldtype": "Currency", "width": 120},
        {"label": _("Cleared"),            "fieldname": "cleared_amount",  "fieldtype": "Currency", "width": 120},
        {"label": _("Bounced"),            "fieldname": "bounced_amount",  "fieldtype": "Currency", "width": 110},
    ]


def get_data(filters):
    conditions = ["pe.cheque_date BETWEEN %(from_date)s AND %(to_date)s"]
    values = {
        "from_date": filters["from_date"],
        "to_date": filters["to_date"],
    }

    if filters.get("building"):
        # Filter via allocation rows without joining (avoids double-counting amounts)
        conditions.append("pe.name IN (SELECT parent FROM `tabPDC Allocation` WHERE building = %(building)s)")
        values["building"] = filters["building"]

    if filters.get("customer"):
        conditions.append("pe.customer = %(customer)s")
        values["customer"] = filters["customer"]

    where = " AND ".join(conditions)

    rows = frappe.db.sql(
        f"""
        SELECT
            DATE_FORMAT(pe.cheque_date, '%%Y-%%m') AS month_key,
            pe.status,
            COUNT(*) AS cnt,
            SUM(pe.amount) AS amount
        FROM `tabPDC Entry` pe
        WHERE {where}
        GROUP BY month_key, pe.status
        ORDER BY month_key ASC
        """,
        values,
        as_dict=True,
    )

    # Pivot into month rows
    months = {}
    for row in rows:
        mk = row.month_key
        if mk not in months:
            months[mk] = {
                "month_key":       mk,
                "month_label":     _month_label(mk),
                "total_count":     0,
                "total_amount":    0.0,
                "pending_amount":  0.0,
                "inbatch_amount":  0.0,
                "deposited_amount":0.0,
                "cleared_amount":  0.0,
                "bounced_amount":  0.0,
            }
        months[mk]["total_count"]  += row.cnt
        months[mk]["total_amount"] += flt(row.amount)
        status = row.status or ""
        if status == "Pending":
            months[mk]["pending_amount"]   += flt(row.amount)
        elif status == "In Batch":
            months[mk]["inbatch_amount"]   += flt(row.amount)
        elif status == "Deposited":
            months[mk]["deposited_amount"] += flt(row.amount)
        elif status == "Cleared":
            months[mk]["cleared_amount"]   += flt(row.amount)
        elif status == "Bounced":
            months[mk]["bounced_amount"]   += flt(row.amount)

    return list(months.values())


def _month_label(month_key):
    """'2026-03' → 'Mar 2026'"""
    try:
        import datetime
        dt = datetime.datetime.strptime(month_key, "%Y-%m")
        return dt.strftime("%b %Y")
    except Exception:
        return month_key


def get_chart(data):
    if not data:
        return None
    return {
        "title": _("Monthly PDC Collection Forecast"),
        "data": {
            "labels": [r["month_label"] for r in data],
            "datasets": [
                {"name": _("Pending"),   "values": [r["pending_amount"]   for r in data]},
                {"name": _("Deposited"), "values": [r["deposited_amount"] for r in data]},
                {"name": _("Cleared"),   "values": [r["cleared_amount"]   for r in data]},
                {"name": _("Bounced"),   "values": [r["bounced_amount"]   for r in data]},
            ],
        },
        "type": "bar",
        "barOptions": {"stacked": True},
        "colors": ["#F39C12", "#2490EF", "#2ECC71", "#E74C3C"],
    }


def get_summary(data):
    if not data:
        return []
    total      = sum(r["total_amount"]    for r in data)
    cleared    = sum(r["cleared_amount"]  for r in data)
    pending    = sum(r["pending_amount"]  for r in data)
    deposited  = sum(r["deposited_amount"]for r in data)
    bounced    = sum(r["bounced_amount"]  for r in data)
    return [
        {"label": _("Total Expected"),  "value": total,     "datatype": "Currency"},
        {"label": _("Cleared"),         "value": cleared,   "datatype": "Currency", "color": "green"},
        {"label": _("Deposited"),       "value": deposited, "datatype": "Currency", "color": "blue"},
        {"label": _("Pending"),         "value": pending,   "datatype": "Currency", "color": "orange"},
        {"label": _("Bounced"),         "value": bounced,   "datatype": "Currency", "color": "red"},
    ]
