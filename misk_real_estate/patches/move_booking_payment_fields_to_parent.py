"""Property Booking now supports multiple units, each keeping its own
booking_amount/down_payment/payment_plan/OA fee/installments (per-unit
schedule) on the Property Booking Unit child row — unchanged. Only
down_payment_date moves up to the parent (applies booking-wide), and the
parent gains read-only aggregate fields (total_unit_price,
total_booking_amount, total_down_payment_amount, total_owners_association_fee)
summed across all unit rows. This patch backfills both for every existing
(today still single-unit) booking. down_payment_date is read via raw SQL
since it's no longer a Property Booking Unit field."""

import frappe
from frappe.utils import flt


def execute():
    frappe.reload_doc("real_estate", "doctype", "pdc_schedule")
    frappe.reload_doc("real_estate", "doctype", "property_booking_unit")
    frappe.reload_doc("real_estate", "doctype", "property_booking")

    # Sites deployed after the field moved to the parent never had a
    # down_payment_date column on the child table — skip the backfill there.
    has_dpd = frappe.db.has_column("Property Booking Unit", "down_payment_date")
    dpd_column = "down_payment_date, " if has_dpd else ""

    rows = frappe.db.sql(
        f"""
        SELECT parent, {dpd_column}unit_price, booking_amount,
               down_payment_amount, owners_association_fee
        FROM `tabProperty Booking Unit`
        """,
        as_dict=True,
    )
    totals = {}
    for row in rows:
        t = totals.setdefault(row.parent, {
            "down_payment_date": row.get("down_payment_date"),
            "total_unit_price": 0.0,
            "total_booking_amount": 0.0,
            "total_down_payment_amount": 0.0,
            "total_owners_association_fee": 0.0,
        })
        t["total_unit_price"] += flt(row.unit_price)
        t["total_booking_amount"] += flt(row.booking_amount)
        t["total_down_payment_amount"] += flt(row.down_payment_amount)
        t["total_owners_association_fee"] += flt(row.owners_association_fee)

    for booking_name, t in totals.items():
        values = {
            "total_unit_price": t["total_unit_price"],
            "total_amount": t["total_unit_price"] + t["total_owners_association_fee"],
            "total_booking_amount": t["total_booking_amount"],
            "total_down_payment_amount": t["total_down_payment_amount"],
            "total_owners_association_fee": t["total_owners_association_fee"],
        }
        # Don't overwrite the parent's down_payment_date on sites where the
        # child table has no value to migrate.
        if has_dpd:
            values["down_payment_date"] = t["down_payment_date"]
        frappe.db.set_value(
            "Property Booking",
            booking_name,
            values,
            update_modified=False,
        )

    frappe.db.delete("Property Setter", {"name": "Property Booking-property_unit-cannot_add_rows"})
    frappe.db.delete("Property Setter", {"name": "Property Booking-property_unit-cannot_delete_rows"})

    frappe.db.commit()
