"""Seed the new property_unit single-row table from each existing Property
Booking's building/unit/price_list/unit_price fields, so bookings created
before this table existed render correctly without needing a resave."""

import frappe


def execute():
    frappe.reload_doc("real_estate", "doctype", "property_booking_unit")
    frappe.reload_doc("real_estate", "doctype", "property_booking")

    bookings = frappe.get_all(
        "Property Booking",
        fields=["name", "building", "unit", "price_list", "unit_price"],
    )
    for b in bookings:
        if not b.unit:
            continue
        if frappe.db.exists("Property Booking Unit", {"parent": b.name}):
            continue
        row = frappe.get_doc({
            "doctype": "Property Booking Unit",
            "parent": b.name,
            "parenttype": "Property Booking",
            "parentfield": "property_unit",
            "idx": 1,
            "building": b.building,
            "unit": b.unit,
            "price_list": b.price_list,
            "unit_price": b.unit_price,
        })
        row.insert(ignore_permissions=True)

    frappe.db.commit()
