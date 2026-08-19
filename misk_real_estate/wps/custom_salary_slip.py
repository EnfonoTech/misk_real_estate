# apps/misk_real_estate/misk_real_estate/wps/custom_salary_slip.py
#
# Misk pays on the 25th for the full calendar month (1st -> month-end), but
# only has real attendance/leave data up to an "Attendance Cutoff Date" that
# HR enters on the Payroll Entry each cycle (it moves around, e.g. 19th one
# month, 21st the next). The trailing days from the cutoff to month-end are
# effectively paid in advance.
#
# Reconciliation is automatic and needs no extra bookkeeping: next cycle's
# window starts the day after *this* cycle's cutoff, so any leave that lands
# in this month's advance tail gets checked (and deducted if unpaid) the
# following month, once it has actually happened.
#
# custom_attendance_from_date is where that "day after" gets written -- a
# real, visible field on the slip (auto-filled once, from the previous
# submitted slip's own cutoff), not just an internal calculation, so HR can
# see and correct it before submitting if the lookup ever picks up the wrong
# prior slip.
#
# Only the leave-lookup window is substituted here. total_working_days and
# the pre-leave payment-days baseline are left untouched (still computed by
# HRMS from the real start_date/end_date), so the slip keeps reporting as a
# normal full calendar month everywhere else (Salary Register, etc).
#
# Applies only when custom_attendance_cutoff_date is actually set (Payroll
# Entry or slip); otherwise this is a no-op and stock HRMS behaviour applies.

import frappe
from frappe.utils import add_days, cint, date_diff, getdate
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip


class CustomSalarySlip(SalarySlip):
	def calculate_lwp_or_ppl_based_on_leave_application(
		self, holidays, working_days_list, daily_wages_fraction_for_half_day
	):
		window_start, window_end = self._get_attendance_cutoff_window()
		if not window_start:
			return super().calculate_lwp_or_ppl_based_on_leave_application(
				holidays, working_days_list, daily_wages_fraction_for_half_day
			)

		window_holidays = self.get_holidays_for_employee(window_start, window_end)
		window_days = [
			add_days(getdate(window_start), d) for d in range(date_diff(window_end, window_start) + 1)
		]

		include_holidays = cint(
			frappe.db.get_single_value("Payroll Settings", "include_holidays_in_total_working_days")
		)
		if not include_holidays:
			window_days = [d for d in window_days if d not in window_holidays]

		# calculate_lwp_or_ppl_based_on_leave_application (parent) reads
		# self.start_date/self.end_date internally for the leave lookup —
		# swap them to our window for just this call, then restore. The
		# method itself has no other side effects on self.
		original_start, original_end = self.start_date, self.end_date
		try:
			self.start_date, self.end_date = window_start, window_end
			return super().calculate_lwp_or_ppl_based_on_leave_application(
				window_holidays, window_days, daily_wages_fraction_for_half_day
			)
		finally:
			self.start_date, self.end_date = original_start, original_end

	def _get_attendance_cutoff_window(self):
		"""(window_start, window_end) for the leave lookup, or (None, None)
		to fall back to stock (full calendar-month) behaviour.

		window_end   = this slip's own cutoff date (custom_attendance_cutoff_date),
		               copied down from its Payroll Entry the first time this runs.
		window_start = custom_attendance_from_date. Auto-filled, once, the first
		               time this runs: day after the *previous* submitted slip's
		               own cutoff date for this same employee/company —
		               wherever the last cycle actually left off, never a fixed
		               day — or this slip's own start_date when there's no
		               earlier slip to look back on (first slip ever, or first
		               one processed after this scheme was set up).

		Both dates are real, visible fields on the slip (not just an internal
		calculation) so HR can see and, if the lookup ever needs correcting,
		override what period was actually checked before submitting. Once set
		they're left alone — re-saving a slip won't silently recompute them.
		"""
		if not self.custom_attendance_cutoff_date and self.payroll_entry:
			self.custom_attendance_cutoff_date = frappe.db.get_value(
				"Payroll Entry", self.payroll_entry, "custom_attendance_cutoff_date"
			)

		window_end = self.custom_attendance_cutoff_date
		if not window_end:
			return None, None

		if not self.custom_attendance_from_date:
			prev_cutoff = _find_previous_cutoff(self.employee, self.company, self.start_date)
			self.custom_attendance_from_date = (
				add_days(getdate(prev_cutoff), 1) if prev_cutoff else self.start_date
			)

		window_start = self.custom_attendance_from_date

		if getdate(window_start) > getdate(window_end):
			frappe.log_error(
				title="Salary Slip attendance cutoff window invalid",
				message=(
					f"Salary Slip {self.name or '(new)'} for {self.employee}: computed window "
					f"{window_start} -> {window_end} has start after end. Falling back to the "
					"full calendar-month attendance check for this slip."
				),
			)
			return None, None

		return window_start, window_end


def _find_previous_cutoff(employee, company, start_date):
	"""The submitted Salary Slip cutoff to chain from: the most recent
	earlier slip for this employee/company, or None if there isn't one.
	Shared by the real save-time calculation above and the live client-side
	preview below, so the two can never disagree."""
	return frappe.db.get_value(
		"Salary Slip",
		{
			"employee": employee,
			"company": company,
			"docstatus": 1,
			"start_date": ["<", start_date],
		},
		"custom_attendance_cutoff_date",
		order_by="start_date desc",
	)


@frappe.whitelist()
def preview_attendance_from_date(employee, start_date, company=None):
	"""Live client-side preview of what custom_attendance_from_date would be
	computed as, before the slip is even saved — called from the Salary Slip
	form as soon as Employee or the period is set."""
	if not employee or not start_date:
		return None

	prev_cutoff = _find_previous_cutoff(employee, company, start_date)
	return add_days(getdate(prev_cutoff), 1) if prev_cutoff else getdate(start_date)
