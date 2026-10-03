// apps/misk_real_estate/misk_real_estate/wps/doctype/leave_salary/leave_salary.js

frappe.ui.form.on("Leave Salary", {
	setup(frm) {
		// cancelling a Leave Salary cancels its own Additional Salary and only
		// unlinks the Leave Application -- never offer to cancel the leave too
		frm.ignore_doctypes_on_cancel_all = ["Leave Application", "Additional Salary"];
		frm.set_query("leave_application", () => ({
			filters: { employee: frm.doc.employee, status: "Approved", docstatus: 1 },
		}));
	},
});
