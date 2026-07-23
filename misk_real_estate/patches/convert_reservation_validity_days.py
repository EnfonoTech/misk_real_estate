"""Reservation.validity_days changed from a Select ("7 Days"/"15 Days") to a
plain Int (number of days). Runs pre_model_sync so the column is still varchar
here — convert existing values before the schema alter tries to cast them."""

import re

import frappe

DEFAULT_DAYS = 15


def execute():
    if not frappe.db.table_exists("Reservation"):
        return

    rows = frappe.db.sql(
        "SELECT name, validity_days FROM `tabReservation` WHERE validity_days IS NOT NULL"
    )
    for name, value in rows:
        match = re.search(r"\d+", value or "")
        days = int(match.group()) if match else DEFAULT_DAYS
        frappe.db.set_value("Reservation", name, "validity_days", days, update_modified=False)
    frappe.db.commit()
