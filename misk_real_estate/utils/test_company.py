import frappe
from frappe.tests.utils import FrappeTestCase

from misk_real_estate.utils.company import get_item_company


class TestCompanyUtils(FrappeTestCase):
    def setUp(self):
        companies = frappe.get_all("Company", limit=2, pluck="name")
        if len(companies) < 2:
            self.skipTest("Requires at least 2 existing Companies.")
        self.company_a, self.company_b = companies

        self.group = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": "TEST-COMPANY-UTIL-GROUP",
            "parent_item_group": "All Item Groups",
            "is_group": 0,
            "company": self.company_a,
        }).insert(ignore_permissions=True)
        self.addCleanup(frappe.delete_doc, "Item Group", self.group.name, force=True)

    def _make_item(self, item_code, company=None):
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_code,
            "item_group": self.group.name,
            "is_sales_item": 1,
            "is_stock_item": 0,
        }).insert(ignore_permissions=True)
        # Frappe auto-fills any new doc's blank "company" field from the site's
        # global default (Document._set_defaults) — force it back to the value
        # this test actually wants, same as a user clearing the auto-filled default.
        frappe.db.set_value("Item", item.name, "company", company)
        item.reload()
        self.addCleanup(frappe.delete_doc, "Item", item.name, force=True)
        return item

    def test_inherits_company_from_item_group_when_blank(self):
        item = self._make_item("TEST-COMPANY-UTIL-INHERIT")
        self.assertEqual(get_item_company(item.name), self.company_a)

    def test_own_company_overrides_item_group(self):
        item = self._make_item("TEST-COMPANY-UTIL-OVERRIDE", company=self.company_b)
        self.assertEqual(get_item_company(item.name), self.company_b)
