import frappe

# One-time starting setup for Misk Leave Salary (see wps/leave_salary.py): the
# "Leave Salary" earning component its Additional Salary pays through.
# Created by a patch rather than fixtures so HR can change it later (e.g.
# taxable or not, accounts) without the next migrate overwriting that. Skips
# it if it already exists.


def execute():
	if frappe.db.exists("Salary Component", "Leave Salary"):
		return

	component = frappe.get_doc(
		{
			"doctype": "Salary Component",
			"salary_component": "Leave Salary",
			"salary_component_abbr": "LS",
			"type": "Earning",
			"description": "Gross Salary / 30 x eligible leave days, paid when a Leave Salary type leave is approved",
			# a fixed amount from the Leave Salary document, not prorated
			"depends_on_payment_days": 0,
			"is_tax_applicable": 0,
			"remove_if_zero_valued": 1,
		}
	)
	# same payroll accounts as Basic, where those are set up
	if frappe.db.exists("Salary Component", "Basic"):
		for row in frappe.get_doc("Salary Component", "Basic").accounts:
			component.append("accounts", {"company": row.company, "account": row.account})

	component.insert(ignore_permissions=True)
