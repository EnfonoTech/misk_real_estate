"""Sales Agreement's building/unit/unit_area_sqft/unit_type/floor_number were
flat fields snapshotting the (previously single) unit on the booking. Now that
a booking can hold multiple units, Sales Agreement lists them in a `units`
child table instead. Seed that table from each existing agreement's old flat
fields (read via raw SQL — the columns are no longer in the doctype JSON) so
the original snapshot is preserved rather than re-pulled from the booking's
current (possibly since-changed) state."""

import frappe


def execute():
    frappe.reload_doc("real_estate", "doctype", "sales_agreement_unit")
    frappe.reload_doc("real_estate", "doctype", "sales_agreement")

    rows = frappe.db.sql(
        """
        SELECT name, building, unit, unit_area_sqft, unit_type, floor_number,
               selling_price, payment_plan, number_of_installments, monthly_installment
        FROM `tabSales Agreement`
        """,
        as_dict=True,
    )
    for row in rows:
        if not row.unit:
            continue
        if frappe.db.exists("Sales Agreement Unit", {"parent": row.name}):
            continue
        unit_row = frappe.get_doc({
            "doctype": "Sales Agreement Unit",
            "parent": row.name,
            "parenttype": "Sales Agreement",
            "parentfield": "units",
            "idx": 1,
            "building": row.building,
            "unit": row.unit,
            "unit_price": row.selling_price,
            "unit_area_sqft": row.unit_area_sqft,
            "unit_type": row.unit_type,
            "floor_number": row.floor_number,
            "payment_plan": row.payment_plan,
            "number_of_installments": row.number_of_installments,
            "monthly_installment": row.monthly_installment,
        })
        unit_row.insert(ignore_permissions=True)

    frappe.db.commit()
