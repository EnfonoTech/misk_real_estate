import frappe
from frappe.model.document import Document


class WPSSettings(Document):
    pass


def get_settings():
    return frappe.get_cached_doc("WPS Settings")
