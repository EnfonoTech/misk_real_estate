frappe.listview_settings["Property Booking"] = {
	get_indicator(doc) {
		const map = {
			"Draft":                  ["Draft", "grey"],
			"Booking Amount Received":["Booking Amount Received", "orange"],
			"Down Payment Received":  ["Down Payment Received", "purple"],
			"Confirmed":              ["Confirmed", "blue"],
			"Closed":                 ["Closed", "green"],
			"Cancelled":              ["Cancelled", "red"],
		};
		const [label, color] = map[doc.status] || [doc.status, "grey"];
		return [label, color, "status,=," + doc.status];
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
