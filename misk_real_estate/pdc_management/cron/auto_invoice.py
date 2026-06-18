# apps/misk_real_estate/misk_real_estate/pdc_management/cron/auto_invoice.py
# B3 — PDC Auto-Invoice: runs monthly (scheduler_events monthly_long)
# Creates a Sales Invoice for each PDC Schedule row whose cheque_date is due
# and does NOT yet have a sales_invoice linked.

import frappe
from frappe import _
from frappe.utils import getdate, today, add_days, flt


def run():
    """
    Entry point called by Frappe scheduler (daily_long).
    Creates Sales Invoices for all PDC Schedule rows whose cheque_date <= today.
    Each invoice is raised on its own cheque date — no fixed day-of-month needed.
    Callable manually: bench --site <site> execute misk_real_estate.pdc_management.cron.auto_invoice.run
    """
    _generate_due_invoices()


def _generate_due_invoices():
    """
    Find all PDC Schedule rows that are:
      - status = Pending or In Batch or Deposited (not Cleared/Bounced/Cancelled)
      - cheque_date <= today
      - sales_invoice is blank
    Then create a Sales Invoice for each.
    """
    today_date = getdate(today())

    # Get all submitted Property Bookings with pdc_schedule child rows
    due_rows = frappe.db.sql(
        """
        SELECT
            ps.name AS schedule_row,
            ps.parent AS booking,
            ps.cheque_date,
            ps.amount,
            ps.net_amount,
            ps.cheque_no,
            ps.installment_type,
            ps.status,
            pb.customer,
            pb.unit,
            pb.company,
            pb.taxes_and_charges
        FROM `tabPDC Schedule` ps
        INNER JOIN `tabProperty Booking` pb ON pb.name = ps.parent
        WHERE pb.docstatus = 1
          AND (pb.invoice_generation = 'Monthly' OR pb.invoice_generation IS NULL OR pb.invoice_generation = '')
          AND ps.cheque_date <= %(today)s
          AND (ps.sales_invoice IS NULL OR ps.sales_invoice = '')
          AND ps.status NOT IN ('Cleared', 'Bounced', 'Cancelled')
        ORDER BY ps.cheque_date ASC
        """,
        {"today": today_date},
        as_dict=True,
    )

    if not due_rows:
        frappe.logger().info("PDC Auto-Invoice: no due PDC rows found.")
        return

    created = []
    errors = []

    for row in due_rows:
        try:
            si_name = _create_invoice(row)
            # Link invoice back to PDC Schedule row
            frappe.db.set_value("PDC Schedule", row.schedule_row, "sales_invoice", si_name)
            # Link invoice to the PDC Entry's allocation row so mark_cleared() reconciles AR
            pdc_entry_name = frappe.db.get_value(
                "PDC Schedule", row.schedule_row, "pdc_entry"
            )
            if pdc_entry_name:
                from misk_real_estate.pdc_management.doctype.pdc_entry.pdc_entry import link_invoice_to_allocation
                link_invoice_to_allocation(pdc_entry_name, row.booking, row.get("installment_type"), si_name)
            created.append(si_name)
        except Exception:
            errors.append(row.schedule_row)
            frappe.log_error(
                frappe.get_traceback(),
                f"PDC Auto-Invoice failed for schedule row {row.schedule_row}",
            )

    frappe.db.commit()
    frappe.logger().info(
        f"PDC Auto-Invoice: created {len(created)} invoices, {len(errors)} errors."
    )


