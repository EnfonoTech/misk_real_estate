// apps/misk_real_estate/misk_real_estate/expense_entry/doctype/expense_entry/expense_entry.js

frappe.ui.form.on("Expense Entry", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.company) {
			const company = frappe.defaults.get_user_default("company")
				|| frappe.defaults.get_global_default("company");
			if (company) frm.set_value("company", company);
		}
		// Frappe's Amend action copies no_copy fields too (unlike a plain
		// Duplicate) — journal_entry would otherwise still point at the old,
		// now-cancelled Journal Entry on the fresh draft, tripping "Cannot
		// link cancelled document" on save.
		if (frm.is_new() && frm.doc.amended_from && frm.doc.journal_entry) {
			frm.set_value("journal_entry", "");
		}
	},

	refresh(frm) {
		// Convenience default — the backend accepts any account regardless
		// of this filter, so it can be widened later without a code change.
		frm.set_query("payable_account", () => ({
			filters: { root_type: "Liability", is_group: 0, company: frm.doc.company || "" },
		}));
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company || "", is_group: 0 } }));
		frm.set_query("project", () => ({ filters: { company: frm.doc.company || "" } }));
		frm.set_query("expense_account", "expenses", () => ({
			filters: { root_type: "Expense", is_group: 0, company: frm.doc.company || "" },
		}));
		frm.set_query("cost_center", "expenses", () => ({
			filters: { company: frm.doc.company || "", is_group: 0 },
		}));
		frm.set_query("project", "expenses", () => ({
			filters: { company: frm.doc.company || "" },
		}));
	},

	// Header Cost Center/Project are the default for every expense row —
	// push into rows that don't already have their own value. Rows the user
	// has explicitly overridden are left untouched.
	cost_center(frm) { _fill_blank_expense_field(frm, "cost_center"); },
	project(frm) { _fill_blank_expense_field(frm, "project"); },
});

frappe.ui.form.on("Expense", {
	amount(frm) { _recalc_total(frm); },
	expenses_remove(frm) { _recalc_total(frm); },

	// New rows default to the header's own Cost Center/Project — still
	// overridable per row.
	expenses_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.cost_center && frm.doc.cost_center) frappe.model.set_value(cdt, cdn, "cost_center", frm.doc.cost_center);
		if (!row.project && frm.doc.project) frappe.model.set_value(cdt, cdn, "project", frm.doc.project);
	},
});

function _recalc_total(frm) {
	const total = (frm.doc.expenses || []).reduce((sum, row) => sum + flt(row.amount), 0);
	frm.set_value("total_amount", flt(total.toFixed(3)));
}

function _fill_blank_expense_field(frm, fieldname) {
	const value = frm.doc[fieldname];
	if (!value) return;
	(frm.doc.expenses || []).forEach((row) => {
		if (!row[fieldname]) frappe.model.set_value(row.doctype, row.name, fieldname, value);
	});
}
