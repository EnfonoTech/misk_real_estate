// Populates the Conditions grid's "Field" column with a dropdown of the
// chosen Document Type's fieldnames — same approach core Frappe uses for
// Document Naming Rule (frappe/core/doctype/document_naming_rule/document_naming_rule.js).
frappe.ui.form.on("Posting Date Naming Rule", {
	refresh: (frm) => {
		frm.trigger("document_type");
	},
	document_type: (frm) => {
		if (!frm.doc.document_type) return;
		frappe.model.with_doctype(frm.doc.document_type, () => {
			let fieldnames = frappe
				.get_meta(frm.doc.document_type)
				.fields.filter((d) => frappe.model.no_value_type.indexOf(d.fieldtype) === -1)
				.map((d) => ({ label: `${d.label} (${d.fieldname})`, value: d.fieldname }));
			frm.fields_dict.conditions.grid.update_docfield_property("field", "options", fieldnames);
		});
	},
});
