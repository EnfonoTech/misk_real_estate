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


def get_building_dimensions(building):
    """(project, cost_center) configured on this Building (Item Group) —
    same "lives on the Item Group" convention as company (see
    resolve_unit_company). Returns (None, None) when unset or `building` is
    blank. Callers should only use these to fill a blank field, never to
    override an explicit per-unit value."""
    if not building:
        return None, None
    row = frappe.db.get_value("Item Group", building, ["project", "cost_center"], as_dict=True)
    if not row:
        return None, None
    return row.project, row.cost_center


def get_income_account(purpose, company):
    """Company-specific income account for a Sales Invoice line, from Misk
    Real Estate Settings' Income Account Mapping table — resolved from the
    LOCAL purpose the calling code already knows about the specific line
    it's building (Booking Amount/Down Payment/Installment), never by
    reading back a saved invoice's own header field, so it stays correct
    per line even if an invoice ever combines lines of different purposes.
    Returns None (never "") when unmapped — Owners Association Fee (handled
    via its own Item Default instead, not this table), blank purpose, or no
    row configured for this company/purpose — so callers can omit the
    income_account key entirely and let ERPNext's own item → item_group →
    Company.default_income_account fallback resolve it."""
    if not purpose or not company:
        return None
    return frappe.db.get_value(
        "Income Account Mapping",
        {"parent": "Misk Real Estate Settings", "company": company, "payment_purpose": purpose},
        "income_account",
    ) or None


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
