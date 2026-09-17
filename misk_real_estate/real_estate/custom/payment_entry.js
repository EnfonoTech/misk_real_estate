// Payment Entry customisation — Misk Real Estate
// Restrict the Party picker to the Payment Entry's own Company.

frappe.ui.form.on("Payment Entry", {
	// In refresh (not onload) so it can't lose a race with ERPNext's own
	// onload, which ASSIGNS this list rather than appending to it.
	refresh(frm) {
		// Cancelling a Payment Entry must NEVER offer to cancel the Property
		// Booking with it. Frappe spots the booking as a "linked submitted
		// document" only because PDC Schedule.payment_entry — a CHILD ROW of
		// the booking — points here; the booking itself is not downstream of
		// this payment. Accepting that offer would take down the whole booking
		// (units, schedule, invoices) to release one cheque, and it can't even
		// succeed: the booking's own link check then blocks on this very
		// Payment Entry's property_booking field. Appended, not assigned —
		// ERPNext sets its own list in onload and we must not clobber it.
		frm.ignore_doctypes_on_cancel_all = frm.ignore_doctypes_on_cancel_all || [];
		if (!frm.ignore_doctypes_on_cancel_all.includes("Property Booking")) {
			frm.ignore_doctypes_on_cancel_all.push("Property Booking");
		}
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
