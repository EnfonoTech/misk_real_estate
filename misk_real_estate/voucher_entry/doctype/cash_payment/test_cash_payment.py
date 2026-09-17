# Copyright (c) 2026, Enfono Technologies and Contributors
# See license.txt
#
# Covers all four voucher screens — they share one controller
# (voucher_entry/voucher_base.py), so they are tested as one matrix rather
# than with four near-identical test files.

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

# doctype, series, control fieldname, account_type, control side, JE voucher_type, direction
MATRIX = [
    ("Cash Payment", "CPV-.YYYY.-", "cash_account", "Cash", "credit", "Cash Entry", "Payment"),
    ("Bank Payment", "BPV-.YYYY.-", "bank_account", "Bank", "credit", "Bank Entry", "Payment"),
    ("Cash Receipt", "CRV-.YYYY.-", "cash_account", "Cash", "debit", "Cash Entry", "Receipt"),
    ("Bank Receipt", "BRV-.YYYY.-", "bank_account", "Bank", "debit", "Bank Entry", "Receipt"),
]


class TestVoucherEntry(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.exists("Company", "misk") or frappe.db.get_value("Company", {}, "name")
		self.accounts = {}
		for account_type in ("Cash", "Bank"):
			self.accounts[account_type] = frappe.db.get_value(
				"Account", {"company": self.company, "account_type": account_type, "is_group": 0}, "name"
			)
		self.contra = frappe.db.get_value(
			"Account", {"company": self.company, "root_type": "Expense", "is_group": 0}, "name"
		)
		if not (self.company and self.contra and all(self.accounts.values())):
			self.skipTest("Requires a Company with leaf Cash, Bank and Expense accounts.")

	def _new(self, doctype, series, control_field, account_type, amounts):
		doc = frappe.new_doc(doctype)
		doc.naming_series = series
		doc.company = self.company
		doc.posting_date = today()
		doc.set(control_field, self.accounts[account_type])
		if doc.meta.has_field("reference_no"):
			# "Bank Entry" JEs require these in ERPNext's own validate_cheque_info
			doc.reference_no = "CHQ-0001"
			doc.reference_date = today()
		for amount in amounts:
			doc.append("lines", {"account": self.contra, "description": "Test", "amount": amount})
		return doc

	def test_submit_posts_a_balanced_journal_entry_on_the_right_sides(self):
		"""The control account takes CONTROL_SIDE, every line takes the other."""
		for doctype, series, field, account_type, side, je_type, direction in MATRIX:
			with self.subTest(doctype=doctype):
				doc = self._new(doctype, series, field, account_type, [100, 250.5])
				doc.insert(ignore_permissions=True)
				self.assertEqual(doc.total_amount, 350.5)

				doc.submit()
				self.assertTrue(doc.journal_entry)

				je = frappe.get_doc("Journal Entry", doc.journal_entry)
				self.assertEqual(je.docstatus, 1)
				self.assertEqual(je.voucher_type, je_type)
				self.assertEqual(je.custom_entry_direction, direction)
				self.assertEqual(flt(je.total_debit), flt(je.total_credit))
				self.assertEqual(flt(je.total_debit), 350.5)

				control = next(r for r in je.accounts if r.account == self.accounts[account_type])
				self.assertEqual(flt(control.get(side)), 350.5)
				other = "debit" if side == "credit" else "credit"
				self.assertFalse(flt(control.get(other)))

				lines = [r for r in je.accounts if r.account == self.contra]
				self.assertEqual(sorted(flt(r.get(other)) for r in lines), [100, 250.5])

				doc.cancel()

	def test_cancel_cascades_to_the_journal_entry(self):
		doc = self._new("Cash Payment", "CPV-.YYYY.-", "cash_account", "Cash", [75])
		doc.insert(ignore_permissions=True)
		doc.submit()
		je_name = doc.journal_entry
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", je_name, "docstatus"), 2)

	def test_bank_vouchers_require_reference_details(self):
		"""Caught here as a plain mandatory field rather than surfacing as
		ERPNext's confusing "Reference No & Reference Date is required for
		Bank Entry" at submit time."""
		for doctype, series in (("Bank Payment", "BPV-.YYYY.-"), ("Bank Receipt", "BRV-.YYYY.-")):
			with self.subTest(doctype=doctype):
				doc = self._new(doctype, series, "bank_account", "Bank", [50])
				doc.reference_no = None
				doc.reference_date = None
				self.assertRaises(frappe.MandatoryError, doc.insert)

	def test_header_account_cannot_also_be_a_line(self):
		doc = self._new("Cash Payment", "CPV-.YYYY.-", "cash_account", "Cash", [])
		doc.append("lines", {"account": self.accounts["Cash"], "amount": 10})
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_empty_voucher_is_rejected(self):
		doc = self._new("Cash Receipt", "CRV-.YYYY.-", "cash_account", "Cash", [])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_row_dimensions_are_taken_verbatim_not_defaulted_from_the_header(self):
		"""A row deliberately left blank must POST blank — the header must not
		silently refill it at submit time. The header's values reach rows only
		through the client-side fill-down, where they are visible; there is no
		second, invisible `row.x or self.x` fallback in the controller.

		Cost Center is the exception only in that a blank one then falls to
		ERPNext's own company default (journal_entry_account.cost_center is
		`default: ":Company"`), which is what keeps P&L lines postable at all.
		What matters here is that it is NOT the header's value."""
		header_cc = frappe.db.get_value(
			"Cost Center", {"company": self.company, "is_group": 0}, "name"
		)
		company_default_cc = frappe.get_cached_value("Company", self.company, "cost_center")
		project = frappe.db.get_value("Project", {}, "name")
		if not (project and header_cc and company_default_cc and header_cc != company_default_cc):
			self.skipTest("Needs a Project and a leaf Cost Center that is not the company default.")

		doc = self._new("Cash Payment", "CPV-.YYYY.-", "cash_account", "Cash", [])
		doc.cost_center = header_cc
		doc.project = project
		# row 1 carries its own dimensions, row 2 is deliberately left blank
		doc.append("lines", {"account": self.contra, "amount": 10,
		                     "cost_center": company_default_cc, "project": project})
		doc.append("lines", {"account": self.contra, "amount": 20})
		doc.insert(ignore_permissions=True)
		doc.submit()

		je = frappe.get_doc("Journal Entry", doc.journal_entry)
		by_amount = {}
		for row in je.accounts:
			by_amount[flt(row.debit) or flt(row.credit)] = row

		self.assertEqual(by_amount[10].project, project)
		self.assertEqual(by_amount[10].cost_center, company_default_cc)

		# the blank row: project stays blank, cost centre is the COMPANY
		# default rather than the header's
		self.assertFalse(by_amount[20].project)
		self.assertEqual(by_amount[20].cost_center, company_default_cc)
		self.assertNotEqual(by_amount[20].cost_center, header_cc)

		# the control account has no row of its own, so it legitimately keeps
		# the header's dimensions
		control = by_amount[30]
		self.assertEqual(control.account, self.accounts["Cash"])
		self.assertEqual(control.cost_center, header_cc)
		self.assertEqual(control.project, project)

		doc.cancel()

	def test_amend_works_without_the_client_script(self):
		"""Amending from the form works because voucher_common.js clears
		journal_entry in the browser. Every other path — the API, data import,
		bulk tools — has no client script, and journal_entry (no_copy, but
		Frappe's Amend does not honour no_copy) still points at the old, now
		cancelled Journal Entry. Frappe runs _validate_links() before
		validate(), so only the _validate_links() override can clear it in
		time; without that this raises CancelledLinkError.

		The amendment gets a FRESH Journal Entry rather than an amendment of
		the old one. That is intended: the cancelled JE stays as the audit
		trail, each voucher version points at its own JE, and it matches how
		ERPNext's own JE-posting documents behave."""
		doc = self._new("Cash Payment", "CPV-.YYYY.-", "cash_account", "Cash", [100])
		doc.insert(ignore_permissions=True)
		doc.submit()
		original, original_je = doc.name, doc.journal_entry
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", original_je, "docstatus"), 2)

		# straight server-side amend — deliberately NOT clearing journal_entry,
		# exactly as a non-browser caller would leave it
		amended = frappe.copy_doc(doc)
		amended.amended_from = original
		amended.docstatus = 0
		self.assertEqual(amended.journal_entry, original_je)  # inherited by Amend
		amended.insert(ignore_permissions=True)               # must not raise
		self.assertFalse(amended.journal_entry)

		amended.submit()
		self.assertTrue(amended.journal_entry)
		self.assertNotEqual(amended.journal_entry, original_je)

		# the old posting is cancelled, the new one is live, each owned by one voucher
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": original_je, "is_cancelled": 0}), 0)
		self.assertTrue(frappe.db.count("GL Entry", {"voucher_no": amended.journal_entry, "is_cancelled": 0}))
		self.assertEqual(
			frappe.get_all("Cash Payment", filters={"journal_entry": amended.journal_entry}, pluck="name"),
			[amended.name],
		)
		amended.cancel()

	def test_a_plain_journal_entry_is_left_completely_alone(self):
		"""Regression guard. These vouchers stamp custom_entry_direction so a
		Journal Entry can be read as pay-vs-receive, and naming rules will later
		key off it. A hand-written Journal Entry sets nothing, so it must keep
		ERPNext's own ACC-JV- naming and an empty direction — no rule can ever
		match it."""
		je = frappe.new_doc("Journal Entry")
		je.company = self.company
		je.posting_date = today()
		je.voucher_type = "Journal Entry"
		je.append("accounts", {"account": self.contra, "debit": 10, "debit_in_account_currency": 10})
		je.append("accounts", {"account": self.accounts["Cash"], "credit": 10, "credit_in_account_currency": 10})
		je.insert(ignore_permissions=True)

		self.assertTrue(je.name.startswith("ACC-JV-"))
		self.assertFalse(je.custom_entry_direction)
		je.delete()
