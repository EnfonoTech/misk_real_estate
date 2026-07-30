frappe.listview_settings["Property Booking"] = {
	// Required: without this, Frappe returns a hardcoded "Draft" for any
	// docstatus-0 document before reaching get_indicator (so Lost never showed).
	has_indicator_for_draft: 1,

	onload(listview) {
		const M = "misk_real_estate.real_estate.doctype.property_booking.property_booking";

		listview.page.add_actions_menu_item(__("Create PDC Entries"), () => {
			const items = listview.get_checked_items();
			if (!items.length) {
				frappe.msgprint(__("Select at least one Property Booking first."));
				return;
			}
			const names = items.map((i) => i.name);
			frappe.confirm(
				__("Create PDC Entries for {0} selected Property Booking(s)?", [names.length]),
				() => {
					frappe.call({
						method: M + ".bulk_create_pdc_entries",
						args: { names },
						freeze: true,
						freeze_message: __("Creating PDC Entries…"),
						callback(r) {
							if (r.exc || !r.message) return;
							const ok = r.message.ok || [];
							const failed = r.message.failed || [];
							const total_created = ok.reduce((sum, o) => sum + o.created, 0);
							if (ok.length) {
								frappe.show_alert({
									message: __("{0} PDC Entries created across {1} booking(s).", [total_created, ok.length]),
									indicator: "green",
								});
							}
							if (failed.length) {
								frappe.msgprint({
									title: __("{0} booking(s) could not be processed", [failed.length]),
									indicator: "orange",
									message: failed.map(
										(f) => `<b>${frappe.utils.escape_html(f.name)}</b>: ${frappe.utils.escape_html(f.error)}`
									).join("<br>"),
								});
							}
							listview.refresh();
						},
					});
				}
			);
		});

		listview.page.add_actions_menu_item(__("Create Missing Invoices"), () => {
			const items = listview.get_checked_items();
			if (!items.length) {
				frappe.msgprint(__("Select at least one Property Booking first."));
				return;
			}
			const names = items.map((i) => i.name);
			frappe.confirm(
				__("Create missing (due) Sales Invoices for {0} selected Property Booking(s)?", [names.length]),
				() => {
					frappe.call({
						method: M + ".bulk_create_missing_invoices",
						args: { names },
						freeze: true,
						freeze_message: __("Creating invoices…"),
						callback(r) {
							if (r.exc || !r.message) return;
							const ok = r.message.ok || [];
							const failed = r.message.failed || [];
							const total_created = ok.reduce((sum, o) => sum + o.created, 0);
							if (ok.length) {
								frappe.show_alert({
									message: __("{0} Sales Invoice(s) created (Draft) across {1} booking(s).", [total_created, ok.length]),
									indicator: "green",
								});
							}
							if (failed.length) {
								frappe.msgprint({
									title: __("{0} booking(s) could not be processed", [failed.length]),
									indicator: "orange",
									message: failed.map(
										(f) => `<b>${frappe.utils.escape_html(f.name)}</b>: ${frappe.utils.escape_html(f.error)}`
									).join("<br>"),
								});
							}
							listview.refresh();
						},
					});
				}
			);
		});
	},

	get_indicator(doc) {
		const status_map = {
			"Booking Amount Received":["Booking Amount Received", "orange"],
			"Down Payment Received":  ["Down Payment Received", "purple"],
			"Installments in Progress":["Installments in Progress", "cyan"],
			"Confirmed":              ["Confirmed", "blue"],
			"Closed":                 ["Closed", "green"],
			"Cancelled":              ["Cancelled", "red"],
			"Lost":                   ["Lost", "red"],
		};
		if (status_map[doc.status]) {
			const [label, color] = status_map[doc.status];
			return [label, color, "status,=," + doc.status];
		}
		// status is still "Draft" → show the approval stage instead
		const wf_color = {
			"Draft":                       "gray",
			"Pending Sales Approval":      "orange",
			"Pending Finance Approval":    "orange",
			"Pending Management Approval": "orange",
			"Confirmed":                   "blue",
			"Rejected":                    "red",
		};
		const ws = doc.workflow_state || "Draft";
		return [ws, wf_color[ws] || "gray", "workflow_state,=," + ws];
	},

	formatters: {
		installment_progress(value) {
			const pct = Math.max(0, Math.min(100, Math.round(flt(value))));
			const color = pct >= 100 ? "#16a34a" : "#3b82f6";
			return `
				<div style="display:flex;align-items:center;gap:8px;min-width:90px;">
					<div style="flex:1;background:#edf0f5;border-radius:6px;height:8px;overflow:hidden;">
						<div style="width:${pct}%;height:100%;background:${color};"></div>
					</div>
					<span style="font-size:11px;color:#6b7280;">${pct}%</span>
				</div>`;
		},
	},
};
