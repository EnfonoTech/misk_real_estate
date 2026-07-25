// apps/misk_real_estate/misk_real_estate/wps/report/wps_report/wps_report.js

frappe.query_reports["WPS Report"] = {
	onload: function (report) {
		// Default to the full current month, not "today" — a payroll period's
		// end_date is the last day of the month even while that month is still
		// in progress, so a "today" upper bound would wrongly exclude it.
		report.set_filter_value("from_date", frappe.datetime.month_start());
		report.set_filter_value("to_date", frappe.datetime.month_end());

		const company = frappe.defaults.get_user_default("company")
			|| frappe.defaults.get_global_default("company");
		if (company) report.set_filter_value("wps_company", company);
	},
};
