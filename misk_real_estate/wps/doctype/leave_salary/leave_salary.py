# apps/misk_real_estate/misk_real_estate/wps/doctype/leave_salary/leave_salary.py
#
# Leave Salary = Gross / 30 x eligible leave days, created and submitted
# automatically when a Leave Salary type Leave Application is approved (see
# wps/leave_salary.py). Submitting creates an Additional Salary of the "Leave
# Salary" component, so the amount is paid as its own earning row on the
# Salary Slip covering payroll_date; cancelling cancels it again. To correct
# the days or amount, cancel and amend.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from misk_real_estate.wps.leave_salary import (
	calculate_leave_salary,
	get_gross_for_leave_salary,
	get_leave_salary_payroll_date,
	is_leave_salary_type,
)


class LeaveSalary(Document):
	def validate(self):
		self.validate_leave_application()
		self.validate_duplicate()

		if not self.payroll_date:
			self.payroll_date = get_leave_salary_payroll_date(self.employee, self.from_date)
		if not flt(self.monthly_gross):
			self.monthly_gross = get_gross_for_leave_salary(self.employee, self.from_date)

		if flt(self.eligible_days) <= 0:
			frappe.throw(_("Eligible Leave Days must be more than zero"))

		self.amount = flt(calculate_leave_salary(self.monthly_gross, self.eligible_days), self.precision("amount"))

	def validate_leave_application(self):
		la = frappe.db.get_value(
			"Leave Application",
			self.leave_application,
			["employee", "leave_type", "from_date", "to_date", "status", "docstatus"],
			as_dict=True,
		)
		if not la:
			frappe.throw(_("Leave Application {0} not found").format(frappe.bold(self.leave_application)))
		if la.employee != self.employee:
			frappe.throw(
				_("Leave Application {0} belongs to another employee").format(frappe.bold(self.leave_application))
			)
		if la.docstatus != 1 or la.status != "Approved":
			frappe.throw(
				_("Leave Application {0} must be approved and submitted").format(frappe.bold(self.leave_application))
			)
		if not is_leave_salary_type(la.leave_type):
			frappe.throw(
				_("Leave Type {0} does not have Leave Salary enabled").format(frappe.bold(la.leave_type))
			)

		self.leave_type, self.from_date, self.to_date = la.leave_type, la.from_date, la.to_date

	def validate_duplicate(self):
		existing = frappe.db.get_value(
			"Leave Salary",
			{"leave_application": self.leave_application, "docstatus": 1, "name": ("!=", self.name)},
		)
		if existing:
			frappe.throw(
				_("Leave Salary {0} already exists for Leave Application {1}").format(
					frappe.get_desk_link("Leave Salary", existing), frappe.bold(self.leave_application)
				)
			)

	def on_submit(self):
		additional_salary = frappe.get_doc(
			{
				"doctype": "Additional Salary",
				"employee": self.employee,
				"company": self.company,
				"salary_component": self.salary_component,
				"amount": self.amount,
				"payroll_date": self.payroll_date,
				"overwrite_salary_structure_amount": 0,
				"ref_doctype": self.doctype,
				"ref_docname": self.name,
			}
		)
		additional_salary.flags.ignore_permissions = True
		additional_salary.insert()
		additional_salary.submit()

		self.db_set("additional_salary", additional_salary.name)
		frappe.db.set_value(
			"Leave Application", self.leave_application, "custom_leave_salary", self.name, update_modified=False
		)

	def on_cancel(self):
		# the submitted Leave Application links back here; it's cleared below
		self.ignore_linked_doctypes = ("Leave Application",)

		if self.additional_salary and frappe.db.get_value("Additional Salary", self.additional_salary, "docstatus") == 1:
			additional_salary = frappe.get_doc("Additional Salary", self.additional_salary)
			additional_salary.flags.ignore_permissions = True
			additional_salary.cancel()

		if frappe.db.get_value("Leave Application", self.leave_application, "custom_leave_salary") == self.name:
			frappe.db.set_value(
				"Leave Application", self.leave_application, "custom_leave_salary", None, update_modified=False
			)
