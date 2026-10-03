// apps/misk_real_estate/misk_real_estate/wps/custom/leave_application.js

// Actual Rejoining Date is HR's to set (enforced server-side too, see
// custom_leave_application.py) -- read-only for everyone else.
const MISK_REJOINING_ROLES = ["HR Manager", "HR User", "System Manager"];

frappe.ui.form.on("Leave Application", {
	refresh(frm) {
		const is_hr = MISK_REJOINING_ROLES.some((role) => frappe.user.has_role(role));
		frm.set_df_property("custom_actual_rejoining_date", "read_only", is_hr ? 0 : 1);
	},
});
