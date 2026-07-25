// apps/misk_real_estate/misk_real_estate/wps/report/project_attendance_and_overtime_report/project_attendance_and_overtime_report.js

frappe.query_reports["Project Attendance and Overtime Report"] = {
	onload: function (report) {
		report.set_filter_value("from_date", frappe.datetime.month_start());
		report.set_filter_value("to_date", frappe.datetime.month_end());

		const company = frappe.defaults.get_user_default("company")
			|| frappe.defaults.get_global_default("company");
		if (company) report.set_filter_value("company", company);
	},
};
