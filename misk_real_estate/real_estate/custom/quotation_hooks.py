import frappe
from frappe.utils import flt


def before_validate(doc, method):
    """
    Auto-manage the consolidated OA Fee line item.
    Runs BEFORE ERPNext calculates taxes/totals so the OA line is included
    in the standard grand_total and tax calculation.
    """
    _set_default_sales_person(doc)
    _sync_oa_fee_line(doc)


def _resolve_sales_person(user):
    """Sales Person linked to a user via Employee.user_id -> Sales Person.employee."""
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        return None
    return frappe.db.get_value("Sales Person", {"employee": employee}, "name")


def _set_default_sales_person(doc):
    if not doc.is_new() or doc.get("custom_sales_person"):
        return
    sales_person = _resolve_sales_person(frappe.session.user)
    if sales_person:
        doc.custom_sales_person = sales_person


@frappe.whitelist()
def get_default_sales_person():
    """Used by quotation.js to pre-fill Sales Person on a new, unsaved Quotation."""
    return _resolve_sales_person(frappe.session.user) or ""


def _sync_oa_fee_line(doc):
    settings = frappe.get_cached_doc("Misk Real Estate Settings")
    oa_item = getattr(settings, "oa_fee_item", None)
    if not oa_item:
        return

    # Sum OA fees from all unit rows (skip existing OA fee lines)
    total_oa = sum(
        flt(item.owners_association_fee)
        for item in doc.items
        if item.item_code != oa_item
    )

    # Remove existing OA fee line(s) (will be re-added if needed)
    doc.items = [item for item in doc.items if item.item_code != oa_item]

    if total_oa > 0:
        oa_uom = frappe.db.get_value("Item", oa_item, "stock_uom") or "Nos"
        oa_name = frappe.db.get_value("Item", oa_item, "item_name") or "Owners Association Fee"
        doc.append("items", {
            "item_code": oa_item,
            "item_name": oa_name,
            "description": "Owners Association Fee",
            "qty": 1,
            "uom": oa_uom,
            "rate": total_oa,
            "conversion_factor": 1,
        })
