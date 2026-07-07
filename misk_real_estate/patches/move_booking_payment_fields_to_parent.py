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

    rows = frappe.db.sql(
        """
        SELECT parent, down_payment_date, unit_price, booking_amount,
               down_payment_amount, owners_association_fee
        FROM `tabProperty Booking Unit`
        """,
        as_dict=True,
    )
    totals = {}
    for row in rows:
        t = totals.setdefault(row.parent, {
            "down_payment_date": row.down_payment_date,
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
        frappe.db.set_value(
            "Property Booking",
            booking_name,
            {
                "down_payment_date": t["down_payment_date"],
                "total_unit_price": t["total_unit_price"],
                "total_amount": t["total_unit_price"] + t["total_owners_association_fee"],
                "total_booking_amount": t["total_booking_amount"],
                "total_down_payment_amount": t["total_down_payment_amount"],
                "total_owners_association_fee": t["total_owners_association_fee"],
            },
            update_modified=False,
        )

    frappe.db.delete("Property Setter", {"name": "Property Booking-property_unit-cannot_add_rows"})
    frappe.db.delete("Property Setter", {"name": "Property Booking-property_unit-cannot_delete_rows"})

    frappe.db.commit()
