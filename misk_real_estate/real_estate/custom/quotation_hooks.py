import frappe
from frappe.utils import flt


def validate(doc, method):
    """Compute total OA fee and grand total including OA from Quotation items."""
    total_oa = sum(flt(item.owners_association_fee) for item in doc.items)
    doc.total_oa_fee = total_oa
    doc.grand_total_with_oa = flt(doc.grand_total) + total_oa
