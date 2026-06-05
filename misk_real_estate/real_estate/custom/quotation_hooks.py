import frappe
from frappe.utils import flt


def before_validate(doc, method):
    """
    Auto-manage the consolidated OA Fee line item.
    Runs BEFORE ERPNext calculates taxes/totals so the OA line is included
    in the standard grand_total and tax calculation.
    """
    _sync_oa_fee_line(doc)


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