def _create_invoice(row, submit=False, payment_purpose=None):
    """Create a Sales Invoice for one PDC Schedule row (or an advance payment row).
    Left as Draft by default — finance reviews and submits manually.
    Pass submit=True to submit immediately. payment_purpose tags the invoice
    (Booking Amount / Down Payment / Installment / Owners Association Fee).
    """
    company = row.company or frappe.defaults.get_user_default("company") or "Misk Real Estate"

    # Use OA-FEE item for Owners Association Fee rows
    settings = frappe.get_cached_doc("Misk Real Estate Settings")
    oa_item = getattr(settings, "oa_fee_item", None)
    if row.get("installment_type") == "Owners Association Fee" and oa_item:
        item_code = oa_item
    else:
        item_code = row.unit or _get_default_item(company)

    taxes_and_charges = row.get("taxes_and_charges") or ""

    if taxes_and_charges:
        rate = _invoice_item_rate(row, taxes_and_charges)
        tax_rows = []
    else:
        # No transaction-level template — build tax rows from item's Item Tax Template
        tax_rows = _build_tax_rows_from_item_template(item_code)
        # Use net_amount when we have tax rows (exclusive); otherwise use total
        rate = flt(row.get("net_amount") or row.get("amount")) if tax_rows else flt(row.get("amount"))

    posting_date = getdate(row.cheque_date or today())
    due_date = max(posting_date, getdate(row.cheque_date)) if row.cheque_date else posting_date

    si = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": row.customer,
        "company": company,
        "posting_date": posting_date,
        "due_date": due_date,
        "taxes_and_charges": taxes_and_charges,
        "taxes": tax_rows,
        "items": [
            {
                "item_code": item_code,
                "qty": 1,
                "rate": rate,
                "description": _get_description(row),
            }
        ],
        "custom_pdc_schedule_row": row.schedule_row,
        "custom_property_booking": row.booking,
        "custom_payment_purpose": payment_purpose or row.get("installment_type") or "Installment",
    })
    si.flags.ignore_permissions = True
    si.insert()
    if submit:
        si.submit()
    return si.name


def _build_tax_rows_from_item_template(item_code):
    """Return SI taxes rows built from an item's (or item group's) Item Tax Template.
    Returns empty list if no template or all rates are 0.
    """
    # Item level first, then item group
    template = frappe.db.get_value("Item Tax", {"parent": item_code}, "item_tax_template")
    if not template:
        item_group = frappe.db.get_value("Item", item_code, "item_group")
        if item_group:
            template = frappe.db.get_value("Item Tax", {"parent": item_group}, "item_tax_template")
    if not template:
        return []

    detail_rows = frappe.db.get_all(
        "Item Tax Template Detail",
        filters={"parent": template},
        fields=["tax_type", "tax_rate"],
    )
    return [
        {
            "charge_type": "On Net Total",
            "account_head": r.tax_type,
            "description": r.tax_type,
            "rate": flt(r.tax_rate),
        }
        for r in detail_rows
        if flt(r.tax_rate) > 0
    ]


def _invoice_item_rate(row, taxes_and_charges):
    """
    Determine the item rate to use in the Sales Invoice.
    - Exclusive tax (taxes_and_charges set, not inclusive): use net_amount so ERPNext adds tax on top.
    - Inclusive tax (taxes_and_charges set, included_in_print_rate): use amount so ERPNext extracts tax.
    - No taxes_and_charges: use amount (total), no tax recalculated.
    """
    total = flt(row.get("amount"))
    net   = flt(row.get("net_amount"))

    if not taxes_and_charges or not net or net == total:
        return total  # no tax or no breakdown available

    is_inclusive = frappe.db.get_value(
        "Sales Taxes and Charges",
        {"parent": taxes_and_charges, "parenttype": "Sales Taxes and Charges Template",
         "included_in_print_rate": 1},
        "name",
    )
    return total if is_inclusive else net


def _get_description(row):
    from frappe.utils import formatdate
    type_label = row.installment_type or "Installment"
    return f"{type_label} — Cheque {row.cheque_no or 'N/A'} — Due {formatdate(row.cheque_date)}"


def _get_default_item(company):
    """Return a fallback item code for invoice lines."""
    item = frappe.db.get_value(
        "Item",
        {"item_name": "Real Estate Installment", "disabled": 0},
        "name",
    )
    if item:
        return item
    # Create it if it doesn't exist
    i = frappe.get_doc({
        "doctype": "Item",
        "item_code": "RE-INSTALLMENT",
        "item_name": "Real Estate Installment",
        "item_group": "Services",
        "is_sales_item": 1,
        "is_purchase_item": 0,
        "is_stock_item": 0,
    })
    i.insert(ignore_permissions=True)
    return i.name
