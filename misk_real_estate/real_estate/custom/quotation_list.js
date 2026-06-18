frappe.listview_settings["Quotation"] = frappe.listview_settings["Quotation"] || {};

frappe.listview_settings["Quotation"].get_indicator = function(doc) {
	// Workflow states take priority for display in the indicator dot
	const workflow_map = {
		"Draft":                    ["Draft",                    "gray"],
		"Pending Sales Approval":   ["Pending Sales Approval",   "orange"],
		"Pending Finance Approval": ["Pending Finance Approval", "yellow"],
		"Confirmed":                ["Confirmed",                "green"],
		"Rejected":                 ["Rejected",                 "red"],
	};
	const status_map = {
		"Open":              ["Open",              "blue"],
		"Ordered":           ["Ordered",           "green"],
		"Partially Ordered": ["Partially Ordered", "purple"],
		"Lost":              ["Lost",              "gray"],
		"Cancelled":         ["Cancelled",         "red"],
		"Expired":           ["Expired",           "gray"],
	};

	// Conversion status (Ordered / Partially Ordered / Lost / Cancelled / Expired)
	// takes priority; show the approval workflow state only while still in progress.
	const conversion_states = ["Ordered", "Partially Ordered", "Lost", "Cancelled", "Expired"];
	if (doc.status && conversion_states.includes(doc.status)) {
		const [label, color] = status_map[doc.status];
		return [label, color, "status,=," + doc.status];
	}
	if (doc.workflow_state && workflow_map[doc.workflow_state]) {
		const [label, color] = workflow_map[doc.workflow_state];
		return [label, color, "workflow_state,=," + doc.workflow_state];
	}
	if (doc.status && status_map[doc.status]) {
		const [label, color] = status_map[doc.status];
		return [label, color, "status,=," + doc.status];
	}
	return [doc.status || doc.workflow_state, "gray"];
};

// Colour the "Workflow State" column (otherwise it renders as plain text)
frappe.listview_settings["Quotation"].formatters = Object.assign(
	frappe.listview_settings["Quotation"].formatters || {},
	{
		workflow_state(value) {
			if (!value) return "";
			const color = {
				"Draft": "gray",
				"Pending Sales Approval": "orange",
				"Pending Finance Approval": "yellow",
				"Confirmed": "green",
				"Rejected": "red",
			}[value] || "gray";
			return `<span class="indicator-pill ${color}">${__(value)}</span>`;
		},
	}
);
