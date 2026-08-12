import frappe
from frappe.utils import getdate

# Doctypes it's never sensible to run this for — Frappe's own naming
# machinery reaches these before a normal document would, and querying our
# own rule doctype from inside its own autoname would recurse.
IGNORE_DOCTYPES = frozenset({"Posting Date Naming Rule", "Posting Date Naming Rule Condition"})


def set_name_from_rule(doc, method=None):
    """autoname hook, registered for doc_events["*"] in hooks.py — runs for
    every doctype's insert, so adding Posting Date Naming Rules for a new
    doctype is pure UI configuration, no extra hook wiring per doctype.

    Only touches doc.name if a matching, enabled Posting Date Naming Rule
    exists for doc.doctype; otherwise it's a no-op and that doctype's normal
    naming (naming_series, field:, hash, core Document Naming Rule, ...)
    proceeds untouched. Also backs off immediately if doc.name is already
    set, so it can never clobber a name a controller's own autoname() (or
    amendment/import logic) already assigned earlier in the same call."""
    if doc.name or doc.doctype in IGNORE_DOCTYPES:
        return

    rule_names = frappe.cache_manager.get_doctype_map(
        "Posting Date Naming Rule",
        doc.doctype,
        filters={"document_type": doc.doctype, "disabled": 0},
        order_by="priority desc",
    )
    for r in rule_names:
        rule = frappe.get_cached_doc("Posting Date Naming Rule", r.name)
        if rule.apply(doc):
            return


def parse_naming_series_variable(doc, variable):
    """.PYYYY./.PYY./.PMM. naming-series tokens: year (4- or 2-digit) / month
    of the *document's* own date field, never "today" (Frappe's built-in
    .YYYY./.YY./.MM. always mean today — frappe.model.naming.parse_naming_series).
    Which field to read is set per-rule via Posting Date Naming Rule's Date
    Field (stashed onto doc.flags by PostingDateNamingRule.apply() right
    before this runs); default is posting_date, falling back to
    transaction_date, which covers the common ERPNext transaction doctypes
    with no per-rule config needed.

    Registered via hooks.py -> naming_series_variables. Same extension point
    ERPNext itself uses for the .FY. (fiscal year) token."""
    date_field = doc.flags.get("posting_date_naming_date_field") or "posting_date"
    date = doc.get(date_field) or doc.get("posting_date") or doc.get("transaction_date")
    date = getdate(date)
    if variable == "PYYYY":
        return date.strftime("%Y")
    if variable == "PYY":
        return date.strftime("%y")
    if variable == "PMM":
        return date.strftime("%m")
