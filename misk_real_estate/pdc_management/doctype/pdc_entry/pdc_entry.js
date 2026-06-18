// apps/misk_real_estate/misk_real_estate/pdc_management/doctype/pdc_entry/pdc_entry.js

frappe.ui.form.on("PDC Entry", {

	// ── On load — set defaults for new docs ────────────────────────────────────
	onload(frm) {
		if (frm.is_new()) {
			if (frm.doc.customer) _fetch_currency(frm);
		}
		// Allocation rows: limit bookings & invoices to this cheque's customer
		frm.set_query("property_booking", "allocations", () => ({
			filters: frm.doc.customer ? { customer: frm.doc.customer } : {},
		}));
		frm.set_query("sales_invoice", "allocations", () => ({
			filters: {
				...(frm.doc.customer ? { customer: frm.doc.customer } : {}),
				docstatus: ["<", 2],
			},
		}));
		// Unit limited to the row's building (units are Items under that Item Group)
		frm.set_query("unit", "allocations", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			return { filters: row.building ? { item_group: row.building } : {} };
		});
	},

	customer(frm) {
		_fetch_currency(frm);
	},

	allocations_remove(frm) {
		_recalc_cheque_amount(frm);
	},

	// ── Refresh — build action buttons based on status ─────────────────────────
	refresh(frm) {
		const status = frm.doc.status;

		// Status badge
		const colors = {
			"Pending":      "orange",
			"Sent to Bank": "purple",
			"In Batch":     "blue",
			"Deposited":    "yellow",
			"Cleared":      "green",
			"Bounced":      "red",
		};
		frm.page.set_indicator(status, colors[status] || "grey");

		// Only action buttons when not submitted/cancelled through docstatus
		// PDC Entry is not a submittable doctype — use status field directly

		// Mark Sent to Bank — cheque handed to the bank, before deposit
		if (["Pending", "In Batch"].includes(status)) {
			frm.add_custom_button(__("Mark Sent to Bank"), () => {
				_confirm_sent_to_bank(frm);
			}, __("Actions"));
		}

		// Mark Deposited — cheque deposited, awaiting clearance/bounce
		if (["Pending", "Sent to Bank", "In Batch"].includes(status)) {
			frm.add_custom_button(__("Mark Deposited"), () => {
				_confirm_deposited(frm);
			}, __("Actions"));
		}

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

		// Single-allocation conveniences (multi-row cheques use the table itself)
		const allocs = frm.doc.allocations || [];
		const single = allocs.length === 1 ? allocs[0] : null;

		// Record Manual Payment — customer cancels PDC and pays by cash/transfer instead
		if (["Pending", "Deposited", "In Batch"].includes(status) && single && single.sales_invoice) {
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

		// View linked Sales Invoice (single-row cheque)
		if (single && single.sales_invoice) {
			frm.add_custom_button(__("Sales Invoice"), () => {
				frappe.set_route("Form", "Sales Invoice", single.sales_invoice);
			}, __("View"));
		}

		// View parent booking (single-row cheque)
		if (single && single.property_booking) {
			frm.add_custom_button(__("Property Booking"), () => {
				frappe.set_route("Form", "Property Booking", single.property_booking);
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

function _confirm_sent_to_bank(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Mark Sent to Bank"),
		fields: [
			{
				fieldname: "sent_date", fieldtype: "Date", label: __("Sent Date"),
				default: frappe.datetime.get_today(), reqd: 1,
			},
		],
		primary_action_label: __("Confirm"),
		primary_action(values) {
			d.hide();
			frappe.call({
				method: "misk_real_estate.pdc_management.doctype.pdc_entry.pdc_entry.mark_sent_to_bank",
				args: { pdc_entry_name: frm.doc.name, sent_date: values.sent_date },
				freeze: true,
				callback(r) { if (!r.exc) frm.reload_doc(); },
			});
		},
	});
	d.show();
}

function _confirm_deposited(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Mark Deposited"),
		fields: [
			{
				fieldname: "deposited_date", fieldtype: "Date", label: __("Deposit Date"),
				default: frappe.datetime.get_today(), reqd: 1,
			},
		],
		primary_action_label: __("Confirm"),
		primary_action(values) {
			d.hide();
			frappe.call({
				method: "misk_real_estate.pdc_management.doctype.pdc_entry.pdc_entry.mark_deposited",
				args: { pdc_entry_name: frm.doc.name, deposited_date: values.deposited_date },
				freeze: true,
				callback(r) { if (!r.exc) frm.reload_doc(); },
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
					${__("A Payment Entry will be created against Sales Invoice {0}.", [(frm.doc.allocations && frm.doc.allocations[0] && frm.doc.allocations[0].sales_invoice) || ""])}
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

// ── Allocation rows — auto-fill amount + invoice from booking/purpose ─────────
frappe.ui.form.on("PDC Allocation", {
	property_booking(frm, cdt, cdn) { _fill_allocation(frm, cdt, cdn, false); },
	purpose(frm, cdt, cdn) { _fill_allocation(frm, cdt, cdn, true); },
	allocated_amount: (frm) => _recalc_cheque_amount(frm),
});

function _recalc_cheque_amount(frm) {
	const total = (frm.doc.allocations || []).reduce((s, r) => s + flt(r.allocated_amount), 0);
	frm.set_value("amount", flt(total, 3));
}

// overwrite_amount: true when the Type changed — re-fetch amount/invoice for the
// new type. On a booking change we only fill blanks (don't clobber a typed amount).
function _fill_allocation(frm, cdt, cdn, overwrite_amount) {
	const row = locals[cdt][cdn];
	if (!row.property_booking) return;
	frappe.call({
		method: "misk_real_estate.pdc_management.doctype.pdc_entry.pdc_entry.get_allocation_defaults",
		args: { booking: row.property_booking, purpose: row.purpose || "" },
		callback(r) {
			if (r.exc || !r.message) return;
			const d = r.message;
			if (!row.building && d.building) frappe.model.set_value(cdt, cdn, "building", d.building);
			if (!row.unit && d.unit) frappe.model.set_value(cdt, cdn, "unit", d.unit);
			if (overwrite_amount) {
				frappe.model.set_value(cdt, cdn, "allocated_amount", d.amount || 0);
				frappe.model.set_value(cdt, cdn, "sales_invoice", d.sales_invoice || null);
			} else {
				if (!row.allocated_amount && d.amount) frappe.model.set_value(cdt, cdn, "allocated_amount", d.amount);
				if (!row.sales_invoice && d.sales_invoice) frappe.model.set_value(cdt, cdn, "sales_invoice", d.sales_invoice);
			}
		},
	});
}
