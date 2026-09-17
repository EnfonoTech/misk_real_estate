// apps/misk_real_estate/misk_real_estate/public/js/voucher_common.js
//
// Shared form behaviour for the Voucher Entry screens (Cash/Bank Payment,
// Cash/Bank Receipt). Loaded app-wide via app_include_js in hooks.py so it is
// always defined before any of the per-doctype scripts run.

frappe.provide("misk.voucher");

misk.voucher.setup = function (doctype, opts) {
	const control_field = opts.control_field;      // "cash_account" | "bank_account"
	const control_account_type = opts.account_type; // "Cash" | "Bank"

	frappe.ui.form.on(doctype, {
		onload(frm) {
			if (frm.is_new() && !frm.doc.company) {
				const company = frappe.defaults.get_user_default("company")
					|| frappe.defaults.get_global_default("company");
				if (company) frm.set_value("company", company);
			}
			// Frappe's Amend action copies no_copy fields too (unlike a plain
			// Duplicate) — journal_entry would otherwise still point at the
			// old, now-cancelled Journal Entry on the fresh draft, tripping
			// "Cannot link cancelled document" on save.
			if (frm.is_new() && frm.doc.amended_from && frm.doc.journal_entry) {
				frm.set_value("journal_entry", "");
			}
		},

		refresh(frm) {
			const company = frm.doc.company || "";

			frm.set_query(control_field, () => ({
				filters: { account_type: control_account_type, is_group: 0, company },
			}));
			frm.set_query("cost_center", () => ({ filters: { company, is_group: 0 } }));
			frm.set_query("project", () => ({ filters: { company } }));

			// Receivable/Payable accounts are excluded deliberately: ERPNext's
			// Journal Entry hard-throws on an AR/AP line with no party, and
			// these vouchers carry no party fields. A filtered picker beats a
			// confusing error at submit time.
			frm.set_query("account", "lines", () => ({
				filters: [
					["company", "=", company],
					["is_group", "=", 0],
					["account_type", "not in", ["Receivable", "Payable"]],
				],
			}));
			frm.set_query("cost_center", "lines", () => ({ filters: { company, is_group: 0 } }));
			frm.set_query("project", "lines", () => ({ filters: { company } }));

			if (frm.doc.journal_entry) {
				frm.add_custom_button(__("Journal Entry"), () => {
					frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry);
				}, __("View"));
			}
		},

		// Header Cost Center/Project are the default for every line — push
		// into rows that don't already have their own value. Rows the user has
		// explicitly overridden are left untouched.
		cost_center(frm) { misk.voucher.fill_blank(frm, "cost_center"); },
		project(frm) { misk.voucher.fill_blank(frm, "project"); },
	});

	frappe.ui.form.on("Voucher Line", {
		amount(frm) { misk.voucher.recalc_total(frm); },
		lines_remove(frm) { misk.voucher.recalc_total(frm); },

		// New rows default to the header's own Cost Center/Project — still
		// overridable per row.
		lines_add(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (!row.cost_center && frm.doc.cost_center) {
				frappe.model.set_value(cdt, cdn, "cost_center", frm.doc.cost_center);
			}
			if (!row.project && frm.doc.project) {
				frappe.model.set_value(cdt, cdn, "project", frm.doc.project);
			}
		},
	});
};

misk.voucher.recalc_total = function (frm) {
	const total = (frm.doc.lines || []).reduce((sum, row) => sum + flt(row.amount), 0);
	frm.set_value("total_amount", flt(total.toFixed(3)));
};

misk.voucher.fill_blank = function (frm, fieldname) {
	const value = frm.doc[fieldname];
	if (!value) return;
	(frm.doc.lines || []).forEach((row) => {
		if (!row[fieldname]) frappe.model.set_value(row.doctype, row.name, fieldname, value);
	});
};
