// apps/misk_real_estate/misk_real_estate/pdc_management/report/pdc_monthly_forecast/pdc_monthly_forecast.js

frappe.query_reports["PDC Monthly Forecast"] = {
	onload: function (report) {
		var today = frappe.datetime.get_today();
		report.set_filter_value("from_date", today);
		report.set_filter_value("to_date", frappe.datetime.add_months(today, 12));
	},
};
