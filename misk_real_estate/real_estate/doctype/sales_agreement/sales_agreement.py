# apps/misk_real_estate/misk_real_estate/real_estate/doctype/sales_agreement/sales_agreement.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate
from frappe.utils.file_manager import save_file

PRINT_FORMAT = "Sales Agreement (Arabic)"


class SalesAgreement(Document):
    def validate(self):
        self._validate_eligibility()
        self._validate_single_active_agreement()

    def before_insert(self):
        self._pull_from_booking()

    def _validate_eligibility(self):
        from misk_real_estate.real_estate.doctype.property_booking.property_booking import (
            check_contract_eligibility,
        )
        booking = frappe.get_doc("Property Booking", self.property_booking)
        failures = check_contract_eligibility(booking)
        if failures:
            frappe.throw("<br>".join(failures), title=_("Not Eligible for Contract Generation"))

    def _validate_single_active_agreement(self):
        existing = frappe.db.exists(
            "Sales Agreement",
            {"property_booking": self.property_booking, "name": ("!=", self.name or "")},
        )
        if existing:
            frappe.throw(
                _("A Sales Agreement ({0}) already exists for booking {1}.").format(
                    existing, self.property_booking
                )
            )

    def _pull_from_booking(self):
        """One-time snapshot of booking/customer/unit terms at contract creation —
        deliberately not kept in sync afterwards; a generated agreement shouldn't
        silently drift if the booking record changes later."""
        booking = frappe.get_doc("Property Booking", self.property_booking)
        row = booking._get_unit_row()

        customer = frappe.db.get_value(
            "Customer", booking.customer,
            ["customer_name", "id_number", "mobile_no", "email_id", "primary_address"],
            as_dict=True,
        ) or {}
        self.customer = booking.customer
        self.customer_name = customer.get("customer_name")
        self.customer_id_number = customer.get("id_number")
        self.customer_mobile = customer.get("mobile_no")
        self.customer_email = customer.get("email_id")
        self.customer_address = customer.get("primary_address")

        self.building = row.building
        self.unit = row.unit
        if row.unit:
            unit_info = frappe.db.get_value(
                "Item", row.unit, ["unit_area_sqft", "unit_type", "floor_number"], as_dict=True
            ) or {}
            self.unit_area_sqft = unit_info.get("unit_area_sqft")
            self.unit_type = unit_info.get("unit_type")
            self.floor_number = unit_info.get("floor_number")

        self.selling_price = row.unit_price
        self.booking_amount = row.booking_amount
        self.booking_date = booking.booking_date
        self.down_payment_amount = row.down_payment_amount
        self.down_payment_date = row.down_payment_date
        self.balance_amount = round(
            flt(row.unit_price) - flt(row.booking_amount) - flt(row.down_payment_amount), 3
        )

        self.payment_plan = row.payment_plan
        self.number_of_installments = row.number_of_installments
        self.monthly_installment = row.monthly_installment
        self.first_installment_due_date = self._first_due_date(booking, "Installment")

        self.management_fee_amount = row.owners_association_fee
        self.management_fee_due_date = self._first_due_date(booking, "Owners Association Fee")

        self.sales_person = booking.sales_person

    def _first_due_date(self, booking, installment_type):
        dates = [
            getdate(r.cheque_date) for r in booking.pdc_schedule
            if r.installment_type == installment_type and r.cheque_date
        ]
        return min(dates) if dates else None


@frappe.whitelist()
def mark_generated(sales_agreement_name):
    """Render the Arabic contract Print Format to PDF, attach it, and advance
    status Draft -> Generated."""
    frappe.has_permission("Sales Agreement", "write", throw=True)
    agreement = frappe.get_doc("Sales Agreement", sales_agreement_name)
    if agreement.status != "Draft":
        frappe.throw(_("Only a Draft agreement can be generated (current: {0}).").format(agreement.status))

    pdf_content = frappe.get_print(
        "Sales Agreement", agreement.name,
        print_format=PRINT_FORMAT,
        as_pdf=True,
    )
    file_doc = save_file(
        f"{agreement.name}.pdf", pdf_content,
        "Sales Agreement", agreement.name,
        is_private=1,
    )
    agreement.contract_pdf = file_doc.file_url
    agreement.status = "Generated"
    agreement.save(ignore_permissions=True)
    frappe.msgprint(_("Contract generated for {0}.").format(agreement.name), alert=True)


@frappe.whitelist()
def mark_signed(sales_agreement_name):
    """Manual milestone — staff confirms the customer has physically signed."""
    frappe.has_permission("Sales Agreement", "write", throw=True)
    agreement = frappe.get_doc("Sales Agreement", sales_agreement_name)
    if agreement.status != "Generated":
        frappe.throw(_("Only a Generated agreement can be marked Signed (current: {0}).").format(agreement.status))
    agreement.status = "Signed"
    agreement.save(ignore_permissions=True)
    frappe.msgprint(_("Contract {0} marked as Signed.").format(agreement.name), alert=True)


@frappe.whitelist()
def mark_registered(sales_agreement_name):
    """Manual milestone — staff confirms the contract has been officially registered."""
    frappe.has_permission("Sales Agreement", "write", throw=True)
    agreement = frappe.get_doc("Sales Agreement", sales_agreement_name)
    if agreement.status != "Signed":
        frappe.throw(_("Only a Signed agreement can be marked Registered (current: {0}).").format(agreement.status))
    agreement.status = "Registered"
    agreement.save(ignore_permissions=True)
    frappe.msgprint(_("Contract {0} marked as Registered.").format(agreement.name), alert=True)
