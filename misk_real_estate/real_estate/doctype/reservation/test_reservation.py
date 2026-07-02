# Copyright (c) 2026, Enfono Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate


class TestReservation(FrappeTestCase):
	def test_reservation_validity_date_default(self):
		doc = frappe.new_doc("Reservation")
		doc.reservation_date = getdate()
		doc.validity_days = "15 Days"
		doc._set_reservation_validity_date()
		self.assertEqual(doc.reservation_validity_date, add_days(getdate(), 15))

	def test_reservation_validity_date_not_overridden(self):
		doc = frappe.new_doc("Reservation")
		doc.reservation_date = getdate()
		doc.validity_days = "7 Days"
		manual_date = add_days(getdate(), 30)
		doc.reservation_validity_date = manual_date
		doc._set_reservation_validity_date()
		self.assertEqual(doc.reservation_validity_date, manual_date)
