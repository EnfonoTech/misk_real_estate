frappe.listview_settings["Property Booking"] = {
	get_indicator(doc) {
		const map = {
			"Draft":     ["Draft",     "grey"],
			"Confirmed": ["Confirmed", "blue"],
			"Closed": ["Closed", "green"],
			"Cancelled": ["Cancelled", "red"],
		};
		const [label, color] = map[doc.status] || [doc.status, "grey"];
		return [label, color, "status,=," + doc.status];
	},
};
