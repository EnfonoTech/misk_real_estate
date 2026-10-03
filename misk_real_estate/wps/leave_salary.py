# apps/misk_real_estate/misk_real_estate/wps/leave_salary.py
#
# Misk Leave Salary (vacation pay), for Leave Types with "Leave Salary"
# (custom_leave_salary) ticked:
#
#   * Approving the Leave Application creates and submits a Leave Salary
#     document: Gross / 30 x eligible leave days (the paid days left after the
#     paid / unpaid split in custom_leave_application.py). Its submit creates
#     an Additional Salary of the "Leave Salary" component, so the amount shows
#     as its own earning row on the Salary Slip covering its payroll date.
#   * The vacation itself is not paid again in the monthly salary: every day
#     from the leave start up to the day before the Actual Rejoining Date is
#     taken out of the slip's payment days (custom_salary_slip.py):
#       - the leave days themselves      -> custom_leave_salary_days
#       - the unpaid (LWP) part, if any  -> already stock HRMS leave_without_pay
#       - days after the leave until HR  -> custom_awaiting_rejoining_days
#         enters the Actual Rejoining Date (open-ended while it is blank)
#   * Attendance cannot be marked Present for the awaiting-rejoining days
#     (attendance_hooks.py), and the Daily Attendance Tool leaves those
#     employees out.
#
# Only HR (HR_ROLES) can set the Actual Rejoining Date.

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	get_assigned_salary_structure,
)

from misk_real_estate.wps.end_of_service import LEAVE_SALARY_DAYS_DIVISOR, get_monthly_gross

LEAVE_SALARY_COMPONENT = "Leave Salary"
HR_ROLES = ("HR Manager", "HR User", "System Manager")


def is_leave_salary_type(leave_type):
	return bool(leave_type and cint(frappe.get_cached_value("Leave Type", leave_type, "custom_leave_salary")))


def is_hr_user():
	return bool(set(HR_ROLES) & set(frappe.get_roles()))


def calculate_leave_salary(monthly_gross, eligible_days):
	return flt(monthly_gross) / LEAVE_SALARY_DAYS_DIVISOR * flt(eligible_days)


def get_gross_for_leave_salary(employee, on_date):
	"""Full-month gross, same as Leave Encashment (last submitted Salary Slip),
	falling back to the assigned Salary Structure for an employee who has no
	submitted slip yet."""
	if frappe.db.exists("Salary Slip", {"employee": employee, "docstatus": 1, "start_date": ("<=", on_date)}):
		return get_monthly_gross(employee, on_date)

	salary_structure = get_assigned_salary_structure(employee, on_date)
	if not salary_structure:
		frappe.throw(
			_("No Salary Structure assigned to Employee {0} on {1} to take Gross Salary from").format(
				frappe.bold(employee), frappe.bold(frappe.format(on_date, "Date"))
			)
		)

	# for_preview pays the full month (payment days = working days)
	salary_slip = make_salary_slip(
		salary_structure, employee=employee, posting_date=on_date, for_preview=1, ignore_permissions=True
	)
	gross = sum(
		flt(row.amount)
		for row in salary_slip.earnings
		if not row.additional_salary and not row.statistical_component and not row.do_not_include_in_total
	)
	if gross <= 0:
		frappe.throw(_("Gross Salary is zero in Salary Structure {0}").format(frappe.bold(salary_structure)))

	return gross


def get_leave_salary_payroll_date(employee, from_date):
	"""The leave start date, unless a submitted Salary Slip already covers it
	-- then the day after the last submitted slip, so the amount still lands
	on a slip that has not been paid yet."""
	last_paid_end = frappe.db.get_value(
		"Salary Slip",
		{"employee": employee, "docstatus": 1, "end_date": (">=", from_date)},
		"end_date",
		order_by="end_date desc",
	)
	return add_days(last_paid_end, 1) if last_paid_end else getdate(from_date)


def create_leave_salary(leave_application):
	"""Called when an approved Leave Application of a Leave Salary type is submitted."""
	la = leave_application
	leave_salary = frappe.get_doc(
		{
			"doctype": "Leave Salary",
			"employee": la.employee,
			"leave_application": la.name,
			"posting_date": getdate(la.posting_date) if la.posting_date else None,
			"eligible_days": flt(la.total_leave_days),
		}
	)
	leave_salary.flags.ignore_permissions = True
	leave_salary.insert()
	leave_salary.submit()

	frappe.msgprint(
		_("Leave Salary {0} of {1} created for {2} day(s), paid with the Salary Slip covering {3}").format(
			frappe.get_desk_link("Leave Salary", leave_salary.name),
			frappe.bold(frappe.format(leave_salary.amount, {"fieldtype": "Currency"})),
			frappe.bold(leave_salary.eligible_days),
			frappe.bold(frappe.format(leave_salary.payroll_date, "Date")),
		),
		indicator="green",
		alert=True,
	)
	return leave_salary


