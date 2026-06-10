frappe.listview_settings["Quotation"] = frappe.listview_settings["Quotation"] || {};

frappe.listview_settings["Quotation"].get_indicator = function(doc) {
	// Workflow states take priority for display in the indicator dot
	const workflow_map = {
		"Draft":                    ["Draft",                    "grey"],
		"Pending Sales Approval":   ["Pending Sales Approval",   "orange"],
		"Pending Finance Approval": ["Pending Finance Approval", "yellow"],
		"Confirmed":                ["Confirmed",                "green"],
		"Rejected":                 ["Rejected",                 "red"],
	};
	const status_map = {
		"Open":              ["Open",              "blue"],
		"Ordered":           ["Ordered",           "green"],
		"Partially Ordered": ["Partially Ordered", "purple"],
		"Lost":              ["Lost",              "grey"],
		"Cancelled":         ["Cancelled",         "red"],
		"Expired":           ["Expired",           "grey"],
	};

	if (doc.workflow_state && workflow_map[doc.workflow_state]) {
		const [label, color] = workflow_map[doc.workflow_state];
		return [label, color, "workflow_state,=," + doc.workflow_state];
	}
	if (doc.status && status_map[doc.status]) {
		const [label, color] = status_map[doc.status];
		return [label, color, "status,=," + doc.status];
	}
	return [doc.status || doc.workflow_state, "grey"];
};
