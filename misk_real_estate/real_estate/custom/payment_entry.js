// Payment Entry customisation — Misk Real Estate
// Restrict the Party picker to the Payment Entry's own Company.

frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		_set_party_query(frm);
	},

	party_type(frm) {
		_set_party_query(frm);
	},
});

// party is a Dynamic Link (Customer or Supplier depending on party_type) — both
// now carry their own company field, so the filter applies to either target.
function _set_party_query(frm) {
	frm.set_query("party", () => ({
		filters: { company: frm.doc.company || "" },
	}));
}
