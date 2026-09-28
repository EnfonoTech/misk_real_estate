# apps/misk_real_estate/misk_real_estate/wps/custom_leave_encashment.py
#
# Misk leave salary = Gross / 30 x encashment days, Gross being the
# employee's own full-month gross (see end_of_service.get_monthly_gross).
# Stock HRMS uses one fixed "Leave Encashment Amount Per Day" per Salary
# Structure, which can't follow each employee's salary.
#
# The balance paid is the employee's whole leave balance on the encashment
# date, carried-forward days included (the settlement sheet pays 35 days, more
# than one year's 30) -- stock HRMS leaves carried-forward days out.

from frappe.utils import flt

from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
from hrms.hr.doctype.leave_encashment.leave_encashment import LeaveEncashment

from misk_real_estate.wps.end_of_service import get_leave_salary


class CustomLeaveEncashment(LeaveEncashment):
	def set_leave_balance(self):
		# still sets leave_allocation, and throws when there is none
		super().set_leave_balance()
		self.leave_balance = get_leave_balance_on(self.employee, self.leave_type, self.encashment_date)

	def set_encashment_amount(self):
		self.encashment_amount = (
			flt(get_leave_salary(self.employee, self.encashment_date, self.encashment_days), self.precision("encashment_amount"))
			if flt(self.encashment_days) > 0
			else 0
		)
