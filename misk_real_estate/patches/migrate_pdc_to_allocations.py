"""Convert legacy single-booking PDC Entries to the unified allocation model:
one allocation row per existing cheque, built from its header fields.
Header fields are kept as mirrors, so this is purely additive."""

import frappe


def execute():
    frappe.reload_doc("pdc_management", "doctype", "pdc_allocation")
    frappe.reload_doc("pdc_management", "doctype", "pdc_entry")

    entries = frappe.get_all(
        "PDC Entry",
        fields=["name", "booking", "unit", "building", "installment_type", "amount", "sales_invoice"],
    )
    migrated = 0
    for e in entries:
        if frappe.db.exists("PDC Allocation", {"parent": e.name}):
            continue  # already has rows
        if not e.booking:
            continue  # nothing to seed from
        child = frappe.get_doc({
            "doctype": "PDC Allocation",
            "parent": e.name,
            "parenttype": "PDC Entry",
            "parentfield": "allocations",
            "idx": 1,
            "property_booking": e.booking,
            "purpose": e.installment_type or "Installment",
            "building": e.building,
            "unit": e.unit,
            "sales_invoice": e.sales_invoice or "",
            "allocated_amount": e.amount,
        })
        child.insert(ignore_permissions=True)
        migrated += 1

    frappe.db.commit()
    frappe.logger().info(f"migrate_pdc_to_allocations: created {migrated} allocation rows")
