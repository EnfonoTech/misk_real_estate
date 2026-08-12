import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import parse_naming_series
from frappe.utils.data import evaluate_filters


class PostingDateNamingRule(Document):
    """Same idea as core's Document Naming Rule (document_type + conditions +
    prefix, editable from the UI, no code changes needed per doctype), but:

    1. Its .PYYYY./.PMM. prefix tokens resolve from Date Field (default
       posting_date, falling back to transaction_date) instead of today —
       see .PYYYY./.PMM. registration in real_estate/custom/posting_date_naming.py.
    2. The running number resets automatically per resolved prefix (e.g. a
       new counter for each month), the same way classic naming series do,
       instead of core Document Naming Rule's single ever-incrementing
       counter field that never resets.

    This is a separate doctype rather than reusing core's Document Naming
    Rule so "Disabled" keeps its normal, single meaning — no double-duty
    checkbox, no collision with core conventions (e.g. frappe.desk.search
    auto-excludes disabled=1 rows from Link-field lookups on any doctype
    with a `disabled` field)."""

    def validate(self):
        self.validate_fields_in_conditions()

    def validate_fields_in_conditions(self):
        if not self.has_value_changed("document_type") and not self.has_value_changed("conditions"):
            return
        docfields = {df.fieldname for df in frappe.get_meta(self.document_type).fields}
        for condition in self.conditions:
            if condition.field not in docfields:
                frappe.throw(
                    _("{0} is not a field of Document Type {1}").format(
                        frappe.bold(condition.field), frappe.bold(self.document_type)
                    )
                )

    def on_update(self):
        self.clear_doctype_map()

    def on_trash(self):
        self.clear_doctype_map()

    def clear_doctype_map(self):
        frappe.cache_manager.clear_doctype_map(self.doctype, self.document_type)

    def matches(self, doc) -> bool:
        if not self.conditions:
            return True
        return evaluate_filters(
            doc, [(self.document_type, c.field, c.condition, c.value) for c in self.conditions]
        )

    def apply(self, doc) -> bool:
        """Set doc.name if this rule matches. Returns whether it applied."""
        if not self.matches(doc):
            return False

        doc.flags.posting_date_naming_date_field = self.date_field or None
        doc.name = parse_naming_series(self.prefix, doc=doc)
        return True
