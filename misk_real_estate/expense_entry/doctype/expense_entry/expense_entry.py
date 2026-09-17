# apps/misk_real_estate/misk_real_estate/expense_entry/doctype/expense_entry/expense_entry.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ExpenseEntry(Document):
    def _validate_links(self):
        """Clear a stale journal_entry before Frappe's own link check sees it.

        Frappe runs _validate_links() ahead of validate()/before_insert on
        BOTH insert and save, so this is the only server-side hook early
        enough: anything later dies on "Cannot link cancelled document"
        before it ever runs.

        Why it needs clearing: journal_entry is no_copy, but Frappe's Amend
        action does not honour no_copy (confirmed in create_new.js: no_copy
        is honoured for a plain Duplicate, not an amend), so an amended draft
        still points at the old, now-cancelled Journal Entry. The browser
        clears it in expense_entry.js, which is why amending from the form
        works; this covers every other path — the API, data import, bulk
        tools and scripts. Kept in step with voucher_entry/voucher_base.py.
        """
        self._clear_stale_journal_entry()
        return super()._validate_links()

    def validate(self):
        self._calculate_total()
        self._validate_expenses()

    def _clear_stale_journal_entry(self):
        """journal_entry is only ever assigned in before_submit, by which
        point docstatus is already 1 — so a draft holding a value can only
        have inherited it from an amend, and it is never legitimate."""
        if self.docstatus == 0 and self.journal_entry:
            self.journal_entry = None

    def _calculate_total(self):
        self.total_amount = flt(sum(flt(row.amount) for row in self.expenses), 3)

    def _validate_expenses(self):
        if not self.expenses:
            frappe.throw(_("At least one expense row is required."))
        for row in self.expenses:
            if not row.amount or flt(row.amount) <= 0:
                frappe.throw(_("Row {0}: Amount is required and must be greater than zero.").format(row.idx))

    def before_submit(self):
        """Submitting IS posting — builds and submits the backing Journal
        Entry in the same step. The link is one-directional the other way
        round from an earlier version of this doctype: this document points
        at the Journal Entry (not the reverse) so that Frappe's own back-link
        check protects the auto-created Journal Entry from being cancelled
        or deleted directly — only cancelling/deleting this document (which
        cascades via on_cancel/on_trash below) can take it down.

        Set here (not on_submit): Frappe writes the docstatus=1 row before
        on_submit runs, so a plain self.journal_entry assignment there would
        never persist (confirmed the hard way with Sales Agreement's status
        field earlier this session)."""
        je = self._build_journal_entry()
        je.insert(ignore_permissions=True)
        je.submit()
        self.journal_entry = je.name

    def _build_journal_entry(self):
        # Each row posts its OWN cost_center/project, verbatim — a row left
        # blank stays blank. The header's values reach rows only through the
        # client-side fill-down (expense_entry.js), which writes them into
        # blank rows where they are visible and overridable.
        #
        # There is deliberately no `row.x or self.x` fallback here any more:
        # it made it impossible to clear one row while the header was set,
        # because it silently put the header value back at submit time. Kept
        # in step with voucher_entry/voucher_base.py, which is the same shape.
        #
        # A row left with no cost_center falls through to ERPNext's own
        # company default (journal_entry_account.cost_center is
        # `default: ":Company"`), which is what keeps Profit and Loss lines
        # postable at all — GL Entry's pl_must_have_cost_center throws
        # without one. Project has no such default, so blank posts blank.
        accounts = []
        for row in self.expenses:
            accounts.append({
                "account": row.expense_account,
                "debit_in_account_currency": flt(row.amount),
                "debit": flt(row.amount),
                "cost_center": row.cost_center,
                "project": row.project,
                "user_remark": row.description,
            })
        # The payable account has no row of its own, so it is the one line
        # that legitimately takes the header's dimensions.
        accounts.append({
            "account": self.payable_account,
            "credit_in_account_currency": flt(self.total_amount),
            "credit": flt(self.total_amount),
            "cost_center": self.cost_center,
            "project": self.project,
        })

        return frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": self.company,
            "posting_date": self.posting_date,
            "user_remark": self.remarks or _("Expense Entry {0}").format(self.name),
            "accounts": accounts,
        })

    def on_cancel(self):
        if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
            frappe.get_doc("Journal Entry", self.journal_entry).cancel()

    def on_trash(self):
        if not (self.journal_entry and frappe.db.exists("Journal Entry", self.journal_entry)):
            return

        journal_entry = self.journal_entry
        # Clear the back-reference first: on_trash runs before this row is
        # actually removed from the DB and before Frappe's own
        # check_if_doc_is_linked runs for the Journal Entry, so this row would
        # otherwise still count as a live reference blocking its delete.
        frappe.db.set_value(self.doctype, self.name, "journal_entry", None)
        try:
            frappe.delete_doc("Journal Entry", journal_entry, ignore_permissions=True)
        except frappe.LinkExistsError:
            # Whether this succeeds depends on Accounts Settings'
            # "delete_linked_ledger_entries": off (ERPNext's default), GL
            # Entries are the permanent audit trail and Journal Entry.on_trash
            # (AccountsController) refuses to delete a voucher that still has
            # them, same as for every other voucher type. Leave it cancelled
            # rather than blocking this document's own deletion.
            pass

