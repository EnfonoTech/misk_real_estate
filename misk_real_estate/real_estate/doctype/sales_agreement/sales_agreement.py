# apps/misk_real_estate/misk_real_estate/real_estate/doctype/sales_agreement/sales_agreement.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class SalesAgreement(Document):
    def validate(self):
        self._reset_status_if_amended()
        self._validate_eligibility()
        self._validate_single_active_agreement()

    def _reset_status_if_amended(self):
        """Amending a cancelled agreement copies its old field values —
        including status="Cancelled" — onto the fresh (docstatus=0) draft.
        Nothing else sets a non-Draft status while docstatus is 0, so reset
        it back rather than leaving it stuck."""
        if self.docstatus == 0 and self.status == "Cancelled":
            self.status = "Draft"

    def before_insert(self):
        self._pull_from_booking()

    def before_submit(self):
        """Submitting IS generating the contract — no separate PDF-generation
        step; staff use the standard Print button (Sales Agreement (Arabic)
        format) on demand instead of an attached, one-time-rendered file.
        Set here (not on_submit) — the DB row is written from the values as
        of before_submit/validate; anything assigned in on_submit itself
        runs after that write already happened and is silently lost."""
        self.status = "Generated"

    def before_cancel(self):
        """Same reasoning as before_submit — on_cancel fires after the
        docstatus=2 row is already written, so a plain assignment there
        never persists."""
        self.status = "Cancelled"

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
            {
                "property_booking": self.property_booking,
                "name": ("!=", self.name or ""),
                "docstatus": ("!=", 2),
            },
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
        silently drift if the booking record changes later. Totals are aggregated
        across every unit on the booking; the `units` table lists each one with
        its own price and payment plan."""
        booking = frappe.get_doc("Property Booking", self.property_booking)

        customer = frappe.db.get_value(
            "Customer", booking.customer,
            ["customer_name", "id_number", "mobile_no", "email_id", "primary_address"],
            as_dict=True,
        ) or {}
        self.company = booking.company
        self.customer = booking.customer
        self.customer_name = customer.get("customer_name")
        self.customer_id_number = customer.get("id_number")
        self.customer_mobile = customer.get("mobile_no")
        self.customer_email = customer.get("email_id")
        self.customer_address = customer.get("primary_address")

        self.units = []
        for row in booking.property_unit:
            unit_info = frappe.db.get_value(
                "Item", row.unit, ["unit_area_sqft", "unit_type", "floor_number"], as_dict=True
            ) if row.unit else {}
            self.append("units", {
                "building": row.building,
                "unit": row.unit,
                "price_list": row.price_list,
                "unit_price": row.unit_price,
                "booking_amount": row.booking_amount,
                "down_payment_percentage": row.down_payment_percentage,
                "down_payment_amount": row.down_payment_amount,
                "owners_association_fee": row.owners_association_fee,
                "unit_area_sqft": (unit_info or {}).get("unit_area_sqft"),
                "unit_type": (unit_info or {}).get("unit_type"),
                "floor_number": (unit_info or {}).get("floor_number"),
                "payment_plan": row.payment_plan,
                "number_of_installments": row.number_of_installments,
                "monthly_installment": row.monthly_installment,
            })

        self.selling_price = booking.total_unit_price
        self.booking_amount = booking.total_booking_amount
        self.booking_date = booking.booking_date
        self.down_payment_amount = booking.total_down_payment_amount
        self.down_payment_date = booking.down_payment_date
        self.balance_amount = flt(
            flt(booking.total_unit_price) - flt(booking.total_booking_amount)
            - flt(booking.total_down_payment_amount), 3
        )

        self.first_installment_due_date = self._first_due_date(booking, "Installment")

        self.management_fee_amount = booking.total_owners_association_fee
        self.management_fee_due_date = self._first_due_date(booking, "Owners Association Fee")

        self.sales_person = booking.sales_person

        self.pdc_schedule = []
        for row in booking.pdc_schedule:
            self.append("pdc_schedule", {
                "sequence_no": row.sequence_no,
                "unit": row.unit,
                "installment_type": row.installment_type,
                "is_pdc": row.is_pdc,
                "cheque_date": row.cheque_date,
                "net_amount": row.net_amount,
                "tax_amount": row.tax_amount,
                "amount": row.amount,
                "cheque_no": row.cheque_no,
                "status": row.status,
                "sales_invoice": row.sales_invoice,
                "payment_entry": row.payment_entry,
                "pdc_entry": row.pdc_entry,
                "unit_breakdown": row.unit_breakdown,
            })

    def _first_due_date(self, booking, installment_type):
        dates = [
            getdate(r.cheque_date) for r in booking.pdc_schedule
            if r.installment_type == installment_type and r.cheque_date
        ]
        return min(dates) if dates else None


@frappe.whitelist()
def mark_signed(sales_agreement_name):
    """Manual milestone — staff confirms the customer has physically signed.
    Uses db_set (not a full save) since this changes a field on an already-
    submitted document without going through the update_after_submit path."""
    frappe.has_permission("Sales Agreement", "write", throw=True)
    agreement = frappe.get_doc("Sales Agreement", sales_agreement_name)
    if agreement.docstatus != 1 or agreement.status != "Generated":
        frappe.throw(_("Only a Generated agreement can be marked Signed (current: {0}).").format(agreement.status))
    agreement.db_set("status", "Signed")
    frappe.msgprint(_("Contract {0} marked as Signed.").format(agreement.name), alert=True)


@frappe.whitelist()
def mark_registered(sales_agreement_name):
    """Manual milestone — staff confirms the contract has been officially registered."""
    frappe.has_permission("Sales Agreement", "write", throw=True)
    agreement = frappe.get_doc("Sales Agreement", sales_agreement_name)
    if agreement.docstatus != 1 or agreement.status != "Signed":
        frappe.throw(_("Only a Signed agreement can be marked Registered (current: {0}).").format(agreement.status))
    agreement.db_set("status", "Registered")
    frappe.msgprint(_("Contract {0} marked as Registered.").format(agreement.name), alert=True)
