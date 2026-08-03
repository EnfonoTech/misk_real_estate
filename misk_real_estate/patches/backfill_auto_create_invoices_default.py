"""New opt-out field Misk Real Estate Settings.auto_create_invoices (default
1) was added to let auto-invoicing be turned off. On an existing site, the
Singles row for a brand-new field reads back as falsy until explicitly
saved — which would silently disable auto-invoicing the moment this code
deploys. Backfill it to 1 (preserving prior behavior) if the site already
has a Settings record."""

import frappe


def execute():
    if not frappe.db.exists("DocType", "Misk Real Estate Settings"):
        return
    frappe.db.set_single_value("Misk Real Estate Settings", "auto_create_invoices", 1)
