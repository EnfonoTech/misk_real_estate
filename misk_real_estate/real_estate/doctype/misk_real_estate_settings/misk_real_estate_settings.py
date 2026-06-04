import frappe
from frappe.model.document import Document


class MiskRealEstateSettings(Document):
    pass


def get_settings():
    return frappe.get_cached_doc("Misk Real Estate Settings")
