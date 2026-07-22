# Copyright (c) 2026, Enfono Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, flt


def _make_unit(code):
	if frappe.db.exists("Item", code):
		frappe.db.set_value("Item", code, "unit_status", "Available")
	else:
		frappe.get_doc({
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": "Consumable",
			"is_sales_item": 1,
			"is_stock_item": 0,
			"unit_status": "Available",
		}).insert(ignore_permissions=True)
	return code


class TestPropertyBooking(FrappeTestCase):
	def setUp(self):
		self.unit_a = _make_unit("TEST-UNIT-A")
		self.unit_b = _make_unit("TEST-UNIT-B")
		self.customer = frappe.get_all("Customer", limit=1)[0].name
		self.company = frappe.get_all("Company", limit=1)[0].name

	def _new_booking(self, property_unit):
		return frappe.get_doc({
			"doctype": "Property Booking",
			"customer": self.customer,
			"company": self.company,
			"booking_date": today(),
			"invoice_generation": "Monthly",
			"property_unit": property_unit,
		})

	def test_totals_aggregate_across_units(self):
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000,
			 "booking_amount": 500, "payment_plan": "Full Payment", "owners_association_fee": 120},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 20000,
			 "booking_amount": 1000, "payment_plan": "Full Payment", "owners_association_fee": 240},
		])
		booking.insert(ignore_permissions=True)

		self.assertEqual(booking.total_unit_price, 30000)
		self.assertEqual(booking.total_booking_amount, 1500)
		self.assertEqual(booking.total_owners_association_fee, 360)
		self.assertEqual(booking.total_amount, 30360)

	def test_pdc_schedule_rows_tagged_with_owning_unit(self):
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000,
			 "booking_amount": 500, "down_payment_percentage": 10,
			 "payment_plan": "Installment 12M", "owners_association_fee": 120},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 20000,
			 "booking_amount": 20000, "payment_plan": "Full Payment", "owners_association_fee": 240},
		])
		booking.insert(ignore_permissions=True)

		units_in_schedule = {row.unit for row in booking.pdc_schedule}
		self.assertEqual(units_in_schedule, {self.unit_a, self.unit_b})
		# Unit A has 12 monthly installments + its own OA fee row; Unit B (Full
		# Payment) only gets an OA fee row.
		unit_a_rows = [r for r in booking.pdc_schedule if r.unit == self.unit_a]
		unit_b_rows = [r for r in booking.pdc_schedule if r.unit == self.unit_b]
		self.assertEqual(len(unit_a_rows), 13)
		self.assertEqual(len(unit_b_rows), 1)

	def test_reserves_every_unit_on_insert(self):
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": "Full Payment"},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 20000, "payment_plan": "Full Payment"},
		])
		booking.insert(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("Item", self.unit_a, "unit_status"), "Reserved")
		self.assertEqual(frappe.db.get_value("Item", self.unit_b, "unit_status"), "Reserved")

	def test_duplicate_unit_booking_blocked(self):
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": "Full Payment"},
		])
		booking.insert(ignore_permissions=True)

		dup = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 5000, "payment_plan": "Full Payment"},
		])
		self.assertRaises(frappe.ValidationError, dup.insert, ignore_permissions=True)

	def test_combined_advance_invoices_across_units(self):
		"""One Booking Amount invoice (with a line per unit) — not one per unit."""
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000,
			 "booking_amount": 10000, "payment_plan": "Full Payment"},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 20000,
			 "booking_amount": 20000, "payment_plan": "Full Payment"},
		])
		booking.insert(ignore_permissions=True)
		booking._create_advance_invoices()

		invoices = frappe.get_all(
			"Sales Invoice",
			filters={"custom_property_booking": booking.name, "custom_payment_purpose": "Booking Amount"},
			fields=["name"],
		)
		self.assertEqual(len(invoices), 1)
		items = frappe.get_all("Sales Invoice Item", filters={"parent": invoices[0].name}, fields=["item_code"])
		self.assertEqual({i.item_code for i in items}, {self.unit_a, self.unit_b})

		# Full Payment forces down_payment to 0 for both units — nothing to invoice.
		self.assertFalse(frappe.db.exists(
			"Sales Invoice",
			{"custom_property_booking": booking.name, "custom_payment_purpose": "Down Payment"},
		))

	def test_down_payment_plan_splits_into_pdc_schedule(self):
		"""A Down Payment Plan schedules tranches 2..N in the PDC Schedule; only
		the first tranche is billed on the upfront combined invoice."""
		if not frappe.db.exists("Down Payment Plan", "TEST-DP-2T"):
			frappe.get_doc({
				"doctype": "Down Payment Plan", "plan_name": "TEST-DP-2T", "number_of_tranches": 2,
			}).insert(ignore_permissions=True)

		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000,
			 "booking_amount": 8000, "down_payment_amount": 2000,
			 "down_payment_plan": "TEST-DP-2T"},
		])
		booking.insert(ignore_permissions=True)

		dp_rows = [r for r in booking.pdc_schedule if r.installment_type == "Down Payment"]
		self.assertEqual(len(dp_rows), 1)  # tranche 2 only — tranche 1 is invoiced upfront
		self.assertEqual(flt(dp_rows[0].amount), 1000)
		self.assertEqual(flt(booking.table_total), 1000)
		self.assertEqual(flt(booking.table_difference), 0)

		booking._create_advance_invoices()
		dp_invoice = frappe.db.get_value(
			"Sales Invoice",
			{"custom_property_booking": booking.name, "custom_payment_purpose": "Down Payment"},
			"name",
		)
		self.assertTrue(dp_invoice)
		items = frappe.get_all("Sales Invoice Item", filters={"parent": dp_invoice}, fields=["rate"])
		self.assertEqual(len(items), 1)
		self.assertEqual(flt(items[0].rate), 1000)  # only the first tranche billed upfront
