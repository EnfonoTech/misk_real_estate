# Copyright (c) 2026, Enfono Technologies and Contributors
# See license.txt
#
# End-to-end Leave Salary flow (wps/leave_salary.py) on an existing employee
# with a Salary Structure Assignment -- everything is rolled back afterwards.

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, getdate

from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	get_assigned_salary_structure,
)

from misk_real_estate.wps.leave_salary import (
	LEAVE_SALARY_COMPONENT,
	get_employees_awaiting_rejoining,
	get_gross_for_leave_salary,
)

LEAVE_TYPE = "Annual Leave"
FROM_DATE, TO_DATE = getdate("2026-10-10"), getdate("2026-11-11")


class TestLeaveSalary(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Leave Type", LEAVE_TYPE) or not frappe.db.exists(
			"Salary Component", LEAVE_SALARY_COMPONENT
		):
			self.skipTest("Annual Leave / Leave Salary component not set up")

		self.employee = self.get_free_employee()
		if not self.employee:
			self.skipTest("No employee with a Salary Structure Assignment and no leave in the test period")

		# allow_negative: no paid / unpaid split, whatever the existing balance
		frappe.db.set_value("Leave Type", LEAVE_TYPE, {"custom_leave_salary": 1, "allow_negative": 1})
		frappe.clear_cache(doctype="Leave Type")
		frappe.db.set_single_value("Payroll Settings", "include_holidays_in_total_working_days", 1)
		frappe.db.set_single_value("Payroll Settings", "payroll_based_on", "Leave")

		if frappe.db.exists(
			"Leave Allocation",
			{"employee": self.employee, "leave_type": LEAVE_TYPE, "docstatus": 1, "to_date": (">=", TO_DATE), "from_date": ("<=", FROM_DATE)},
		):
			return
		allocation = frappe.get_doc(
			{
				"doctype": "Leave Allocation",
				"employee": self.employee,
				"leave_type": LEAVE_TYPE,
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"new_leaves_allocated": 60,
			}
		)
		allocation.insert(ignore_permissions=True)
		allocation.submit()

	def get_free_employee(self):
		for employee in frappe.get_all(
			"Salary Structure Assignment", filters={"docstatus": 1}, pluck="employee", distinct=True
		):
			if frappe.db.get_value("Employee", employee, "status") != "Active":
				continue
			if frappe.db.exists(
				"Leave Application",
				{"employee": employee, "docstatus": ("<", 2), "from_date": ("<=", "2026-12-31"), "to_date": (">=", "2026-09-01")},
			):
				continue
			if frappe.db.exists("Salary Slip", {"employee": employee, "end_date": (">=", "2026-10-01")}):
				continue
			return employee

	def make_leave_application(self, from_date=FROM_DATE, to_date=TO_DATE):
		la = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": self.employee,
				"leave_type": LEAVE_TYPE,
				"from_date": from_date,
				"to_date": to_date,
				"status": "Approved",
				"follow_via_email": 0,
				"leave_approver": frappe.db.get_value("Employee", self.employee, "leave_approver"),
			}
		)
		la.insert(ignore_permissions=True)
		la.submit()
		return la

	def make_slip(self, posting_date):
		structure = get_assigned_salary_structure(self.employee, posting_date)
		slip = make_salary_slip(structure, employee=self.employee, posting_date=posting_date, ignore_permissions=True)
		slip.insert(ignore_permissions=True)
		return slip

	def test_leave_salary_flow(self):
		la = self.make_leave_application()
		self.assertTrue(la.custom_leave_salary)

		leave_salary = frappe.get_doc("Leave Salary", la.custom_leave_salary)
		gross = get_gross_for_leave_salary(self.employee, FROM_DATE)
		self.assertEqual(leave_salary.docstatus, 1)
		self.assertEqual(flt(leave_salary.eligible_days), flt(la.total_leave_days))
		self.assertEqual(flt(leave_salary.amount, 2), flt(gross / 30 * flt(la.total_leave_days), 2))
		self.assertEqual(getdate(leave_salary.payroll_date), FROM_DATE)
		self.assertEqual(frappe.db.get_value("Additional Salary", leave_salary.additional_salary, "docstatus"), 1)

		# October: worked 1-9 Oct only, Leave Salary as its own earning row
		october = self.make_slip("2026-10-15")
		self.assertEqual(october.custom_leave_salary_days, 22)
		self.assertEqual(october.payment_days, 9)
		leave_rows = [row for row in october.earnings if row.salary_component == LEAVE_SALARY_COMPONENT]
		self.assertEqual(len(leave_rows), 1)
		self.assertEqual(flt(leave_rows[0].amount, 2), flt(leave_salary.amount, 2))
		self.assertEqual(
			flt(october.gross_pay, 2),
			flt(sum(flt(r.amount) for r in october.earnings if not r.do_not_include_in_total), 2),
		)
		october.delete()

		# November, not rejoined yet: 11 leave days + 19 awaiting -> nothing paid
		november = self.make_slip("2026-11-15")
		self.assertEqual(november.custom_leave_salary_days, 11)
		self.assertEqual(november.custom_awaiting_rejoining_days, 19)
		self.assertEqual(november.payment_days, 0)
		november.delete()

		self.assertIn(self.employee, get_employees_awaiting_rejoining("2026-11-13"))
		attendance = frappe.get_doc(
			{"doctype": "Attendance", "employee": self.employee, "attendance_date": "2026-11-13", "status": "Present"}
		)
		self.assertRaises(frappe.ValidationError, attendance.insert, ignore_permissions=True)

		# HR confirms rejoining on 14 Nov: 12-13 Nov unpaid, paid from the 14th
		la.reload()
		la.custom_actual_rejoining_date = "2026-11-14"
		la.save(ignore_permissions=True)
		november = self.make_slip("2026-11-15")
		self.assertEqual(november.custom_awaiting_rejoining_days, 2)
		self.assertEqual(november.payment_days, 30 - 11 - 2)
		self.assertNotIn(self.employee, get_employees_awaiting_rejoining("2026-11-14"))
		november.delete()

		# cancelling the leave cancels its Leave Salary and Additional Salary
		la.reload()
		la.cancel()
		self.assertEqual(frappe.db.get_value("Leave Salary", leave_salary.name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Additional Salary", leave_salary.additional_salary, "docstatus"), 2)

	def test_rejoining_date_is_hr_only(self):
		la = self.make_leave_application()
		la.reload()
		la.custom_actual_rejoining_date = "2026-11-12"
		frappe.set_user("Guest")
		try:
			self.assertRaises(frappe.PermissionError, la.save, ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_rejoining_date_must_be_after_leave_start(self):
		la = self.make_leave_application()
		la.reload()
		la.custom_actual_rejoining_date = FROM_DATE
		self.assertRaises(frappe.ValidationError, la.save, ignore_permissions=True)