def cancel_leave_salary(leave_application):
	for name in frappe.get_all(
		"Leave Salary", filters={"leave_application": leave_application, "docstatus": 1}, pluck="name"
	):
		leave_salary = frappe.get_doc("Leave Salary", name)
		leave_salary.flags.ignore_permissions = True
		leave_salary.cancel()


# ── Vacation periods ──────────────────────────────────────────────────────────


def get_vacations(employee, from_date, to_date):
	"""Approved leave applications of `employee` that have a Leave Salary
	document (so leave approved before this feature is never picked up) and
	whose vacation
	(leave start up to the day before the Actual Rejoining Date, open-ended
	while that is blank) overlaps from_date..to_date. Each gets:
	  leave_end   -- last paid leave day (to_date)
	  vacation_end -- last day of the whole requested leave, unpaid part included
	"""
	la = frappe.qb.DocType("Leave Application")
	rows = (
		frappe.qb.from_(la)
		.select(la.name, la.from_date, la.to_date, la.unpaid_to_date, la.custom_actual_rejoining_date)
		.where(la.employee == employee)
		.where(la.custom_leave_salary.isnotnull() & (la.custom_leave_salary != ""))
		.where(la.docstatus == 1)
		.where(la.status == "Approved")
		.where(la.from_date <= to_date)
		.where(la.custom_actual_rejoining_date.isnull() | (la.custom_actual_rejoining_date > from_date))
	).run(as_dict=True)

	for row in rows:
		row.from_date = getdate(row.from_date)
		row.leave_end = getdate(row.to_date)
		row.vacation_end = max(row.leave_end, getdate(row.unpaid_to_date or row.to_date))
		row.rejoining_date = (
			getdate(row.custom_actual_rejoining_date) if row.custom_actual_rejoining_date else None
		)
	return rows


def get_other_leave_dates(employee, from_date, to_date, exclude):
	"""Dates covered by any other approved leave in the range (e.g. an LWP HR
	files for an overstay) -- those are already handled by stock HRMS."""
	dates = set()
	for row in frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			"name": ("not in", exclude or [""]),
			"from_date": ("<=", to_date),
			"to_date": (">=", from_date),
		},
		fields=["from_date", "to_date"],
	):
		day = getdate(row.from_date)
		while day <= getdate(row.to_date):
			dates.add(day)
			day = add_days(day, 1)
	return dates


def get_vacation_days(employee, from_date, to_date, skip_dates=None):
	"""(leave_salary_days, awaiting_rejoining_days) between from_date and
	to_date. Days in skip_dates (holidays when payroll leaves them out of
	working days, days outside employment) are not counted."""
	from_date, to_date = getdate(from_date), getdate(to_date)
	vacations = get_vacations(employee, from_date, to_date)
	if not vacations:
		return 0, 0

	skip_dates = set(skip_dates or [])
	other_leave_dates = get_other_leave_dates(employee, from_date, to_date, [v.name for v in vacations])

	leave_days = awaiting_days = 0
	day = from_date
	while day <= to_date:
		if day not in skip_dates:
			for vacation in vacations:
				if day < vacation.from_date or (vacation.rejoining_date and day >= vacation.rejoining_date):
					continue
				if day <= vacation.leave_end:
					leave_days += 1
				elif day > vacation.vacation_end and day not in other_leave_dates:
					awaiting_days += 1
				# the unpaid (LWP) part in between is stock HRMS leave_without_pay
				break
		day = add_days(day, 1)

	return leave_days, awaiting_days


def get_awaiting_rejoining_application(employee, date):
	"""The Leave Application `employee` has not yet rejoined from on `date`
	(date after the whole leave, before the Actual Rejoining Date), or None."""
	date = getdate(date)
	for vacation in get_vacations(employee, date, date):
		if date > vacation.vacation_end:
			return vacation.name
	return None


def get_employees_awaiting_rejoining(date):
	date = getdate(date)
	la = frappe.qb.DocType("Leave Application")
	rows = (
		frappe.qb.from_(la)
		.select(la.employee, la.to_date, la.unpaid_to_date)
		.where(la.custom_leave_salary.isnotnull() & (la.custom_leave_salary != ""))
		.where(la.docstatus == 1)
		.where(la.status == "Approved")
		.where(la.to_date < date)
		.where(la.custom_actual_rejoining_date.isnull() | (la.custom_actual_rejoining_date > date))
	).run(as_dict=True)
	return {
		row.employee for row in rows if max(getdate(row.to_date), getdate(row.unpaid_to_date or row.to_date)) < date
	}
