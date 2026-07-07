// apps/misk_real_estate/misk_real_estate/real_estate/doctype/sales_agreement/sales_agreement.js

frappe.ui.form.on("Sales Agreement", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Generate Contract"), () => {
				frappe.confirm(
					__("Render the contract PDF from the {0} print format and attach it?", [__("Sales Agreement (Arabic)")]),
					() => {
						frappe.call({
							method: "misk_real_estate.real_estate.doctype.sales_agreement.sales_agreement.mark_generated",
							args: { sales_agreement_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Generating contract..."),
							callback(r) { if (!r.exc) frm.reload_doc(); },
						});
					}
				);
			}, __("Actions"));
		}

		if (frm.doc.status === "Generated") {
			frm.add_custom_button(__("Mark Signed"), () => {
				frappe.call({
					method: "misk_real_estate.real_estate.doctype.sales_agreement.sales_agreement.mark_signed",
					args: { sales_agreement_name: frm.doc.name },
					freeze: true,
					callback(r) { if (!r.exc) frm.reload_doc(); },
				});
			}, __("Actions"));
		}

		if (frm.doc.status === "Signed") {
			frm.add_custom_button(__("Mark Registered"), () => {
				frappe.call({
					method: "misk_real_estate.real_estate.doctype.sales_agreement.sales_agreement.mark_registered",
					args: { sales_agreement_name: frm.doc.name },
					freeze: true,
					callback(r) { if (!r.exc) frm.reload_doc(); },
				});
			}, __("Actions"));
		}

		if (frm.doc.contract_pdf) {
			frm.add_custom_button(__("Open Contract PDF"), () => {
				window.open(frm.doc.contract_pdf);
			}, __("View"));
		}

		frm.add_custom_button(__("Property Booking"), () => {
			frappe.set_route("Form", "Property Booking", frm.doc.property_booking);
		}, __("View"));

		const colors = { "Draft": "gray", "Generated": "blue", "Signed": "orange", "Registered": "green" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "gray");
	},
});
