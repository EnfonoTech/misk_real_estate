# apps/misk_real_estate/misk_real_estate/voucher_entry/voucher_base.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class VoucherBase(Document):
    """Shared controller for the cash/bank payment & receipt vouchers.

    Every one of them is the same shape as Expense Entry (see
    expense_entry/doctype/expense_entry/expense_entry.py, which this is
    modelled on): one header "control" account on one side, N child rows on
    the other, and submitting builds + submits the backing Journal Entry in
    the same step. Only four things differ between the screens, so those are
    the four class attributes below and nothing else is duplicated.

    Expense Entry itself deliberately does NOT inherit from this — it is
    live, and rewiring its controller would put existing data at risk for no
    functional gain. The two are kept in step by hand; if a fix lands here
    that also applies there, port it explicitly.
    """

    #: Fieldname of the header account paid from / received into.
    CONTROL_FIELD: str = ""
    #: Side the control account takes. Rows always take the other one.
    CONTROL_SIDE: str = ""  # "credit" (payment) | "debit" (receipt)
    #: ERPNext Journal Entry voucher_type for the entry this creates.
    #: "Bank Entry" additionally makes cheque_no/cheque_date mandatory in
    #: ERPNext's own JournalEntry.validate_cheque_info — which is why the
    #: bank doctypes carry reqd reference_no/reference_date fields.
    JE_VOUCHER_TYPE: str = "Journal Entry"
    #: Stamped onto the Journal Entry's custom_entry_direction, so a JE can
    #: be read as pay-vs-receive without opening the voucher. Combined with
    #: the JE's own native voucher_type (Cash Entry / Bank Entry) it gives
    #: the full picture.
    DIRECTION: str = ""  # "Payment" | "Receipt"

    # ── helpers ──────────────────────────────────────────────────────────

    @property
    def control_account(self):
        return self.get(self.CONTROL_FIELD)

    @property
    def row_side(self):
        return "debit" if self.CONTROL_SIDE == "credit" else "credit"

    # ── validation ───────────────────────────────────────────────────────

    def _validate_links(self):
        """Clear a stale journal_entry before Frappe's own link check sees it.

        Frappe runs _validate_links() ahead of validate()/before_insert on
        BOTH insert and save, so this is the only server-side hook early
        enough: anything later dies on "Cannot link cancelled document"
        before it ever runs.

        Why it needs clearing: journal_entry is no_copy, but Frappe's Amend
        action does not honour no_copy (only a plain Duplicate does), so an
        amended draft still points at the old, now-cancelled Journal Entry.
        The browser clears it in public/js/voucher_common.js, which is why
        amending from the form works; this covers every other path — the API,
        data import, bulk tools and scripts.
        """
        self._clear_stale_journal_entry()
        return super()._validate_links()

    def validate(self):
        self._calculate_total()
        self._validate_lines()

    def _clear_stale_journal_entry(self):
        """journal_entry is only ever assigned in before_submit, by which
        point docstatus is already 1 — so a draft holding a value can only
        have inherited it from an amend, and it is never legitimate."""
        if self.docstatus == 0 and self.journal_entry:
            self.journal_entry = None

    def _calculate_total(self):
        self.total_amount = flt(sum(flt(row.amount) for row in self.lines), 3)

    def _validate_lines(self):
        if not self.lines:
            frappe.throw(_("At least one row is required."))
        for row in self.lines:
            if not row.amount or flt(row.amount) <= 0:
                frappe.throw(
                    _("Row {0}: Amount is required and must be greater than zero.").format(row.idx)
                )
            if row.account == self.control_account:
                frappe.throw(
                    _("Row {0}: {1} is already the header account — it cannot also be a line.").format(
                        row.idx, frappe.bold(row.account)
                    )
                )

    # ── posting ──────────────────────────────────────────────────────────

    def before_submit(self):
        """Submitting IS posting — builds and submits the backing Journal
        Entry in the same step. The link is one-directional: this document
        points at the Journal Entry (not the reverse) so that Frappe's own
        back-link check protects the auto-created Journal Entry from being
        cancelled or deleted directly — only cancelling/deleting this
        document (which cascades via on_cancel/on_trash below) can take it
        down.

        Set here and not in on_submit: Frappe writes the docstatus=1 row
        before on_submit runs, so a plain self.journal_entry assignment there
        would never persist."""
        je = self._build_journal_entry()
        je.insert(ignore_permissions=True)
        je.submit()
        self.journal_entry = je.name

    def _build_journal_entry(self):
        # Each row posts its OWN cost_center/project, verbatim — a row left
        # blank stays blank. The header's values reach rows only through the
        # client-side fill-down (public/js/voucher_common.js), which writes
        # them into blank rows where they are visible and overridable.
        #
        # There is deliberately no `row.x or self.x` fallback here any more:
        # it made it impossible to clear one row while the header was set,
        # because it silently put the header value back at submit time.
        #
        # A row left with no cost_center falls through to ERPNext's own
        # company default (journal_entry_account.cost_center is
        # `default: ":Company"`), which is what keeps Profit and Loss lines
        # postable at all — GL Entry's pl_must_have_cost_center throws
        # without one. Project has no such default, so blank posts blank.
        row_side = self.row_side
        accounts = []
        for row in self.lines:
            accounts.append({
                "account": row.account,
                row_side: flt(row.amount),
                f"{row_side}_in_account_currency": flt(row.amount),
                "cost_center": row.cost_center,
                "project": row.project,
                "user_remark": row.description,
            })
        # The control account has no row of its own, so it is the one line
        # that legitimately takes the header's dimensions.
        accounts.append({
            "account": self.control_account,
            self.CONTROL_SIDE: flt(self.total_amount),
            f"{self.CONTROL_SIDE}_in_account_currency": flt(self.total_amount),
            "cost_center": self.cost_center,
            "project": self.project,
        })

        return frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": self.JE_VOUCHER_TYPE,
            "custom_entry_direction": self.DIRECTION,
            "company": self.company,
            "posting_date": self.posting_date,
            "user_remark": self.remarks or _("{0} {1}").format(_(self.doctype), self.name),
            # Cash vouchers have no instrument fields at all, so these read
            # back as None there and are simply not set on the Journal Entry.
            "cheque_no": self.get("reference_no"),
            "cheque_date": self.get("reference_date"),
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
