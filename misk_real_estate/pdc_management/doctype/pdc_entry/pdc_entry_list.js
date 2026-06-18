// List-view bulk actions + indicators for PDC Entry.
// Pipeline: Pending → Sent to Bank → Deposited → Cleared / Bounced (also Returned,
// Cancelled, Substituted). Actions appear in the "Actions" menu once rows selected.

frappe.listview_settings["PDC Entry"] = {
	add_fields: ["bounce_reason", "bounce_reason_color"],

	onload(listview) {
		const M = "misk_real_estate.pdc_management.doctype.pdc_entry.pdc_entry";

		function selected_names() {
			const items = listview.get_checked_items();
			if (!items.length) {
				frappe.msgprint(__("Select at least one PDC Entry first."));
				return null;
			}
			return items.map(i => i.name);
		}

		function run_bulk(action, names, payload, freeze_msg) {
			frappe.call({
				method: M + ".bulk_action",
				args: Object.assign({ names: names, action: action }, payload || {}),
				freeze: true,
				freeze_message: freeze_msg || __("Updating {0} cheque(s)…", [names.length]),
				callback(r) {
					if (r.exc || !r.message) return;
					const ok = r.message.ok || [];
					const failed = r.message.failed || [];
					if (ok.length) {
						frappe.show_alert({ message: __("{0} cheque(s) updated.", [ok.length]), indicator: "green" });
					}
					if (failed.length) {
						frappe.msgprint({
							title: __("{0} could not be updated", [failed.length]),
							indicator: "orange",
							message: failed.map(f => `<b>${frappe.utils.escape_html(f.name)}</b>: ${frappe.utils.escape_html(f.error)}`).join("<br>"),
						});
					}
					listview.refresh();
				},
			});
		}

		function prompt_then(action, fields, label, build_payload) {
			const names = selected_names();
			if (!names) return;
			frappe.prompt(fields, (v) => run_bulk(action, names, build_payload(v)), label, __("Confirm"));
		}

		const today = () => frappe.datetime.get_today();

		listview.page.add_actions_menu_item(__("Sent to Bank"), () => {
			prompt_then("sent_to_bank",
				[{ fieldname: "date", fieldtype: "Date", label: __("Sent Date"), default: today(), reqd: 1 }],
				__("Mark Sent to Bank"), (v) => ({ date: v.date }));
		});

		listview.page.add_actions_menu_item(__("Mark Deposited"), () => {
			prompt_then("deposited",
				[{ fieldname: "date", fieldtype: "Date", label: __("Deposit Date"), default: today(), reqd: 1 }],
				__("Mark Deposited"), (v) => ({ date: v.date }));
		});

		listview.page.add_actions_menu_item(__("Mark Cleared"), () => {
			prompt_then("cleared",
				[{ fieldname: "date", fieldtype: "Date", label: __("Cleared Date"), default: today(), reqd: 1 },
				 { fieldname: "hint", fieldtype: "HTML", options: `<div class="text-muted small">${__("Posts a Payment Entry per cheque. Cheques without an invoice on every row are skipped and reported.")}</div>` }],
				__("Mark Cleared (posts GL)"), (v) => ({ date: v.date }));
		});

		listview.page.add_actions_menu_item(__("Mark Bounced"), () => {
			prompt_then("bounced",
				[{ fieldname: "bounce_reason", fieldtype: "Link", label: __("Bounce Reason"), options: "PDC Bounce Reason", reqd: 1 },
				 { fieldname: "notes", fieldtype: "Small Text", label: __("Extra Notes") }],
				__("Mark Bounced"), (v) => ({ bounce_reason: v.bounce_reason, notes: v.notes || "" }));
		});

		listview.page.add_actions_menu_item(__("Mark Returned"), () => {
			prompt_then("returned",
				[{ fieldname: "notes", fieldtype: "Small Text", label: __("Notes") }],
				__("Mark Returned"), (v) => ({ notes: v.notes || "" }));
		});

		listview.page.add_actions_menu_item(__("Cancel Cheque"), () => {
			prompt_then("cancelled",
				[{ fieldname: "notes", fieldtype: "Small Text", label: __("Notes") }],
				__("Cancel Cheque"), (v) => ({ notes: v.notes || "" }));
		});
	},

	formatters: {
		bounce_reason(value, df, doc) {
			if (!value) return "";
			const color = doc.bounce_reason_color || "red";
			return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(value)}</span>`;
		},
	},

	get_indicator(doc) {
		const map = {
			"Pending": "gray",
			"Sent to Bank": "purple",
			"In Batch": "blue",
			"Deposited": "orange",
			"Cleared": "green",
			"Bounced": "red",
			"Substituted": "yellow",
			"Cancelled": "gray",
			"Returned": "pink",
		};
		return [__(doc.status), map[doc.status] || "gray", "status,=," + doc.status];
	},
};
