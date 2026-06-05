// Quotation customisation — Misk Real Estate
// - Approval status badge
// - Building filter on items: select Building → only Available units shown
// - "Create Property Booking" button when Quotation is Confirmed

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		_set_item_query(frm);
		_add_action_buttons(frm);
	},
});

frappe.ui.form.on("Quotation Item", {
	down_payment_percentage(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const remaining = flt(row.rate) - flt(row.booking_amount);
		if (!remaining || !row.down_payment_percentage) return;
		const dp = flt((remaining * flt(row.down_payment_percentage) / 100).toFixed(3));
		frappe.model.set_value(cdt, cdn, "down_payment_amount", dp);
	},

	down_payment_amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const remaining = flt(row.rate) - flt(row.booking_amount);
		if (!remaining || !row.down_payment_amount) return;
		const pct = flt((flt(row.down_payment_amount) / remaining * 100).toFixed(3));
		frappe.model.set_value(cdt, cdn, "down_payment_percentage", pct);
	},

	building(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "item_code", "");
		frappe.model.set_value(cdt, cdn, "item_name", "");
		frappe.model.set_value(cdt, cdn, "rate", 0);
		_set_item_query(frm);
	},

	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.item_code && !row.building) {
			frappe.db.get_value("Item", row.item_code, "item_group", (r) => {
				if (r && r.item_group) {
					frappe.model.set_value(cdt, cdn, "building", r.item_group);
				}
			});
		}
	},
});

// ── Item query: filter by building + Available only ───────────────────────────
function _set_item_query(frm) {
	frm.fields_dict["items"].grid.get_field("item_code").get_query = function(doc, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		const filters = { unit_status: "Available" };
		if (row && row.building) filters["item_group"] = row.building;
		return { filters };
	};
}

// ── Action buttons ────────────────────────────────────────────────────────────
function _add_action_buttons(frm) {
	const state = frm.doc.workflow_state;

	// "Create Property Booking" — only when Confirmed and not already Ordered
	if (
		frm.doc.docstatus === 1 &&
		state === "Confirmed" &&
		frm.doc.status !== "Ordered"
	) {
		frm.add_custom_button(__("Create Property Booking"), () => {
			frappe.confirm(
				__("Create Property Booking(s) for all {0} line item(s) in this Quotation?",
					[frm.doc.items ? frm.doc.items.length : 0]),
				() => {
					frappe.call({
						method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.create_bookings_from_quotation",
						args: { quotation_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Creating Property Bookings..."),
						callback(r) {
							if (!r.exc && r.message && r.message.length) {
								if (r.message.length === 1) {
									frappe.set_route("Form", "Property Booking", r.message[0]);
								} else {
									frappe.show_alert({
										message: __("{0} bookings created.", [r.message.length]),
										indicator: "green",
									});
									frappe.set_route("List", "Property Booking", { quotation: frm.doc.name });
								}
							}
						},
					});
				}
			);
		}, __("Actions"));
	}

	// View linked Property Bookings
	frm.add_custom_button(__("Property Bookings"), () => {
		frappe.set_route("List", "Property Booking", { quotation: frm.doc.name });
	}, __("View"));
}
