// apps/misk_real_estate/misk_real_estate/wps/doctype/daily_attendance_tool/daily_attendance_tool.js

frappe.ui.form.on("Daily Attendance Tool", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.company) {
			const company = frappe.defaults.get_user_default("company")
				|| frappe.defaults.get_global_default("company");
			if (company) frm.set_value("company", company);
		}
	},

	refresh(frm) {
		frm.set_query("employee", "employees", () => ({
			filters: { company: frm.doc.company || "" },
		}));

		if (frm.doc.docstatus !== 0) return;

		frm.add_custom_button(__("Get Employees"), () => _get_employees(frm));
		frm.add_custom_button(__("Mark All As Present"), () => _mark_all_present(frm));

		_highlight_missing_project(frm);
	},

	attendance_date(frm) { _highlight_missing_project(frm); },
	employees_add(frm) { _highlight_missing_project(frm); },
	employees_remove(frm) { _highlight_missing_project(frm); },
});

frappe.ui.form.on("Daily Attendance Tool Employee", {
	project(frm) { _highlight_missing_project(frm); },
	shift(frm, cdt, cdn) { _fetch_working_hours(frm, cdt, cdn); },
	overtime_hours(frm, cdt, cdn) { _calc_total_hours(frm, cdt, cdn); },
});

function _get_employees(frm) {
	if (!frm.doc.company || !frm.doc.attendance_date) {
		frappe.msgprint(__("Set Company and Attendance Date first."));
		return;
	}

	const fetch = () => {
		frappe.call({
			method: "misk_real_estate.wps.doctype.daily_attendance_tool.daily_attendance_tool.get_employees",
			args: {
				company: frm.doc.company,
				attendance_date: frm.doc.attendance_date,
				employee_category: frm.doc.employee_category,
				project: frm.doc.project,
				shift: frm.doc.shift,
			},
			freeze: true,
			callback(r) {
				if (!r.message) return;
				frm.clear_table("employees");
				r.message.forEach((row) => {
					const child = frm.add_child("employees");
					Object.assign(child, row);
				});
				frm.refresh_field("employees");
				_highlight_missing_project(frm);
				frappe.show_alert({
					message: __("Loaded {0} employee(s).", [r.message.length]),
					indicator: "green",
				});
			},
		});
	};

	if ((frm.doc.employees || []).length) {
		frappe.confirm(
			__("This will replace the current employee rows and any edits you've made. Continue?"),
			fetch
		);
	} else {
		fetch();
	}
}

function _mark_all_present(frm) {
	(frm.doc.employees || []).forEach((row) => {
		frappe.model.set_value(row.doctype, row.name, "status", "Present");
	});
}

// Working Hours is read-only — always set from the shift's own normal
// hours, never typed by hand. Overtime Hours is the only hours field the
// user edits directly (no longer derived from a "worked hours minus normal"
// formula).
function _fetch_working_hours(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.shift) return;

	frappe.call({
		method: "misk_real_estate.wps.attendance_hooks.get_shift_hours",
		args: { shift: row.shift },
		callback(r) {
			frappe.model.set_value(cdt, cdn, "working_hours", flt(r.message));
			_calc_total_hours(frm, cdt, cdn);
		},
	});
}

function _calc_total_hours(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "total_hours", flt(row.working_hours) + flt(row.overtime_hours));
}

// Rows with no project resolved (no matching Shift Assignment) get a subtle
// highlight so gaps are visible before submitting, not discovered later in a
// report — mirrors the PDC schedule row-styling pattern already used in
// sales_agreement.js.
function _highlight_missing_project(frm) {
	setTimeout(() => {
		const grid = frm.fields_dict.employees && frm.fields_dict.employees.grid;
		if (!grid) return;
		(frm.doc.employees || []).forEach((row) => {
			grid.wrapper
				.find(`.grid-row[data-name="${row.name}"]`)
				.find(".data-row")
				.css("background-color", row.project ? "" : "#fff7e6");
		});
	}, 300);
}
