// apps/misk_real_estate/misk_real_estate/real_estate/doctype/sales_agreement/sales_agreement.js

frappe.ui.form.on("Sales Agreement", {
	refresh(frm) {
		if (frm.is_new()) return;

		// Submitting the document IS generating the contract — no custom
		// button needed, the standard Submit action handles it. Staff use
		// the regular Print button (Sales Agreement (Arabic) format) to view
		// or print it on demand.

		if (frm.doc.docstatus === 1 && frm.doc.status === "Generated") {
			frm.add_custom_button(__("Mark Signed"), () => {
				frappe.call({
					method: "misk_real_estate.real_estate.doctype.sales_agreement.sales_agreement.mark_signed",
					args: { sales_agreement_name: frm.doc.name },
					freeze: true,
					callback(r) { if (!r.exc) frm.reload_doc(); },
				});
			}, __("Actions"));
		}

		if (frm.doc.docstatus === 1 && frm.doc.status === "Signed") {
			frm.add_custom_button(__("Mark Registered"), () => {
				frappe.call({
					method: "misk_real_estate.real_estate.doctype.sales_agreement.sales_agreement.mark_registered",
					args: { sales_agreement_name: frm.doc.name },
					freeze: true,
					callback(r) { if (!r.exc) frm.reload_doc(); },
				});
			}, __("Actions"));
		}

		frm.add_custom_button(__("Property Booking"), () => {
			frappe.set_route("Form", "Property Booking", frm.doc.property_booking);
		}, __("View"));

		const colors = { "Draft": "gray", "Generated": "blue", "Signed": "orange", "Registered": "green", "Cancelled": "red" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "gray");

		_style_pdc_schedule(frm);
	},
});

// ── PDC Schedule visual grouping (mirrors Property Booking) ─────────────────
function _style_pdc_schedule(frm) {
	const colors = {
		"Booking Amount":         "#dbeafe",
		"Down Payment":           "#dcfce7",
		"Installment":            "#ffffff",
		"Owners Association Fee": "#fef9c3",
	};
	setTimeout(() => {
		const grid = frm.fields_dict.pdc_schedule && frm.fields_dict.pdc_schedule.grid;
		if (!grid) return;
		const rows = frm.doc.pdc_schedule || [];

		const rowMap = {};
		rows.forEach(r => { rowMap[r.name] = r; });

		grid.wrapper.find(".grid-row[data-name]").each(function() {
			const row = rowMap[$(this).data("name")];
			if (!row) return;
			$(this).find(".data-row").css("background-color", colors[row.installment_type] || "#fff");
		});

		let prev_type = null;
		rows.forEach(row => {
			if (prev_type !== null && row.installment_type !== prev_type) {
				grid.wrapper.find(`.grid-row[data-name="${row.name}"]`)
					.find(".data-row").css("border-top", "2px solid #d1d5db");
			}
			prev_type = row.installment_type;
		});
	}, 400);
}
