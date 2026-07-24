# Copyright (c) 2026, Enfono Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase, change_settings
from frappe.utils import flt, today


class TestExpenseEntry(FrappeTestCase):
	def setUp(self):
		self.company = (
			frappe.db.exists("Company", "misk") or frappe.db.get_value("Company", {}, "name")
		)
		self.payable_account = frappe.db.get_value(
			"Account", {"company": self.company, "root_type": "Liability", "is_group": 0}, "name"
		)
		self.expense_account = frappe.db.get_value(
			"Account", {"company": self.company, "root_type": "Expense", "is_group": 0}, "name"
		)
		if not (self.company and self.payable_account and self.expense_account):
			self.skipTest("Requires an existing Company with a leaf Liability and Expense account.")

	def _new_entry(self, amounts):
		doc = frappe.new_doc("Expense Entry")
		doc.naming_series = "EXP-.YYYY.-"
		doc.company = self.company
		doc.posting_date = today()
		doc.payable_account = self.payable_account
		for amount in amounts:
			doc.append("expenses", {
				"expense_account": self.expense_account,
				"description": "Test expense",
				"amount": amount,
			})
		return doc

	def test_submit_creates_and_submits_linked_journal_entry(self):
		"""The link points from this document at the Journal Entry (not the
		reverse) so Frappe's own back-link check protects the auto-created
		Journal Entry from being cancelled/deleted directly — only this
		document's own cancel/delete (which cascades) can take it down."""
		doc = self._new_entry([100, 250.5])
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.total_amount, 350.5)

		doc.submit()
		self.assertTrue(doc.journal_entry)

		je = frappe.get_doc("Journal Entry", doc.journal_entry)
		self.assertEqual(je.docstatus, 1)

		debit_rows = [r for r in je.accounts if r.account == self.expense_account]
		credit_row = next(r for r in je.accounts if r.account == self.payable_account)
		self.assertEqual(sorted(flt(r.debit) for r in debit_rows), [100, 250.5])
		self.assertEqual(flt(credit_row.credit), 350.5)

		doc.cancel()

	def test_cancel_cancels_linked_journal_entry(self):
		doc = self._new_entry([75])
		doc.insert(ignore_permissions=True)
		doc.submit()
		je_name = doc.journal_entry

		doc.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", je_name, "docstatus"), 2)

	def test_header_dimensions_default_rows_but_row_override_wins(self):
		cost_centers = frappe.get_all(
			"Cost Center", filters={"company": self.company, "is_group": 0}, pluck="name", limit=2
		)
		if len(cost_centers) < 2:
			self.skipTest("Requires two existing leaf Cost Centers.")
		header_cc, row_cc = cost_centers

		doc = self._new_entry([100, 200])
		doc.cost_center = header_cc
		doc.expenses[1].cost_center = row_cc  # explicit override
		doc.insert(ignore_permissions=True)
		doc.submit()

		je = frappe.get_doc("Journal Entry", doc.journal_entry)
		debit_rows = {flt(r.debit): r.cost_center for r in je.accounts if r.account == self.expense_account}
		credit_row = next(r for r in je.accounts if r.account == self.payable_account)

		# row with no cost_center of its own inherits the header's
		self.assertEqual(debit_rows[100], header_cc)
		# row with its own cost_center keeps it, not the header's
		self.assertEqual(debit_rows[200], row_cc)
		# the payable/credit line always carries the header cost_center
		self.assertEqual(credit_row.cost_center, header_cc)

		doc.cancel()

	def test_at_least_one_expense_required(self):
		doc = self._new_entry([])
		self.assertRaises(frappe.ValidationError, doc.insert, ignore_permissions=True)

	def test_cancelling_journal_entry_directly_is_blocked(self):
		"""The auto-created Journal Entry must only go down via this
		document's own cancel (which cascades) — not be cancellable on its
		own, since that would leave this document out of sync with the
		ledger it thinks it posted."""
		doc = self._new_entry([60])
		doc.insert(ignore_permissions=True)
		doc.submit()

		je = frappe.get_doc("Journal Entry", doc.journal_entry)
		self.assertRaises(frappe.LinkExistsError, je.cancel)

		doc.cancel()

	@change_settings("Accounts Settings", {"delete_linked_ledger_entries": 0})
	def test_deleting_expense_entry_leaves_journal_entry_cancelled_when_site_disallows_it(self):
		"""Nothing links *to* Expense Entry (only Expense Entry links to the
		Journal Entry), so deleting it after cancel is never blocked by
		Frappe's back-link check regardless of the Journal Entry's own
		docstatus. With Accounts Settings.delete_linked_ledger_entries off,
		Journal Entry.on_trash (AccountsController) refuses to delete a
		voucher that still has GL Entries — the permanent accounting audit
		trail — so it's intentionally left behind, cancelled, rather than
		blocking this document's own deletion."""
		doc = self._new_entry([80])
		doc.insert(ignore_permissions=True)
		doc.submit()
		je_name = doc.journal_entry
		doc.cancel()

		frappe.delete_doc("Expense Entry", doc.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Expense Entry", doc.name))
		self.assertEqual(frappe.db.get_value("Journal Entry", je_name, "docstatus"), 2)

	@change_settings("Accounts Settings", {"delete_linked_ledger_entries": 1})
	def test_deleting_expense_entry_also_deletes_journal_entry_when_site_allows_it(self):
		"""With delete_linked_ledger_entries on, Journal Entry.on_trash deletes
		its own GL Entries first, so the cascade delete here goes all the way
		through instead of being caught and left cancelled."""
		doc = self._new_entry([80])
		doc.insert(ignore_permissions=True)
		doc.submit()
		je_name = doc.journal_entry
		doc.cancel()

		frappe.delete_doc("Expense Entry", doc.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Expense Entry", doc.name))
		self.assertFalse(frappe.db.exists("Journal Entry", je_name))

	def test_amend_after_cancel_creates_a_separate_new_journal_entry(self):
		doc = self._new_entry([50])
		doc.insert(ignore_permissions=True)
		doc.submit()
		original_je = doc.journal_entry
		doc.cancel()

		# ignore_no_copy=False: Frappe's own client-side Amend action actually
		# copies no_copy fields too (confirmed in create_new.js) — a caller
		# writing a correct server-side amend needs to opt into clearing them
		# explicitly, same as the client-side fix in expense_entry.js does.
		amended = frappe.copy_doc(doc, ignore_no_copy=False)
		amended.amended_from = doc.name
		amended.docstatus = 0
		amended.insert(ignore_permissions=True)
		self.assertFalse(amended.journal_entry)

		amended.submit()
		self.assertNotEqual(amended.journal_entry, original_je)

		amended.cancel()
