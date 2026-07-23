# Copyright (c) 2026, Enfono Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate


class TestReservation(FrappeTestCase):
	def test_reservation_validity_date_default(self):
		doc = frappe.new_doc("Reservation")
		doc.reservation_date = getdate()
		doc.validity_days = 15
		doc._set_reservation_validity_date()
		self.assertEqual(doc.reservation_validity_date, add_days(getdate(), 15))

	def test_reservation_validity_date_not_overridden(self):
		doc = frappe.new_doc("Reservation")
		doc.reservation_date = getdate()
		doc.validity_days = 7
		manual_date = add_days(getdate(), 30)
		doc.reservation_validity_date = manual_date
		doc._set_reservation_validity_date()
		self.assertEqual(doc.reservation_validity_date, manual_date)

	def test_owners_association_fee_folds_into_total(self):
		doc = frappe.new_doc("Reservation")
		doc.append("items", {"unit": "TEST-UNIT", "selling_price": 100000, "owners_association_fee": 500})
		doc._calculate_taxes_and_totals()
		self.assertEqual(doc.total, 100500)
		self.assertEqual(doc.grand_total, 100500)

	def test_reservation_submittable_without_quotation(self):
		company = frappe.db.get_value("Company", {}, "name")
		customer = frappe.db.get_value("Customer", {}, "name")
		unit = frappe.db.get_value("Item", {"unit_status": "Available"}, "name")
		if not (company and customer and unit):
			self.skipTest("Requires an existing Company, Customer and available unit Item.")

		doc = frappe.new_doc("Reservation")
		doc.company = company
		doc.customer_name = customer
		doc.reservation_date = getdate()
		doc.validity_days = 7
		doc.append("items", {"unit": unit, "selling_price": 100000})
		doc.insert()
		doc.submit()

		self.assertFalse(doc.quotation)
		self.assertEqual(doc.docstatus, 1)

		doc.cancel()
