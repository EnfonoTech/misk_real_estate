# apps/misk_real_estate/misk_real_estate/pdc_management/cron/auto_invoice.py
# B3 — PDC Auto-Invoice: runs monthly (scheduler_events monthly_long)
# Creates a Sales Invoice for each PDC Schedule row whose cheque_date is due
# and does NOT yet have a sales_invoice linked.

import frappe
from frappe import _
from frappe.utils import getdate, today, add_days


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
            # Link invoice to PDC Entry so mark_cleared() can reconcile AR
            pdc_entry_name = frappe.db.get_value(
                "PDC Schedule", row.schedule_row, "pdc_entry"
            )
            if pdc_entry_name:
                frappe.db.set_value("PDC Entry", pdc_entry_name, "sales_invoice", si_name)
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


def _create_invoice(row):
    """Create and submit a Sales Invoice for one PDC Schedule row."""
    company = row.company or frappe.defaults.get_user_default("company") or "Misk Real Estate"

    # Use OA-FEE item for Owners Association Fee rows
    settings = frappe.get_cached_doc("Misk Real Estate Settings")
    oa_item = getattr(settings, "oa_fee_item", None)
    if row.get("installment_type") == "Owners Association Fee" and oa_item:
        item_code = oa_item
    else:
        item_code = row.unit or _get_default_item(company)

    si = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": row.customer,
        "company": company,
        "posting_date": row.cheque_date,
        "due_date": add_days(row.cheque_date, 0),
        "taxes_and_charges": row.get("taxes_and_charges") or "",
        "items": [
            {
                "item_code": item_code,
                "qty": 1,
                "rate": row.amount,
                "description": _get_description(row),
            }
        ],
        "custom_pdc_schedule_row": row.schedule_row,
        "custom_property_booking": row.booking,
    })
    si.flags.ignore_permissions = True
    si.insert()
    si.submit()
    return si.name


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
