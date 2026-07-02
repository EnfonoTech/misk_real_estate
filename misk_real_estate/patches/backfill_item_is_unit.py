"""Flag existing Items as real estate units so the new is_unit checkbox
reflects data already in the system. Fixture sync (which creates the
is_unit Custom Field) runs after both patch phases in bench migrate, so
this patch creates the field itself if it isn't there yet before backfilling.

Units always have unit_status/unit_type/floor_number/unit_area_sqft
populated (set by the Excel import or manual entry); normal items
(e.g. the Owners Association Fee item) never populate these."""

import frappe


def execute():
    if not frappe.db.exists("Custom Field", "Item-is_unit"):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Item",
            "fieldname": "is_unit",
            "label": "Is Real Estate Unit",
            "fieldtype": "Check",
            "insert_after": "item_name",
            "default": "0",
        }).insert(ignore_permissions=True)

    frappe.db.sql(
        """
        UPDATE `tabItem`
        SET is_unit = 1
        WHERE is_unit = 0
          AND (
                unit_status IS NOT NULL
                OR unit_type IS NOT NULL
                OR floor_number IS NOT NULL
                OR unit_area_sqft > 0
          )
        """
    )
    frappe.db.commit()
