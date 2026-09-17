# apps/misk_real_estate/misk_real_estate/real_estate/report/pdc_status_report/pdc_status_report.py

import frappe
from frappe import _
from frappe.utils import flt

# Where the unreceived half of a partially cleared cheque is reported in the
# cards/chart. Kept separate from "Partially Cleared" (which carries only the
# money actually banked) so the two still add up to the cheque's face value.
PARTIAL_BALANCE = _("Partial — Balance Due")


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    summary = get_summary(data)
    return columns, data, None, chart, summary


def get_columns():
    return [
        {"label": _("PDC Entry"),       "fieldname": "pdc_entry",      "fieldtype": "Link",     "options": "PDC Entry", "width": 130},
        {"label": _("Cheque No"),      "fieldname": "cheque_no",      "fieldtype": "Data",     "width": 130},
        {"label": _("Customer"),        "fieldname": "customer",       "fieldtype": "Link",     "options": "Customer", "width": 160},
        {"label": _("Building"),        "fieldname": "building",       "fieldtype": "Link",     "options": "Item Group", "width": 140},
        {"label": _("Unit"),            "fieldname": "unit",           "fieldtype": "Link",     "options": "Item",  "width": 110},
        {"label": _("Type"),            "fieldname": "purpose",        "fieldtype": "Data",     "width": 120},
        {"label": _("Cheque Date"),     "fieldname": "cheque_date",    "fieldtype": "Date",     "width": 110},
        {"label": _("Amount (OMR)"),    "fieldname": "amount",         "fieldtype": "Currency", "width": 120},
        {"label": _("Received"),        "fieldname": "received",       "fieldtype": "Currency", "width": 110},
        {"label": _("Balance"),         "fieldname": "balance",        "fieldtype": "Currency", "width": 110},
        {"label": _("Status"),          "fieldname": "status",         "fieldtype": "Data",     "width": 110},
        {"label": _("Booking"),         "fieldname": "booking",        "fieldtype": "Link",     "options": "Property Booking", "width": 140},
        {"label": _("Batch"),           "fieldname": "batch",          "fieldtype": "Link",     "options": "PDC Batch", "width": 130},
        {"label": _("Deposited Date"),  "fieldname": "deposited_date", "fieldtype": "Date",     "width": 120},
        {"label": _("Cleared Date"),    "fieldname": "cleared_date",   "fieldtype": "Date",     "width": 110},
        # Every receipt against the cheque, each linked to its own Payment Entry.
        # This replaces a plain Payment Entry column, which could only ever show
        # the latest one — pe.payment_entry is still SELECTed, as the fallback
        # for a cheque cleared in one shot (no itemised clearance rows).
        {"label": _("Payments"),        "fieldname": "payments",       "fieldtype": "Data",     "width": 320},
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

    rows = frappe.db.sql(
        f"""
        SELECT
            pe.name AS pdc_entry,
            pe.cheque_no,
            pe.customer,
            GROUP_CONCAT(DISTINCT a.building) AS building,
            GROUP_CONCAT(DISTINCT a.unit) AS unit,
            GROUP_CONCAT(DISTINCT a.purpose) AS purpose,
            pe.cheque_date,
            pe.amount AS amount,
            -- A cheque cleared in one shot through Mark Cleared never touches
            -- cleared_amount (that field only tracks part-receipts), so
            -- "Received" is derived from the status instead. This is what keeps
            -- the column correct for every PDC already cleared in production,
            -- with no backfill needed.
            CASE WHEN pe.status = 'Cleared' THEN pe.amount
                 ELSE COALESCE(pe.cleared_amount, 0) END AS received,
            CASE WHEN pe.status = 'Cleared' THEN 0
                 ELSE pe.amount - COALESCE(pe.cleared_amount, 0) END AS balance,
            pe.status,
            GROUP_CONCAT(DISTINCT a.property_booking) AS booking,
            pe.batch,
            pe.mode_of_payment,
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
    _attach_payments(rows)
    return rows


def _attach_payments(rows):
    """Fill each row's `payments` with every receipt recorded against that
    cheque. Partially cleared cheques have one PDC Clearance row per receipt;
    a cheque cleared in one shot has none, so it falls back to its single
    Payment Entry — which is why an already-cleared production PDC still
    renders correctly here without any backfill."""
    names = [r.pdc_entry for r in rows]
    if not names:
        return
    by_cheque = {}
    for c in frappe.get_all(
        "PDC Clearance",
        filters={"parent": ("in", names)},
        fields=["parent", "clearance_date", "amount", "mode_of_payment", "payment_entry"],
        order_by="parent asc, idx asc",
    ):
        by_cheque.setdefault(c.parent, []).append(c)

    for row in rows:
        parts = by_cheque.get(row.pdc_entry)
        if parts:
            row.payments = " | ".join(
                _payment_label(c.clearance_date, c.amount, c.mode_of_payment, c.payment_entry)
                for c in parts
            )
        elif row.status == "Cleared" and row.payment_entry:
            row.payments = _payment_label(
                row.cleared_date, row.amount, row.mode_of_payment, row.payment_entry
            )
        else:
            row.payments = ""


def _payment_label(date, amount, mode, payment_entry):
    """One receipt as `16-09-2026: 300.000 (Cash)`, the amount linking to its
    Payment Entry. The href is deliberately RELATIVE — this bench serves several
    sites by Host header, and an absolute link would send the user to whichever
    hostname the report happened to be generated under."""
    amt = f"{flt(amount):,.3f}"  # OMR is 3-decimal (Baisa); format_value drops them here
    if payment_entry:
        amt = f'<a href="/app/payment-entry/{payment_entry}">{amt}</a>'
    stamp = frappe.format_value(date, {"fieldtype": "Date"}) if date else _("Cleared")
    return f"{stamp}: {amt}" + (f" ({mode})" if mode else "")


def _money_by_status(data):
    """Money by status for the cards and chart.

    A partially cleared cheque is the one case where its face value would be a
    lie in a MONEY bucket — only `received` has actually been banked. So it
    contributes its received amount to its own bucket and its unpaid balance to
    PARTIAL_BALANCE, and the two still sum to the cheque's face value, keeping
    the buckets reconciled with Total Amount. The table columns stay face-value
    (Amount / Received / Balance side by side); this is only for the totals."""
    buckets = {}
    for row in data:
        s = row.status or "Unknown"
        if s == "Partially Cleared":
            buckets[s] = buckets.get(s, 0) + flt(row.received)
            if flt(row.balance):
                buckets[PARTIAL_BALANCE] = buckets.get(PARTIAL_BALANCE, 0) + flt(row.balance)
        else:
            buckets[s] = buckets.get(s, 0) + flt(row.amount)
    return buckets


def get_chart(data):
    if not data:
        return None
    buckets = {k: v for k, v in _money_by_status(data).items() if v}
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
    by_status = _money_by_status(data)
    return [
        {"label": _("Total PDCs"),   "value": len(data),                         "datatype": "Int"},
        {"label": _("Total Amount"), "value": total,                             "datatype": "Currency"},
        {"label": _("Pending"),      "value": by_status.get("Pending", 0),       "datatype": "Currency", "color": "orange"},
        {"label": _("Sent to Bank"), "value": by_status.get("Sent to Bank", 0),  "datatype": "Currency", "color": "purple"},
        {"label": _("Deposited"),    "value": by_status.get("Deposited", 0),     "datatype": "Currency", "color": "blue"},
        {"label": _("In Batch"),     "value": by_status.get("In Batch", 0),      "datatype": "Currency", "color": "purple"},
        {"label": _("Partially Cleared (Received)"), "value": by_status.get("Partially Cleared", 0), "datatype": "Currency", "color": "light-blue"},
        {"label": PARTIAL_BALANCE,   "value": by_status.get(PARTIAL_BALANCE, 0),  "datatype": "Currency", "color": "orange"},
        {"label": _("Cleared"),      "value": by_status.get("Cleared", 0),       "datatype": "Currency", "color": "green"},
        {"label": _("Bounced"),      "value": by_status.get("Bounced", 0),       "datatype": "Currency", "color": "red"},
        {"label": _("Substituted"),  "value": by_status.get("Substituted", 0),   "datatype": "Currency", "color": "gray"},
        {"label": _("Cancelled"),    "value": by_status.get("Cancelled", 0),     "datatype": "Currency", "color": "gray"},
        {"label": _("Returned"),     "value": by_status.get("Returned", 0),      "datatype": "Currency", "color": "gray"},
    ]
