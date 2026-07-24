# Copyright (c) 2026, Enfono Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, flt, add_months, getdate


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
		# Tests that submit() commit real rows (submit isn't rolled back the
		# way plain insert() is) — release any leftover booking a prior test
		# run left holding these units, so re-runs don't hit "already Reserved".
		self._release_stale_bookings(self.unit_a)
		self._release_stale_bookings(self.unit_b)
		# Defensive, not just cleanup-after: a commit() anywhere mid-suite (several
		# functions under test call it) can make an in-test setting change stick
		# around past its own test's addCleanup, poisoning every later test that
		# submits a booking. Force the known-good default before every test
		# instead of trusting that every prior test's cleanup actually ran.
		frappe.db.set_single_value("Misk Real Estate Settings", "auto_submit_invoices", 0)

	def _release_stale_bookings(self, unit):
		for row in frappe.get_all("Property Booking Unit", filters={"unit": unit}, fields=["parent"]):
			booking_name = row.parent
			if not frappe.db.exists("Property Booking", booking_name):
				continue

			# A leftover booking and its own invoices can reference each other
			# both ways (Sales Invoice.custom_property_booking, and PDC
			# Schedule.sales_invoice on the booking's own child rows) — Frappe's
			# back-link check blocks cancelling EITHER side first because the
			# other side still points to it. Break both link directions via a
			# direct write before cancelling anything, so neither cancel trips
			# over the other.
			invoices = frappe.get_all(
				"Sales Invoice", filters={"custom_property_booking": booking_name}, fields=["name", "docstatus"]
			)
			for si in invoices:
				frappe.db.set_value("Sales Invoice", si.name, "custom_property_booking", "")
			if frappe.db.exists("PDC Schedule", {"parent": booking_name}):
				frappe.db.set_value("PDC Schedule", {"parent": booking_name}, "sales_invoice", "")

			for si in invoices:
				if si.docstatus == 1:
					frappe.get_doc("Sales Invoice", si.name).cancel()

			# A leftover Sales Agreement also back-links to the booking and blocks
			# its cancel — cancel it first if submitted (force on delete_doc
			# doesn't bypass the submitted-doc delete restriction).
			for sa in frappe.get_all(
				"Sales Agreement", filters={"property_booking": booking_name}, fields=["name", "docstatus"]
			):
				if sa.docstatus == 1:
					frappe.get_doc("Sales Agreement", sa.name).cancel()
				frappe.delete_doc("Sales Agreement", sa.name, force=True, ignore_permissions=True)

			doc = frappe.get_doc("Property Booking", booking_name)
			if doc.docstatus == 1:
				doc.cancel()
			if frappe.db.exists("Property Booking", booking_name):
				frappe.delete_doc("Property Booking", booking_name, force=True, ignore_permissions=True)

	def _new_booking(self, property_unit):
		return frappe.get_doc({
			"doctype": "Property Booking",
			"customer": self.customer,
			"company": self.company,
			"booking_date": today(),
			"invoice_generation": "Monthly",
			"property_unit": property_unit,
		})

	def _make_project(self, project_name):
		existing = frappe.db.get_value(
			"Project", {"project_name": project_name, "company": self.company}, "name"
		)
		if existing:
			return existing
		return frappe.get_doc({
			"doctype": "Project", "project_name": project_name, "company": self.company,
		}).insert(ignore_permissions=True).name

	def _make_cost_center(self, cost_center_name):
		existing = frappe.db.get_value(
			"Cost Center", {"cost_center_name": cost_center_name, "company": self.company}, "name"
		)
		if existing:
			return existing
		parent = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 1}, "name")
		return frappe.get_doc({
			"doctype": "Cost Center", "cost_center_name": cost_center_name,
			"company": self.company, "parent_cost_center": parent, "is_group": 0,
		}).insert(ignore_permissions=True).name

	def _make_single_installment_plan(self):
		if frappe.db.exists("Payment Plan", "TEST-1-INSTALLMENT"):
			return "TEST-1-INSTALLMENT"
		return frappe.get_doc({
			"doctype": "Payment Plan", "plan_name": "TEST-1-INSTALLMENT", "number_of_installments": 1,
		}).insert(ignore_permissions=True).name

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

	def test_pdc_schedule_stays_per_unit_when_due_dates_dont_coincide(self):
		"""Different plans (12 monthly installments vs. Full Payment) put each
		unit's rows on different dates, so nothing combines — every row keeps
		today's single-unit shape (unit set, no unit_breakdown)."""
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
		self.assertTrue(all(not r.unit_breakdown for r in booking.pdc_schedule))
		# Unit A has 12 monthly installments + its own OA fee row; Unit B (Full
		# Payment) only gets an OA fee row.
		unit_a_rows = [r for r in booking.pdc_schedule if r.unit == self.unit_a]
		unit_b_rows = [r for r in booking.pdc_schedule if r.unit == self.unit_b]
		self.assertEqual(len(unit_a_rows), 13)
		self.assertEqual(len(unit_b_rows), 1)

	def test_pdc_schedule_combines_matching_installment_dates_across_units(self):
		"""Two units on the SAME Payment Plan share every due date — their
		installment amounts combine into ONE row (one physical cheque) instead
		of one row per unit."""
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 12000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 24000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
		])
		booking.insert(ignore_permissions=True)

		installment_rows = [r for r in booking.pdc_schedule if r.installment_type == "Installment"]
		self.assertEqual(len(installment_rows), 12)  # combined, not 24
		for row in installment_rows:
			self.assertEqual(row.unit, "")
			self.assertEqual(flt(row.amount), 1500)
			breakdown = {c["unit"]: flt(c["amount"]) for c in frappe.parse_json(row.unit_breakdown)}
			self.assertEqual(breakdown, {self.unit_a: 500, self.unit_b: 1000})

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

	def test_build_pdc_row_invoice_items_combined_vs_single(self):
		"""A single-unit PDC row still produces one invoice line; a combined
		row (unit_breakdown populated) produces one line per unit."""
		from misk_real_estate.pdc_management.cron.auto_invoice import build_pdc_row_invoice_items

		single_row = frappe._dict(
			installment_type="Installment", unit=self.unit_a,
			net_amount=500, tax_amount=0, amount=500, unit_breakdown=None,
		)
		items, _tax_rows, custom_unit = build_pdc_row_invoice_items(
			single_row, "", None, self.company, "desc", "NONEXISTENT-BOOKING"
		)
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["item_code"], self.unit_a)
		self.assertEqual(items[0]["rate"], 500)
		self.assertEqual(custom_unit, self.unit_a)

		combined_row = frappe._dict(
			installment_type="Installment", unit="", net_amount=1500, tax_amount=0, amount=1500,
			unit_breakdown=[
				{"unit": self.unit_a, "net_amount": 500, "tax_amount": 0, "amount": 500},
				{"unit": self.unit_b, "net_amount": 1000, "tax_amount": 0, "amount": 1000},
			],
		)
		items, _tax_rows, custom_unit = build_pdc_row_invoice_items(
			combined_row, "", None, self.company, "desc", "NONEXISTENT-BOOKING"
		)
		self.assertEqual({i["item_code"] for i in items}, {self.unit_a, self.unit_b})
		self.assertEqual(sum(flt(i["rate"]) for i in items), 1500)
		self.assertEqual(custom_unit, "")

	def test_dimensions_propagate_to_advance_invoice(self):
		"""Booking-level Project/Cost Center default onto each Sales Invoice
		Item line; a unit-level override wins over the booking default."""
		project = self._make_project("TEST-PROJECT-ADV")
		cost_center_default = self._make_cost_center("TEST-CC-ADV-DEFAULT")
		cost_center_override = self._make_cost_center("TEST-CC-ADV-OVERRIDE")

		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000,
			 "booking_amount": 10000, "payment_plan": "Full Payment",
			 "cost_center": cost_center_override},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 20000,
			 "booking_amount": 20000, "payment_plan": "Full Payment"},
		])
		booking.project = project
		booking.cost_center = cost_center_default
		booking.insert(ignore_permissions=True)
		booking._create_advance_invoices()

		si_name = frappe.db.get_value(
			"Sales Invoice",
			{"custom_property_booking": booking.name, "custom_payment_purpose": "Booking Amount"},
			"name",
		)
		si = frappe.get_doc("Sales Invoice", si_name)
		self.assertEqual(si.project, project)
		self.assertEqual(si.cost_center, cost_center_default)
		dims = {i.item_code: (i.project, i.cost_center) for i in si.items}
		self.assertEqual(dims[self.unit_a], (project, cost_center_override))  # unit override wins
		self.assertEqual(dims[self.unit_b], (project, cost_center_default))  # inherits booking default

	def test_dimensions_resolve_for_combined_pdc_row(self):
		"""Each unit's line in a combined Installment invoice resolves its own
		Project/Cost Center — override where set, else the booking default."""
		project = self._make_project("TEST-PROJECT-PDC")
		cost_center_default = self._make_cost_center("TEST-CC-PDC-DEFAULT")
		cost_center_override = self._make_cost_center("TEST-CC-PDC-OVERRIDE")

		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 12000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M",
			 "cost_center": cost_center_override},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 24000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
		])
		booking.project = project
		booking.cost_center = cost_center_default
		booking.insert(ignore_permissions=True)

		from misk_real_estate.pdc_management.cron.auto_invoice import build_pdc_row_invoice_items
		combined_row = next(r for r in booking.pdc_schedule if r.installment_type == "Installment")
		items, _tax_rows, _custom_unit = build_pdc_row_invoice_items(
			combined_row, "", None, self.company, "desc", booking.name
		)
		dims = {i["item_code"]: (i["project"], i["cost_center"]) for i in items}
		self.assertEqual(dims[self.unit_a], (project, cost_center_override))
		self.assertEqual(dims[self.unit_b], (project, cost_center_default))

	def _submit_with_cheque_numbers(self, booking):
		for row in booking.pdc_schedule:
			row.cheque_no = f"CHQ-{row.idx}"
		booking.save(ignore_permissions=True)
		booking.submit()

	def test_on_submit_creates_due_installment_invoices_backdated(self):
		"""A backdated booking (booking_date 6 months in the past, 12-month
		plan) should get Sales Invoices for its already-due installments right
		on submit — posted on each row's own cheque_date, not today — while
		future installments are left for the cron."""
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 12000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
		])
		booking.booking_date = add_months(today(), -6)
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		booking.reload()
		installment_rows = [r for r in booking.pdc_schedule if r.installment_type == "Installment"]
		due_rows = [r for r in installment_rows if getdate(r.cheque_date) <= getdate(today())]
		future_rows = [r for r in installment_rows if getdate(r.cheque_date) > getdate(today())]
		self.assertTrue(due_rows)
		self.assertTrue(future_rows)

		for row in due_rows:
			self.assertTrue(row.sales_invoice)
			posting_date = frappe.db.get_value("Sales Invoice", row.sales_invoice, "posting_date")
			self.assertEqual(getdate(posting_date), getdate(row.cheque_date))

		for row in future_rows:
			self.assertFalse(row.sales_invoice)

	def test_create_missing_invoices_skips_future_rows(self):
		"""create_missing_invoices only fills in due-but-missing rows — it
		must not front-load invoices for installments that aren't due yet."""
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 12000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
		])
		booking.booking_date = add_months(today(), -6)
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		booking.reload()
		installment_rows = [r for r in booking.pdc_schedule if r.installment_type == "Installment"]
		due_row = next(r for r in installment_rows if getdate(r.cheque_date) <= getdate(today()))
		future_row = next(r for r in installment_rows if getdate(r.cheque_date) > getdate(today()))

		# Simulate the due row's invoice having been missed (e.g. on-submit failed).
		frappe.db.set_value("PDC Schedule", due_row.name, "sales_invoice", "")

		from misk_real_estate.real_estate.doctype.property_booking.property_booking import create_missing_invoices
		created = create_missing_invoices(booking.name)
		self.assertEqual(len(created), 1)

		booking.reload()
		updated_due_row = next(r for r in booking.pdc_schedule if r.name == due_row.name)
		updated_future_row = next(r for r in booking.pdc_schedule if r.name == future_row.name)
		self.assertTrue(updated_due_row.sales_invoice)
		self.assertFalse(updated_future_row.sales_invoice)

	def _set_auto_submit_invoices(self, value):
		# .save() (not db_set) so get_cached_doc's cache is invalidated the same
		# way a real settings-form save would — otherwise the "off" reset below
		# doesn't actually take effect for later tests in this same run.
		settings = frappe.get_single("Misk Real Estate Settings")
		settings.auto_submit_invoices = value
		settings.save(ignore_permissions=True)
		if value:
			self.addCleanup(self._set_auto_submit_invoices, 0)

	def test_auto_submit_invoices_setting_controls_advance_invoice_submission(self):
		"""Booking Amount / Down Payment auto-invoices stay Draft by default,
		and submit automatically once "Auto-submit Automatically Generated
		Invoices" is on."""
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000,
			 "booking_amount": 10000, "payment_plan": "Full Payment"},
		])
		booking.insert(ignore_permissions=True)
		booking._create_advance_invoices()
		si_name = frappe.db.get_value(
			"Sales Invoice",
			{"custom_property_booking": booking.name, "custom_payment_purpose": "Booking Amount"},
			"name",
		)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si_name, "docstatus"), 0)

		self._set_auto_submit_invoices(1)
		booking_2 = self._new_booking([
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 10000,
			 "booking_amount": 10000, "payment_plan": "Full Payment"},
		])
		booking_2.insert(ignore_permissions=True)
		booking_2._create_advance_invoices()
		si_name_2 = frappe.db.get_value(
			"Sales Invoice",
			{"custom_property_booking": booking_2.name, "custom_payment_purpose": "Booking Amount"},
			"name",
		)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si_name_2, "docstatus"), 1)

	def test_bulk_create_pdc_entries_creates_for_submitted_and_reports_draft_as_failed(self):
		"""List-view bulk action: PDC Entries get created for a submitted
		booking; a Draft one in the same batch is reported as failed instead
		of aborting the whole run."""
		plan = self._make_single_installment_plan()
		submitted = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		submitted.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(submitted)

		draft = self._new_booking([
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 20000, "payment_plan": "Full Payment"},
		])
		draft.insert(ignore_permissions=True)

		from misk_real_estate.real_estate.doctype.property_booking.property_booking import bulk_create_pdc_entries
		result = bulk_create_pdc_entries([submitted.name, draft.name])

		ok_by_name = {o["name"]: o["created"] for o in result["ok"]}
		self.assertEqual(ok_by_name.get(submitted.name), 1)
		self.assertEqual({f["name"] for f in result["failed"]}, {draft.name})

	def test_submitted_pdc_schedule_directly_editable_before_pdc_entries(self):
		"""No PDC Entry and no Sales Agreement yet — cheque_no/cheque_date/amount
		stay directly editable via a normal doc.save() after submit."""
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		row = booking.pdc_schedule[0]
		row.cheque_no = "CHQ-EDITED"
		row.cheque_date = add_months(today(), 2)
		booking.save(ignore_permissions=True)

		booking.reload()
		self.assertEqual(booking.pdc_schedule[0].cheque_no, "CHQ-EDITED")
		self.assertEqual(getdate(booking.pdc_schedule[0].cheque_date), getdate(add_months(today(), 2)))

	def test_pdc_schedule_locked_once_pdc_entry_created(self):
		"""Once any row has a PDC Entry, editing ANY row is blocked."""
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		from misk_real_estate.real_estate.doctype.property_booking.property_booking import create_pdc_entries
		create_pdc_entries(booking.name)

		booking.reload()
		booking.pdc_schedule[0].cheque_no = "SHOULD-NOT-SAVE"
		self.assertRaises(frappe.ValidationError, booking.save, ignore_permissions=True)

	def test_pdc_schedule_locked_once_sales_agreement_exists(self):
		"""A generated Sales Agreement locks the schedule even without a PDC Entry."""
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		# Bypass Sales Agreement's own eligibility re-check (requires Booking
		# Amount/Down Payment settled and every row already PDC-entered) — this
		# test isolates the booking-side lock, not full contract eligibility.
		agreement = frappe.get_doc({"doctype": "Sales Agreement", "property_booking": booking.name})
		agreement.flags.ignore_validate = True
		agreement.insert(ignore_permissions=True)

		booking.reload()
		booking.pdc_schedule[0].cheque_no = "SHOULD-NOT-SAVE"
		self.assertRaises(frappe.ValidationError, booking.save, ignore_permissions=True)

	def test_cancel_blocked_once_sales_agreement_submitted(self):
		"""Submitting a Sales Agreement is what 'generates' the contract — once
		that's happened, cancelling the booking must be blocked (it would
		release the unit and PDC entries out from under an issued contract).

		Bypasses the eligibility re-check itself (via a mock, not
		ignore_validate — that flag also skips before_submit/before_cancel,
		which is exactly what sets `status` here; using it would make this
		test pass even if that logic were broken)."""
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		from unittest.mock import patch
		with patch(
			"misk_real_estate.real_estate.doctype.property_booking.property_booking.check_contract_eligibility",
			return_value=[],
		):
			agreement = frappe.get_doc({"doctype": "Sales Agreement", "property_booking": booking.name})
			agreement.insert(ignore_permissions=True)
			agreement.submit()

		self.assertEqual(agreement.status, "Generated")
		self.assertRaises(frappe.ValidationError, booking.cancel)

		agreement.cancel()
		self.assertEqual(frappe.db.get_value("Sales Agreement", agreement.name, "status"), "Cancelled")

	def test_cancel_allowed_when_sales_agreement_still_draft(self):
		"""A Draft (not yet submitted/generated) Sales Agreement doesn't block
		cancelling the booking — only an actually-generated contract does."""
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		agreement = frappe.get_doc({"doctype": "Sales Agreement", "property_booking": booking.name})
		agreement.flags.ignore_validate = True
		agreement.insert(ignore_permissions=True)
		self.assertEqual(agreement.docstatus, 0)

		booking.cancel()
		self.assertEqual(booking.docstatus, 2)

	def test_pdc_schedule_locked_once_row_invoiced(self):
		"""A row that already has a Sales Invoice locks the whole table, even
		with no PDC Entry and no Sales Agreement yet."""
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		si = frappe.get_doc({
			"doctype": "Sales Invoice", "customer": self.customer, "company": self.company,
			"items": [{"item_code": self.unit_a, "qty": 1, "rate": 5000}],
		}).insert(ignore_permissions=True)
		frappe.db.set_value("PDC Schedule", booking.pdc_schedule[0].name, "sales_invoice", si.name)

		booking.reload()
		booking.pdc_schedule[0].cheque_no = "SHOULD-NOT-SAVE"
		self.assertRaises(frappe.ValidationError, booking.save, ignore_permissions=True)

	def test_balance_check_enforced_on_post_submit_edit(self):
		"""Editing a row's Amount so the table no longer matches the expected
		total is rejected on save, post-submit."""
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		booking.insert(ignore_permissions=True)
		self._submit_with_cheque_numbers(booking)

		booking.pdc_schedule[0].amount = flt(booking.pdc_schedule[0].amount) + 500
		self.assertRaises(frappe.ValidationError, booking.save, ignore_permissions=True)

	def test_editing_combined_row_amount_rescales_unit_breakdown(self):
		"""Editing a combined row's Amount keeps unit_breakdown proportional to
		the new total instead of going stale."""
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 12000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 24000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
		])
		booking.insert(ignore_permissions=True)

		combined_row = next(r for r in booking.pdc_schedule if r.installment_type == "Installment")
		self.assertEqual(flt(combined_row.amount), 1500)  # 500 (unit A) + 1000 (unit B)
		combined_row.amount = 3000  # double it
		booking.save(ignore_permissions=True)

		booking.reload()
		updated_row = next(r for r in booking.pdc_schedule if r.name == combined_row.name)
		breakdown = {c["unit"]: flt(c["amount"]) for c in frappe.parse_json(updated_row.unit_breakdown)}
		self.assertEqual(breakdown, {self.unit_a: 1000, self.unit_b: 2000})
		self.assertEqual(flt(updated_row.amount), 3000)

	def test_editing_unit_on_single_row_recomputes_net_tax_keeps_amount(self):
		"""Reassigning a single-unit row's Unit to another unit on the same
		booking keeps Amount (the cheque's face value) unchanged and
		recomputes Net/Tax from the new unit's own rate."""
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 20000, "payment_plan": "Full Payment"},
		])
		booking.insert(ignore_permissions=True)

		row = booking.pdc_schedule[0]
		self.assertEqual(row.unit, self.unit_a)
		original_amount = flt(row.amount)
		row.unit = self.unit_b
		booking.save(ignore_permissions=True)

		booking.reload()
		updated_row = next(r for r in booking.pdc_schedule if r.name == row.name)
		self.assertEqual(updated_row.unit, self.unit_b)
		self.assertEqual(flt(updated_row.amount), original_amount)
		self.assertEqual(flt(updated_row.net_amount) + flt(updated_row.tax_amount), flt(updated_row.amount))

	def test_editing_unit_rejected_for_combined_row(self):
		"""A combined row has no single unit to reassign — setting Unit
		directly on it is rejected."""
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 12000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
			{"building": "Consumable", "unit": self.unit_b, "unit_price": 24000,
			 "down_payment_percentage": 50, "payment_plan": "Installment 12M"},
		])
		booking.insert(ignore_permissions=True)

		combined_row = next(r for r in booking.pdc_schedule if r.installment_type == "Installment")
		combined_row.unit = self.unit_a
		self.assertRaises(frappe.ValidationError, booking.save, ignore_permissions=True)

	def test_editing_unit_rejected_for_unit_outside_booking(self):
		"""Reassigning a row to a unit that isn't part of this booking is rejected."""
		outside_unit = _make_unit("TEST-UNIT-OUTSIDE")
		plan = self._make_single_installment_plan()
		booking = self._new_booking([
			{"building": "Consumable", "unit": self.unit_a, "unit_price": 10000, "payment_plan": plan},
		])
		booking.insert(ignore_permissions=True)

		booking.pdc_schedule[0].unit = outside_unit
		self.assertRaises(frappe.ValidationError, booking.save, ignore_permissions=True)
