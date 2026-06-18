frappe.listview_settings["Property Booking"] = {
	// Required: without this, Frappe returns a hardcoded "Draft" for any
	// docstatus-0 document before reaching get_indicator (so Lost never showed).
	has_indicator_for_draft: 1,

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
