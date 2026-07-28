// apps/misk_real_estate/misk_real_estate/real_estate/report/building_status_report/building_status_report.js

frappe.query_reports["Building Status Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
		{
			fieldname: "building",
			label: __("Building"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "unit_status",
			label: __("Unit Status"),
			fieldtype: "Select",
			options: "\nAvailable\nBooked\nSold\nReserved\nUnder Maintenance",
		},
	],
};
