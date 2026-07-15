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

    # The flat unit columns only exist on sites that ran the old single-unit
    # Sales Agreement. Sites deployed after the units child table was
    # introduced never had them, and have nothing to backfill.
    legacy_columns = [
        "building", "unit", "unit_area_sqft", "unit_type", "floor_number",
        "payment_plan", "number_of_installments", "monthly_installment",
    ]
    existing = [c for c in legacy_columns if frappe.db.has_column("Sales Agreement", c)]
    if "unit" not in existing:
        return

    rows = frappe.db.sql(
        f"""
        SELECT name, selling_price, {", ".join(existing)}
        FROM `tabSales Agreement`
        """,
        as_dict=True,
    )
    for row in rows:
        if not row.get("unit"):
            continue
        if frappe.db.exists("Sales Agreement Unit", {"parent": row.name}):
            continue
        unit_row = frappe.get_doc({
            "doctype": "Sales Agreement Unit",
            "parent": row.name,
            "parenttype": "Sales Agreement",
            "parentfield": "units",
            "idx": 1,
            "building": row.get("building"),
            "unit": row.get("unit"),
            "unit_price": row.selling_price,
            "unit_area_sqft": row.get("unit_area_sqft"),
            "unit_type": row.get("unit_type"),
            "floor_number": row.get("floor_number"),
            "payment_plan": row.get("payment_plan"),
            "number_of_installments": row.get("number_of_installments"),
            "monthly_installment": row.get("monthly_installment"),
        })
        unit_row.insert(ignore_permissions=True)

    frappe.db.commit()
