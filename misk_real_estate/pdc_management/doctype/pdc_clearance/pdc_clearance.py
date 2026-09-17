# apps/misk_real_estate/misk_real_estate/pdc_management/doctype/pdc_clearance/pdc_clearance.py

from frappe.model.document import Document


class PDCClearance(Document):
    """One money-in event against a cheque that did NOT clear in full.

    Only ever written by pdc_entry.record_partial_clearance() — every row is
    read-only in the grid, and a normally-cleared cheque (the overwhelming
    majority) has none at all."""
    pass
