# apps/misk_real_estate/misk_real_estate/wps/custom_gratuity.py
#
# Misk service days for gratuity: DOJ..Relieving Date counted inclusively,
# minus approved unpaid leave (see end_of_service.py). Stock HRMS counts the
# range exclusively and subtracts either LWP attendance or Absent attendance
# depending on Payroll Settings; Misk only subtracts approved unpaid leave,
# with half days as 0.5.
#
# Everything else (the rule's 365 days/year, slabs, Basic from the last
# salary slip) stays stock HRMS, driven by the Gratuity Rule.

from hrms.payroll.doctype.gratuity.gratuity import Gratuity

from misk_real_estate.wps.end_of_service import get_gratuity_service_days


class CustomGratuity(Gratuity):
	def get_total_working_days(self) -> float:
		return get_gratuity_service_days(self.employee)
