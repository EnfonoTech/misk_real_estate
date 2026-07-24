import frappe


def validate(doc, method):
    _inherit_company_from_parent(doc)


def _inherit_company_from_parent(doc):
    """One-time copy-down on creation only. Frappe auto-fills any new
    document's blank "company" field from the site's global default company
    (Document._set_defaults, which runs before validate()), so a plain
    "only fill when blank" check can't tell "never set" apart from "filled
    from the global default" — always prefer the parent's own company for a
    new child group instead. Never touches an already-saved group again."""
    if not doc.is_new() or not doc.parent_item_group:
        return
    parent_company = frappe.db.get_value("Item Group", doc.parent_item_group, "company")
    if parent_company:
        doc.company = parent_company
