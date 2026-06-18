"""Drop the legacy Quotation Item -> Property Booking reverse link (it blocked
cancelling bookings) and recompute each Quotation's status from its Property
Bookings. The only link kept is Property Booking.quotation -> Quotation."""

import frappe


def execute():
    settings = frappe.get_cached_doc("Misk Real Estate Settings")
    oa_item = getattr(settings, "oa_fee_item", None)

    # Remove the reverse link that caused "Cannot cancel ... linked with Property Booking"
    frappe.db.sql(
        "UPDATE `tabQuotation Item` SET property_booking = NULL "
        "WHERE property_booking IS NOT NULL AND property_booking != ''"
    )

    quotations = set(frappe.get_all(
        "Property Booking", filters={"quotation": ["is", "set"]}, pluck="quotation"
    ))
    for q in quotations:
        line_units = {
            i.item_code for i in frappe.get_all(
                "Quotation Item", filters={"parent": q}, fields=["item_code"]
            ) if i.item_code != oa_item
        }
        if not line_units:
            continue
        bookings = frappe.get_all(
            "Property Booking", filters={"quotation": q}, fields=["unit", "status", "docstatus"]
        )
        active = {b.unit for b in bookings if b.docstatus != 2 and b.status not in ("Lost", "Cancelled")}
        booked = line_units & active
        if booked == line_units:
            status = "Ordered"
        elif booked:
            status = "Partially Ordered"
        elif any(b.status == "Lost" for b in bookings):
            status = "Lost"
        else:
            status = "Open"
        frappe.db.set_value("Quotation", q, "status", status, update_modified=False)

    frappe.db.commit()
