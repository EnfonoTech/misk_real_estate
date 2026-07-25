// apps/misk_real_estate/misk_real_estate/wps/custom/attendance.js

frappe.ui.form.on("Attendance", {
	employee(frm) { _fetch_shift_assignment(frm); },
	attendance_date(frm) { _fetch_shift_assignment(frm); },
	shift(frm) { _calc_overtime(frm); },
	working_hours(frm) { _calc_overtime(frm); },
});

// Fills Project and Shift from the employee's active Shift Assignment for
// this date, whichever of the two is still blank — never overrides a
// manually-chosen value.
function _fetch_shift_assignment(frm) {
	if ((frm.doc.project && frm.doc.shift) || !frm.doc.employee || !frm.doc.attendance_date) return;

	frappe.call({
		method: "misk_real_estate.wps.attendance_hooks.get_shift_assignment_details",
		args: { employee: frm.doc.employee, attendance_date: frm.doc.attendance_date },
		callback(r) {
			if (!r.message) return;
			if (!frm.doc.project && r.message.project) frm.set_value("project", r.message.project);
			if (!frm.doc.shift && r.message.shift_type) frm.set_value("shift", r.message.shift_type);
		},
	});
}

// Defaults Working Hours to the shift's own normal hours (only if still
// blank), then suggests overtime_hours = max(0, worked hours - normal
// hours). Nothing re-runs this unless Shift or Working Hours changes again,
// so a manual edit to either field afterward is never overwritten.
function _calc_overtime(frm) {
	if (!frm.doc.shift) return;

	frappe.call({
		method: "misk_real_estate.wps.attendance_hooks.get_shift_hours",
		args: { shift: frm.doc.shift },
		callback(r) {
			const normal_hours = flt(r.message);
			if (!frm.doc.working_hours) frm.set_value("working_hours", normal_hours);

			const overtime = Math.max(0, flt(frm.doc.working_hours) - normal_hours);
			frm.set_value("overtime_hours", overtime);
		},
	});
}
