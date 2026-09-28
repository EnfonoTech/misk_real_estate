import frappe

# One-time starting setup for Misk gratuity + leave salary (see
# wps/end_of_service.py). Created by a patch rather than fixtures so HR can
# change them later without the next migrate overwriting that. Skips anything
# that already exists.


def execute():
	create_annual_leave_type()
	create_gratuity_rule()


def create_annual_leave_type():
	if frappe.db.exists("Leave Type", "Annual Leave"):
		return

	frappe.get_doc(
		{
			"doctype": "Leave Type",
			"leave_type_name": "Annual Leave",
			# 30/yr from the Leave Policy -> 2.5 credited at each month-end
			"is_earned_leave": 1,
			"earned_leave_frequency": "Monthly",
			"allocate_on_day": "Last Day",
			"rounding": "",
			# the settlement sheet's 35-day balance is more than one year's 30
			"is_carry_forward": 1,
			"allow_negative": 0,
			"allow_encashment": 1,
			"earning_component": "Leave Encashment"
			if frappe.db.exists("Salary Component", "Leave Encashment")
			else None,
		}
	).insert(ignore_permissions=True)


def create_gratuity_rule():
	if frappe.db.exists("Gratuity Rule", "Misk Gratuity Rule") or not frappe.db.exists(
		"Salary Component", "Basic"
	):
		return

	rule = frappe.new_doc("Gratuity Rule")
	rule.name = "Misk Gratuity Rule"
	rule.calculate_gratuity_amount_based_on = "Current Slab"
	# keeps the fraction (5.41 years), rounded to 2 decimals by the
	# Gratuity-current_work_experience-precision Property Setter
	rule.work_experience_calculation_function = "Take Exact Completed Years"
	rule.total_working_days_per_year = 365
	rule.minimum_year_for_gratuity = 0
	rule.append("applicable_earnings_component", {"salary_component": "Basic"})
	# one Basic per year of service, no slabs or cap
	rule.append("gratuity_rule_slabs", {"from_year": 0, "to_year": 0, "fraction_of_applicable_earnings": 1})
	rule.insert(ignore_permissions=True)
