"""Multi-company helpers shared across real estate forms.

Company lives primarily on the Item Group (Building) — a Unit's own `company`
field is an optional override for cases like the shared "Services" Item Group,
where an individual item may need a company distinct from its group's.
"""

import frappe
from frappe.utils import flt


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


# Two buildings' real Project/Cost Center names in production don't follow
# the plain "MR-<Building>" rule below — confirmed against the user's own
# Project.csv / Cost Center export. Both already have project/cost_center
# set wherever this matters, so this only documents why, in case either
# ever needs (re)creating from scratch.
BUILDING_LABEL_OVERRIDES = {
    "Misk Al Mawalah": "MR-Misk Mawalah",
    "Misk Wallk": "MR-Misk Walk",
}


def ensure_building_dimensions(building):
    """Create (idempotently) a Project + Cost Center for `building` (an
    Item Group) and set them on its project/cost_center fields — the
    master-data counterpart to get_building_dimensions(). A no-op, returning
    the existing pair, if the Item Group already has both set. Company and
    its root group Cost Center are resolved from the building itself
    (resolve_unit_company / the Company's own top-level Cost Center) —
    never hardcoded, so this works for any building, present or future.
    Label follows this app's "MR-<Building>" convention unless
    BUILDING_LABEL_OVERRIDES has a specific one. Returns (project, cost_center)."""
    existing_project, existing_cost_center = get_building_dimensions(building)
    if existing_project and existing_cost_center:
        return existing_project, existing_cost_center

    company = resolve_unit_company(building)
    if not company:
        frappe.throw(f"Cannot resolve a company for building {building!r} — set Item Group.company first.")
    abbr = frappe.db.get_value("Company", company, "abbr")
    label = BUILDING_LABEL_OVERRIDES.get(building, f"MR-{building}")

    project = existing_project or frappe.db.get_value("Project", {"project_name": label}, "name")
    if not project:
        project = frappe.get_doc({
            "doctype": "Project",
            "project_name": label,
            "naming_series": "PROJ-.####",
            "company": company,
        }).insert(ignore_permissions=True).name

    cost_center = existing_cost_center or f"{label} - {abbr}"
    if not frappe.db.exists("Cost Center", cost_center):
        parent_cost_center = frappe.db.get_value(
            "Cost Center",
            {"company": company, "is_group": 1, "parent_cost_center": ("is", "not set")},
            "name",
        )
        frappe.get_doc({
            "doctype": "Cost Center",
            "cost_center_name": label,
            "parent_cost_center": parent_cost_center,
            "company": company,
            "is_group": 0,
        }).insert(ignore_permissions=True)

    frappe.db.set_value("Item Group", building, {"project": project, "cost_center": cost_center})
    return project, cost_center


def ensure_all_building_dimensions():
    """Bulk entrypoint: for every Building (an Item Group with at least one
    is_unit Item) missing Project or Cost Center, create and set them via
    ensure_building_dimensions. Safe to re-run — buildings that already
    have both are skipped/untouched. Callable directly:
        bench --site <site> execute misk_real_estate.utils.company.ensure_all_building_dimensions
    """
    buildings = frappe.db.sql_list("""
        SELECT DISTINCT item_group FROM `tabItem`
        WHERE is_unit = 1 AND item_group IS NOT NULL AND item_group != ''
    """)
    for building in buildings:
        project, cost_center = ensure_building_dimensions(building)
        print(f"{building}: {project}, {cost_center}")
    frappe.db.commit()


def get_unit_installment_weights(booking_name):
    """{unit: weight} for every unit on a Property Booking, weight = its own
    unit_price - booking_amount - down_payment_amount (its remaining
    installment total). Used to split an Installment PDC row/invoice line
    across units when there's no reliable per-unit attribution already
    recorded on it. Deliberately NOT based on the stored monthly_installment/
    number_of_installments fields — those are only ever computed when a
    Payment Plan is set, and are left at 0/blank for bookings whose PDC
    Schedule was populated directly (confirmed on a real production
    booking). unit_price/booking_amount/down_payment_amount are reliably
    set either way."""
    rows = frappe.db.get_all(
        "Property Booking Unit",
        filters={"parent": booking_name},
        fields=["unit", "unit_price", "booking_amount", "down_payment_amount"],
    )
    return {
        r.unit: flt(r.unit_price) - flt(r.booking_amount) - flt(r.down_payment_amount)
        for r in rows if r.unit
    }


def split_amount_by_unit_weight(amount, weights):
    """Split `amount` across `weights` ({unit: weight}) proportionally, one
    uniform rule used everywhere a PDC Schedule row/invoice line needs to be
    attributed to specific units: weighted by each unit's own remaining
    installment total (see get_unit_installment_weights), falling back to an
    equal split when every weight is 0 (e.g. imported directly, no Payment
    Plan ever set — real production case). The last unit (by name, for a
    stable/reproducible order) absorbs whatever's left over so the shares
    always sum to exactly `amount`, rather than drifting from rounding each
    share to 3 decimals independently. Returns [(unit, amount), ...], or []
    if `weights` is empty."""
    positive = {u: w for u, w in weights.items() if w}
    total = sum(positive.values())
    if total:
        shares = [(u, w / total) for u, w in sorted(positive.items())]
    elif weights:
        shares = [(u, 1 / len(weights)) for u in sorted(weights)]
    else:
        return []

    result = []
    running = 0.0
    for i, (u, ratio) in enumerate(shares):
        if i == len(shares) - 1:
            amt = round(flt(amount) - running, 3)
        else:
            amt = round(flt(amount) * ratio, 3)
            running = round(running + amt, 3)
        result.append((u, amt))
    return result


def get_sales_team(sales_person):
    """Sales Invoice `sales_team` child rows for a single Sales Person at
    100% contribution — used by every place this app auto-creates a Sales
    Invoice from a Property Booking, so the booking's Sales Person carries
    through instead of leaving the invoice's Sales Team table empty.
    allocated_amount is left unset — SellingController.calculate_commission
    computes it from allocated_percentage during the invoice's own
    validate(), same as it would for a manually-entered row. Returns []
    when sales_person is blank, so callers can pass it straight through."""
    if not sales_person:
        return []
    return [{"sales_person": sales_person, "allocated_percentage": 100}]


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
