// apps/misk_real_estate/misk_real_estate/pdc_management/doctype/pdc_entry/pdc_entry.js

frappe.ui.form.on("PDC Entry", {

	// ── On load — set defaults for new docs ────────────────────────────────────
	onload(frm) {
		if (frm.is_new()) {
			if (frm.doc.company && !frm.doc.bank_account) _fetch_bank_account(frm);
			if (frm.doc.customer) _fetch_currency(frm);
		}
	},

	company(frm) {
		if (!frm.doc.bank_account) _fetch_bank_account(frm);
	},

	customer(frm) {
		_fetch_currency(frm);
	},

	// ── Refresh — build action buttons based on status ─────────────────────────
	refresh(frm) {
		const status = frm.doc.status;

		// Status badge
		const colors = {
			"Pending":    "orange",
			"In Batch":   "blue",
			"Deposited":  "purple",
			"Cleared":    "green",
			"Bounced":    "red",
		};
		frm.page.set_indicator(status, colors[status] || "grey");

		// Only action buttons when not submitted/cancelled through docstatus
		// PDC Entry is not a submittable doctype — use status field directly

		// Mark Cleared — available when Deposited or In Batch, GL not yet posted
		if (["Deposited", "In Batch"].includes(status) && !frm.doc.gl_posted) {
			frm.add_custom_button(__("Mark Cleared"), () => {
				_confirm_clearance(frm);
			}, __("Actions"));
		}

		// Post GL / Create Payment Entry — status already Cleared but PE was never created
		if (status === "Cleared" && !frm.doc.gl_posted) {
			frm.add_custom_button(__("Post GL Entry"), () => {
				_confirm_clearance(frm);
			}, __("Actions"));
		}

		// Mark Bounced — available when Deposited or In Batch
		if (["Deposited", "In Batch"].includes(status)) {
			frm.add_custom_button(__("Mark Bounced"), () => {
				_confirm_bounced(frm);
			}, __("Actions"));
		}

		// Record Manual Payment — customer cancels PDC and pays by cash/transfer instead
		if (["Pending", "Deposited", "In Batch"].includes(status) && frm.doc.sales_invoice) {
			frm.add_custom_button(__("Record Manual Payment"), () => {
				_record_manual_payment(frm);
			}, __("Actions"));
		}

		// View linked Payment Entry
		if (frm.doc.payment_entry) {
			frm.add_custom_button(__("Payment Entry"), () => {
				frappe.set_route("Form", "Payment Entry", frm.doc.payment_entry);
			}, __("View"));
		}

		// View linked Sales Invoice
		if (frm.doc.sales_invoice) {
			frm.add_custom_button(__("Sales Invoice"), () => {
				frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice);
			}, __("View"));
		}

		// View parent booking
		if (frm.doc.booking) {
			frm.add_custom_button(__("Property Booking"), () => {
				frappe.set_route("Form", "Property Booking", frm.doc.booking);
			}, __("View"));
		}

		// View linked batch
		if (frm.doc.batch) {
			frm.add_custom_button(__("PDC Batch"), () => {
				frappe.set_route("Form", "PDC Batch", frm.doc.batch);
			}, __("View"));
		}
	},
});


// ── Field fetch helpers ───────────────────────────────────────────────────────

function _fetch_bank_account(frm) {
	if (!frm.doc.company) return;
	frappe.db.get_value("Company", frm.doc.company, "default_bank_account", (r) => {
		if (r && r.default_bank_account) {
			frm.set_value("bank_account", r.default_bank_account);
		}
	});
}

function _fetch_currency(frm) {
	if (!frm.doc.customer) return;
	frappe.db.get_value("Customer", frm.doc.customer, "default_currency", (r) => {
		frm.set_value("currency", (r && r.default_currency) || "OMR");
	});
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function _confirm_clearance(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Confirm Cheque Clearance"),
		fields: [
			{
				fieldname: "cleared_date",
				fieldtype: "Date",
				label: __("Clearance Date"),
				default: frappe.datetime.get_today(),
				reqd: 1,
			},
		],
		primary_action_label: __("Mark Cleared"),
		primary_action(values) {
			d.hide();
			frappe.call({
				method: "misk_real_estate.pdc_management.doctype.pdc_entry.pdc_entry.mark_cleared",
				args: {
					pdc_entry_name: frm.doc.name,
					cleared_date: values.cleared_date,
				},
				freeze: true,
				freeze_message: __("Posting GL entries..."),
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({
							message: __("Cleared. Payment Entry: {0}", [r.message]),
							indicator: "green",
						});
						frm.reload_doc();
					}
				},
			});
		},
	});
	d.show();
}

function _record_manual_payment(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Record Manual Payment"),
		fields: [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: `<div class="alert alert-warning" style="margin-bottom:10px">
					<b>${__("Cheque {0} will be cancelled.", [frm.doc.cheque_no])}</b><br>
					${__("A Payment Entry will be created against Sales Invoice {0}.", [frm.doc.sales_invoice])}
				</div>`,
			},
			{
				fieldname: "mode_of_payment",
				fieldtype: "Link",
				label: __("Mode of Payment"),
				options: "Mode of Payment",
				reqd: 1,
			},
			{
				fieldname: "payment_date",
				fieldtype: "Date",
				label: __("Payment Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount (OMR)"),
				reqd: 1,
				default: frm.doc.amount,
			},
			{
				fieldname: "notes",
				fieldtype: "Small Text",
				label: __("Notes"),
				default: __("Customer cancelled PDC cheque {0} and paid manually.", [frm.doc.cheque_no]),
			},
		],
		primary_action_label: __("Create Payment Entry & Cancel PDC"),
		primary_action(values) {
			d.hide();
			frappe.call({
				method: "misk_real_estate.pdc_management.doctype.pdc_entry.pdc_entry.record_manual_payment",
				args: {
					pdc_entry_name: frm.doc.name,
					mode_of_payment: values.mode_of_payment,
					payment_date: values.payment_date,
					amount: values.amount,
					notes: values.notes || "",
				},
				freeze: true,
				freeze_message: __("Creating Payment Entry..."),
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({
							message: __("Payment Entry {0} created. PDC cancelled.", [r.message]),
							indicator: "green",
						});
						frm.reload_doc();
					}
				},
			});
		},
	});
	d.show();
}

function _confirm_bounced(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Mark Cheque as Bounced"),
		fields: [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: `<p class="text-muted">${__("Cheque No: <strong>{0}</strong> — Amount: <strong>{1} OMR</strong>", [frm.doc.cheque_no, frm.doc.amount])}</p>`,
			},
			{
				fieldname: "notes",
				fieldtype: "Small Text",
				label: __("Reason / Notes"),
				placeholder: __("e.g. Insufficient funds, Account closed…"),
			},
		],
		primary_action_label: __("Mark Bounced"),
		primary_action(values) {
			d.hide();
			frappe.call({
				method: "misk_real_estate.pdc_management.doctype.pdc_entry.pdc_entry.mark_bounced",
				args: {
					pdc_entry_name: frm.doc.name,
					notes: values.notes || "",
				},
				freeze: true,
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({
							message: __("Cheque {0} marked Bounced.", [frm.doc.cheque_no]),
							indicator: "red",
						});
						frm.reload_doc();
					}
				},
			});
		},
	});
	d.show();
}
