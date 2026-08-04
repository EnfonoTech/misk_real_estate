import frappe
from frappe import _
from frappe.model.document import Document


class MiskRealEstateSettings(Document):
    def validate(self):
        self._validate_income_account_mapping()

    def _validate_income_account_mapping(self):
        for row in self.income_account_mapping:
            account_company = frappe.db.get_value("Account", row.income_account, "company")
            if account_company and account_company != row.company:
                frappe.throw(
                    _("Row {0}: Income Account {1} belongs to {2}, not {3}.").format(
                        row.idx, row.income_account, account_company, row.company
                    )
                )


def get_settings():
    return frappe.get_cached_doc("Misk Real Estate Settings")
