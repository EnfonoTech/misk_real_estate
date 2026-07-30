"""Multi-company helpers shared across real estate forms.

Company lives primarily on the Item Group (Building) — a Unit's own `company`
field is an optional override for cases like the shared "Services" Item Group,
where an individual item may need a company distinct from its group's.
"""

import frappe


def get_item_company(item_code):
    """Effective company for a unit/item: its own override, else its Item
    Group's (Building's) company."""
    item = frappe.db.get_value("Item", item_code, ["company", "item_group"], as_dict=True)
    if not item:
        return None
    if item.company:
        return item.company
    return frappe.db.get_value("Item Group", item.item_group, "company")


def resolve_unit_company(item_group):
    """Default company to store on a new/updated unit under `item_group`:
    the Building's own company if set, else Misk Real Estate Settings'
    default. Used to actually populate Item.company (not just resolve it
    live) — see item_hooks.validate and utils/import_units.py."""
    if item_group:
        ig_company = frappe.db.get_value("Item Group", item_group, "company")
        if ig_company:
            return ig_company
    return frappe.db.get_single_value("Misk Real Estate Settings", "default_company")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_units_for_company(doctype, txt, searchfield, start, page_len, filters):
    """Unit picker shared by Quotation Item / Property Booking Unit / Reservation
    Item's standalone (no-quotation) branch — layers a company condition (item's
    own override, else its Item Group's) on top of the existing building/
    unit_status scoping, only when the calling form actually has a company set."""
    filters = filters or {}
    conditions = ["i.is_unit = 1", "i.item_code LIKE %(txt)s"]
    values = {"txt": f"%{txt}%", "page_len": page_len, "start": start}

    if filters.get("unit_status"):
        conditions.append("COALESCE(i.unit_status, 'Available') = %(unit_status)s")
        values["unit_status"] = filters["unit_status"]

    if filters.get("building"):
        conditions.append("i.item_group = %(building)s")
        values["building"] = filters["building"]

    if filters.get("company"):
        conditions.append("COALESCE(i.company, ig.company) = %(company)s")
        values["company"] = filters["company"]

    where = " AND ".join(conditions)
    return frappe.db.sql(
        f"""
        SELECT i.item_code, i.item_name
        FROM `tabItem` i
        LEFT JOIN `tabItem Group` ig ON ig.name = i.item_group
        WHERE {where}
        ORDER BY i.item_code
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        values,
    )
