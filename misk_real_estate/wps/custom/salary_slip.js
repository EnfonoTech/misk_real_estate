// apps/misk_real_estate/misk_real_estate/wps/custom/salary_slip.js

frappe.ui.form.on("Salary Slip", {
	employee(frm) { _preview_attendance_from_date(frm); },
	start_date(frm) { _preview_attendance_from_date(frm); },
});

// Live preview of Attendance From Date as soon as Employee and the period
// are known — same lookback custom_salary_slip.py uses at save time (day
// after the previous submitted slip's own cutoff, or this slip's own start
// date if there isn't one). Never overwrites a value already there, whether
// that's a prior auto-fill or a manual correction.
function _preview_attendance_from_date(frm) {
	if (frm.doc.custom_attendance_from_date || !frm.doc.employee || !frm.doc.start_date) return;

	frappe.call({
		method: "misk_real_estate.wps.custom_salary_slip.preview_attendance_from_date",
		args: {
			employee: frm.doc.employee,
			start_date: frm.doc.start_date,
			company: frm.doc.company,
		},
		callback(r) {
			if (r.message) frm.set_value("custom_attendance_from_date", r.message);
		},
	});
}
