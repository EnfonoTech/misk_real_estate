# apps/misk_real_estate/misk_real_estate/wps/custom_leave_application.py
#
# Automatic paid / unpaid split for earned leave (Annual Leave).
#
# When an employee asks for more earned-leave days than their balance, stock
# HRMS refuses the application ("Insufficient leave balance"). Misk instead
# pays whole days from the balance and turns the rest into Leave Without Pay:
#
#   * Draft (Open) -- the split is only previewed in the "Paid / Unpaid
#     Split" fields so HR sees it while approving; dates are left as asked.
#   * Submit (Approved) -- this application is cut down to the paid days and
#     a separate Leave Without Pay application is created and submitted for
#     the remaining dates. Each is then an ordinary Leave Application, so
#     attendance, salary slip LWP, leave balance and gratuity service
#     (end_of_service.py) all work from the standard records.
#   * Cancel -- the linked Leave Without Pay application is cancelled too.
#
# The paid part keeps any holidays that follow its last paid day, so the
# unpaid part starts on the next working day.

import math

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

from hrms.hr.doctype.leave_application.leave_application import (
	LeaveApplication,
	get_leave_balance_on,
	get_number_of_leave_days,
)

SPLIT_FIELDS = (
	"requested_to_date",
	"paid_leave_days",
	"unpaid_leave_days",
	"unpaid_from_date",
	"unpaid_to_date",
)


class CustomLeaveApplication(LeaveApplication):
	def validate_balance_leaves(self):
		split = self.get_paid_unpaid_split()
		if not split:
			for field in SPLIT_FIELDS:
				self.set(field, None)
			return super().validate_balance_leaves()

		self.update(split)
		self.leave_balance = split["balance"]

		if self._action != "submit":
			# preview only: keep the dates as asked, skip the stock balance error
			self.total_leave_days = split["requested_days"]
			frappe.msgprint(
				_(
					"Leave balance is {0} day(s), so {1} day(s) will be paid {2} and {3} day(s) will be Leave Without Pay ({4} to {5}) when this is approved."
				).format(
					frappe.bold(split["balance"]),
					frappe.bold(split["paid_leave_days"]),
					self.leave_type,
					frappe.bold(split["unpaid_leave_days"]),
					frappe.format(split["unpaid_from_date"], "Date"),
					frappe.format(split["unpaid_to_date"], "Date"),
				),
				title=_("Paid / Unpaid Split"),
				indicator="blue",
			)
			return

		# approving: this application keeps only the paid days
		if split["paid_leave_days"]:
			self.to_date = split["paid_to_date"]
		else:
			# nothing left to pay -- the whole application becomes unpaid
			self.leave_type = split["lwp_leave_type"]
			self.paid_leave_days = 0
			self.unpaid_leave_days = 0
			self.unpaid_from_date = self.unpaid_to_date = None
		super().validate_balance_leaves()

	def get_paid_unpaid_split(self):
		if (
			not (self.from_date and self.to_date and self.employee and self.leave_type)
			or self.status == "Rejected"
			or self.get("split_from_leave_application")
			or not frappe.get_cached_value("Leave Type", self.leave_type, "is_earned_leave")
			or frappe.get_cached_value("Leave Type", self.leave_type, "allow_negative")
		):
			return None

		requested_days = get_number_of_leave_days(
			self.employee, self.leave_type, self.from_date, self.to_date, self.half_day, self.half_day_date
		)
		balance = flt(
			get_leave_balance_on(
				self.employee,
				self.leave_type,
				self.from_date,
				self.to_date,
				consider_all_leaves_in_the_allocation_period=True,
				for_consumption=True,
			).get("leave_balance_for_consumption"),
			cint(frappe.db.get_single_value("System Settings", "float_precision")) or 2,
		)
		if requested_days <= balance:
			return None

		if cint(self.half_day):
			frappe.throw(
				_(
					"Leave balance is {0} day(s), less than the {1} day(s) asked for. Remove Half Day so the leave can be split into paid and unpaid days."
				).format(frappe.bold(balance), frappe.bold(requested_days))
			)

		lwp_leave_type = get_lwp_leave_type()
		if not lwp_leave_type:
			return None

		paid_days = math.floor(max(balance, 0))
		paid_to_date = self.get_paid_to_date(paid_days) if paid_days else None
		unpaid_from = add_days(paid_to_date, 1) if paid_to_date else getdate(self.from_date)
		unpaid_days = get_number_of_leave_days(self.employee, lwp_leave_type, unpaid_from, self.to_date)

		return frappe._dict(
			requested_to_date=getdate(self.to_date),
			requested_days=requested_days,
			balance=balance,
			paid_leave_days=paid_days,
			paid_to_date=paid_to_date,
			unpaid_leave_days=unpaid_days,
			unpaid_from_date=unpaid_from,
			unpaid_to_date=getdate(self.to_date),
			lwp_leave_type=lwp_leave_type,
		)

	def get_paid_to_date(self, paid_days):
		"""Last date on which the paid part still counts only `paid_days` --
		i.e. including any holidays straight after the last paid day."""
		date = getdate(self.from_date)
		end = getdate(self.to_date)
		while date < end and (
			get_number_of_leave_days(self.employee, self.leave_type, self.from_date, add_days(date, 1))
			<= paid_days
		):
			date = add_days(date, 1)
		return date

	def on_submit(self):
		super().on_submit()
		if self.get("unpaid_leave_days") and self.get("unpaid_from_date"):
			self.create_unpaid_leave_application()

	def create_unpaid_leave_application(self):
		unpaid = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": self.employee,
				"leave_type": get_lwp_leave_type(),
				"from_date": self.unpaid_from_date,
				"to_date": self.unpaid_to_date,
				"status": "Approved",
				"leave_approver": self.leave_approver,
				"posting_date": self.posting_date,
				"follow_via_email": 0,
				"description": _("Unpaid part of {0} ({1} balance was not enough)").format(
					self.name, self.leave_type
				),
				"split_from_leave_application": self.name,
			}
		)
		unpaid.flags.ignore_permissions = True
		unpaid.insert()
		unpaid.submit()
		self.db_set("unpaid_leave_application", unpaid.name)
		frappe.msgprint(
			_("{0} day(s) Leave Without Pay created as {1}").format(
				frappe.bold(unpaid.total_leave_days), frappe.get_desk_link("Leave Application", unpaid.name)
			),
			indicator="green",
			alert=True,
		)

	def on_cancel(self):
		if self.get("unpaid_leave_application"):
			unpaid = frappe.get_doc("Leave Application", self.get("unpaid_leave_application"))
			if unpaid.docstatus == 1:
				unpaid.flags.ignore_permissions = True
				unpaid.cancel()
		super().on_cancel()


def get_lwp_leave_type():
	lwp_types = frappe.get_all("Leave Type", filters={"is_lwp": 1}, pluck="name", order_by="creation")
	if "Leave Without Pay" in lwp_types:
		return "Leave Without Pay"
	return lwp_types[0] if lwp_types else None
