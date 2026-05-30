// apps/misk_real_estate/misk_real_estate/pdc_management/doctype/pdc_batch/pdc_batch.js

frappe.ui.form.on("PDC Batch", {

	// ── Refresh — build action buttons based on state ─────────────────────────
	refresh(frm) {
		const batch_status = frm.doc.batch_status;

		// Status badge
		const colors = {
			"Draft":        "orange",
			"Sent to Bank": "blue",
			"Completed":    "green",
		};
		frm.page.set_indicator(batch_status, colors[batch_status] || "grey");

		if (frm.doc.docstatus !== 1) return;

		// Mark Sent to Bank — only when submitted and still Draft status
		if (batch_status === "Draft") {
			frm.add_custom_button(__("Mark Sent to Bank"), () => {
				frappe.confirm(
					__("Send {0} cheques to bank? This will mark all entries as Deposited.", [
						frm.doc.total_cheques || (frm.doc.items || []).length,
					]),
					() => {
						frappe.call({
							method: "misk_real_estate.pdc_management.doctype.pdc_batch.pdc_batch.mark_sent_to_bank",
							args: { batch_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Updating PDC Entries..."),
							callback(r) {
								if (!r.exc) {
									frappe.show_alert({
										message: __("Batch marked Sent to Bank. All entries set to Deposited."),
										indicator: "blue",
									});
									frm.reload_doc();
								}
							},
						});
					}
				);
			}, __("Actions"));
		}

		// View all PDC Entries in this batch
		frm.add_custom_button(__("PDC Entries"), () => {
			frappe.set_route("List", "PDC Entry", { batch: frm.doc.name });
		}, __("View"));
	},
});
