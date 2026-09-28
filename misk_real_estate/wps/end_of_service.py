# apps/misk_real_estate/misk_real_estate/wps/end_of_service.py
#
# Misk end-of-service rules (gratuity + leave salary), shared by
# custom_gratuity.py and custom_leave_encashment.py:
#
#   Gratuity      = Basic x (DOJ..Relieving Date inclusive - unpaid leave days) / 365
#   Leave salary  = Gross / 30 x leave days
#
# (Leave earning itself is stock HRMS earned leave: 30/yr -> 2.5 a month.)
#
# "Unpaid leave" means approved, submitted Leave Applications of a Leave Type
# marked Is Leave Without Pay -- a half day counts 0.5, and holidays count or
# not per that Leave Type's own "include holidays" setting, the same way HRMS
# counts the leave itself. Plain absence (no leave application) is NOT unpaid
# leave here.

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, get_last_day, getdate

from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days

LEAVE_SALARY_DAYS_DIVISOR = 30


def get_lwp_leave_types():
	return frappe.get_all("Leave Type", filters={"is_lwp": 1}, pluck="name")


def get_unpaid_leave_segments(leave_application, from_date=None, to_date=None):
	"""Yield (segment_from, segment_to, unpaid_days) for each calendar month the
	application covers, clipped to from_date..to_date when given."""
	la = leave_application
	start = max(getdate(la.from_date), getdate(from_date or la.from_date))
	end = min(getdate(la.to_date), getdate(to_date or la.to_date))
	half_day_date = getdate(la.half_day_date) if la.half_day_date else None

	while start <= end:
		segment_end = min(get_last_day(start), end)
		# get_number_of_leave_days treats a one-day range with half_day set as
		# 0.5 whatever the half_day_date is, so only pass half_day when this
		# segment is where the half day actually falls.
		half_day = la.half_day and (
			getdate(la.from_date) == getdate(la.to_date)
			or (half_day_date and start <= half_day_date <= segment_end)
		)
		days = get_number_of_leave_days(
			la.employee,
			la.leave_type,
			start,
			segment_end,
			half_day=1 if half_day else 0,
			half_day_date=half_day_date if half_day else None,
		)
		yield start, segment_end, flt(days)
		start = add_days(segment_end, 1)


def get_unpaid_leave_applications(employee, from_date, to_date):
	lwp_types = get_lwp_leave_types()
	if not lwp_types:
		return []

	return frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"leave_type": ("in", lwp_types),
			"docstatus": 1,
			"status": "Approved",
			"from_date": ("<=", to_date),
			"to_date": (">=", from_date),
		},
		fields=["name", "employee", "leave_type", "from_date", "to_date", "half_day", "half_day_date"],
	)


def get_unpaid_leave_days(employee, from_date, to_date):
	return sum(
		days
		for la in get_unpaid_leave_applications(employee, from_date, to_date)
		for _start, _end, days in get_unpaid_leave_segments(la, from_date, to_date)
	)


def get_gratuity_service_days(employee):
	date_of_joining, relieving_date = frappe.db.get_value(
		"Employee", employee, ["date_of_joining", "relieving_date"]
	)
	if not date_of_joining:
		frappe.throw(_("Please set Date of Joining for employee: {0}").format(frappe.bold(employee)))
	if not relieving_date:
		frappe.throw(_("Please set Relieving Date for employee: {0}").format(frappe.bold(employee)))
	if getdate(relieving_date) < getdate(date_of_joining):
		frappe.throw(_("Relieving Date cannot be before Date of Joining for employee: {0}").format(employee))

	# DOJ and relieving date both count as service days (the settlement sheet's =C3-C2+1)
	total_days = date_diff(relieving_date, date_of_joining) + 1
	return total_days - get_unpaid_leave_days(employee, date_of_joining, relieving_date)


def get_monthly_gross(employee, on_date):
	"""Full-month gross of the employee's last submitted Salary Slip on/before
	on_date -- structure earnings only, so one-off Additional Salary rows
	(arrears, earlier encashments, gratuity) don't inflate the leave salary."""
	salary_slip = frappe.db.get_value(
		"Salary Slip",
		{"employee": employee, "docstatus": 1, "start_date": ("<=", on_date)},
		order_by="start_date desc",
	)
	if not salary_slip:
		frappe.throw(
			_("No submitted Salary Slip found for Employee {0} on or before {1} to take Gross Salary from").format(
				frappe.bold(employee), frappe.bold(frappe.format(on_date, "Date"))
			)
		)

	salary_slip = frappe.get_doc("Salary Slip", salary_slip)
	# same as HRMS Gratuity: full payment days, so a short last month (joining,
	# unpaid leave) doesn't lower the monthly figure
	salary_slip.payment_days = salary_slip.total_working_days
	salary_slip.calculate_net_pay()

	gross = sum(
		flt(row.amount)
		for row in salary_slip.earnings
		if not row.additional_salary and not row.statistical_component and not row.do_not_include_in_total
	)
	if gross <= 0:
		frappe.throw(_("Gross Salary is zero on Salary Slip {0}").format(frappe.bold(salary_slip.name)))

	return gross


def get_leave_salary(employee, on_date, leave_days):
	return get_monthly_gross(employee, on_date) / LEAVE_SALARY_DAYS_DIVISOR * flt(leave_days)
