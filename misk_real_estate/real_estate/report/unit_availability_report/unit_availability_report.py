# apps/misk_real_estate/misk_real_estate/real_estate/report/unit_availability_report/unit_availability_report.py

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    summary = get_summary(data)
    chart = get_chart(data)
    return columns, data, None, chart, summary


def get_columns():
    return [
        {
            "fieldname": "building",
            "label": _("Building"),
            "fieldtype": "Link",
            "options": "Item Group",
            "width": 160,
        },
        {
            "fieldname": "unit_id",
            "label": _("Unit ID"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 130,
        },
        {
            "fieldname": "unit_name",
            "label": _("Unit Name"),
            "fieldtype": "Data",
            "width": 160,
        },
        {
            "fieldname": "floor_number",
            "label": _("Floor"),
            "fieldtype": "Int",
            "width": 70,
        },
        {
            "fieldname": "unit_area_sqft",
            "label": _("Area (Sq Ft)"),
            "fieldtype": "Float",
            "width": 110,
        },
        {
            "fieldname": "unit_status",
            "label": _("Status"),
            "fieldtype": "Data",
            "width": 110,
        },
        {
            "fieldname": "customer",
            "label": _("Customer"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 160,
        },
        {
            "fieldname": "customer_name",
            "label": _("Customer Name"),
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "fieldname": "booking",
            "label": _("Booking"),
            "fieldtype": "Link",
            "options": "Property Booking",
            "width": 140,
        },
        {
            "fieldname": "unit_price",
            "label": _("Unit Price (OMR)"),
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "fieldname": "booking_date",
            "label": _("Booking Date"),
            "fieldtype": "Date",
            "width": 110,
        },
    ]


def get_data(filters):
    conditions = "WHERE i.disabled = 0 AND i.is_sales_item = 1"
    params = {}

    if filters.get("building"):
        conditions += " AND i.item_group = %(building)s"
        params["building"] = filters["building"]

    if filters.get("unit_status"):
        conditions += " AND COALESCE(i.unit_status, 'Available') = %(unit_status)s"
        params["unit_status"] = filters["unit_status"]

    rows = frappe.db.sql(
        """
        SELECT
            i.item_group          AS building,
            i.item_code           AS unit_id,
            i.item_name           AS unit_name,
            i.floor_number        AS floor_number,
            i.unit_area_sqft      AS unit_area_sqft,
            COALESCE(i.unit_status, 'Available') AS unit_status,
            pb.customer           AS customer,
            pb.customer_name      AS customer_name,
            pb.name               AS booking,
            pb.unit_price         AS unit_price,
            pb.booking_date       AS booking_date
        FROM `tabItem` i
        LEFT JOIN `tabProperty Booking` pb
            ON pb.unit = i.item_code
            AND pb.docstatus = 1
            AND pb.status NOT IN ('Cancelled')
        {conditions}
        ORDER BY i.item_group, i.item_code
        """.format(conditions=conditions),
        params,
        as_dict=True,
    )
    return rows


def get_summary(data):
    total = len(data)
    available = sum(1 for r in data if r.unit_status == "Available")
    booked = sum(1 for r in data if r.unit_status == "Booked")
    sold = sum(1 for r in data if r.unit_status == "Sold")
    reserved = sum(1 for r in data if r.unit_status == "Reserved")

    return [
        {"label": _("Total Units"), "value": total, "datatype": "Int", "indicator": "blue"},
        {"label": _("Available"), "value": available, "datatype": "Int", "indicator": "green"},
        {"label": _("Booked"), "value": booked, "datatype": "Int", "indicator": "orange"},
        {"label": _("Sold"), "value": sold, "datatype": "Int", "indicator": "red"},
        {"label": _("Reserved"), "value": reserved, "datatype": "Int", "indicator": "grey"},
    ]


def get_chart(data):
    buildings = {}
    for row in data:
        b = row.building or "Unknown"
        if b not in buildings:
            buildings[b] = {"Available": 0, "Booked": 0, "Sold": 0, "Reserved": 0}
        status = row.unit_status or "Available"
        if status in buildings[b]:
            buildings[b][status] += 1

    labels = list(buildings.keys())
    return {
        "data": {
            "labels": labels,
            "datasets": [
                {"name": _("Available"), "values": [buildings[b]["Available"] for b in labels]},
                {"name": _("Booked"), "values": [buildings[b]["Booked"] for b in labels]},
                {"name": _("Sold"), "values": [buildings[b]["Sold"] for b in labels]},
                {"name": _("Reserved"), "values": [buildings[b]["Reserved"] for b in labels]},
            ],
        },
        "type": "bar",
        "barOptions": {"stacked": True},
        "colors": ["#28a745", "#fd7e14", "#dc3545", "#6c757d"],
    }
