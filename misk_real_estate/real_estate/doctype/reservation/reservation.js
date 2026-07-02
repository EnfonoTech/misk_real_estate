// apps/misk_real_estate/misk_real_estate/real_estate/doctype/reservation/reservation.js

frappe.ui.form.on("Reservation", {
	setup(frm) {
		frm.set_query("quotation", () => ({
			filters: { workflow_state: "Confirmed" },
		}));
	},

	refresh(frm) {
		_set_unit_query(frm);
		_add_action_buttons(frm);
	},

	quotation(frm) {
		_set_unit_query(frm);
	},

	taxes_and_charges(frm) {
		if (!frm.doc.taxes_and_charges) return;
		frappe.call({
			method: "erpnext.controllers.accounts_controller.get_taxes_and_charges",
			args: {
				master_doctype: "Sales Taxes and Charges Template",
				master_name: frm.doc.taxes_and_charges,
			},
			callback(r) {
				if (!r.exc) {
					frm.set_value("taxes", r.message || []);
				}
			},
		});
	},
});

frappe.ui.form.on("Reservation Item", {
	unit(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.unit && !row.building) {
			frappe.db.get_value("Item", row.unit, "item_group", (r) => {
				if (r && r.item_group) frappe.model.set_value(cdt, cdn, "building", r.item_group);
			});
		}
	},
});

// ── Restrict the Unit dropdown (Units grid) to items on the selected Quotation ──
function _set_unit_query(frm) {
	frm.fields_dict["items"].grid.get_field("unit").get_query = () => ({
		query: "misk_real_estate.real_estate.doctype.reservation.reservation.get_quotation_units",
		filters: { quotation: frm.doc.quotation },
	});
}

// ── "Create Property Booking" — one entry per unit row not yet converted ──────
function _add_action_buttons(frm) {
	if (frm.is_new() || frm.doc.docstatus !== 1 || frm.doc.workflow_state !== "Approved") return;

	const pending = (frm.doc.items || []).filter((row) => !row.property_booking);
	pending.forEach((row) => {
		const label = row.unit + (row.building ? ` — ${row.building}` : "");
		frm.add_custom_button(
			__(label),
			() => _open_new_booking(frm, row),
			__("Create Property Booking")
		);
	});

	frm.add_custom_button(__("Property Bookings"), () => {
		frappe.set_route("List", "Property Booking", { quotation: frm.doc.quotation });
	}, __("View"));
}

// ── Open new Property Booking pre-filled from a Reservation unit row ─────────
function _open_new_booking(frm, row) {
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.resolve_customer_for_quotation",
		args: { quotation_name: frm.doc.quotation },
		freeze: true,
		freeze_message: __("Resolving customer..."),
		callback(r) {
			const customer = r.message || "";
			frappe.db.get_value(
				"Quotation",
				frm.doc.quotation,
				["company", "taxes_and_charges", "selling_price_list"],
				(q) => {
					frappe.route_options = {
						quotation: frm.doc.quotation,
						customer: customer,
						company: q.company || "",
						building: row.building || "",
						unit: row.unit || "",
						unit_price: row.selling_price || 0,
						payment_plan: row.proposed_payment_plan || "",
						price_list: q.selling_price_list || "",
						taxes_and_charges: q.taxes_and_charges || "",
						booking_amount: row.booking_amount || 0,
						down_payment_amount: row.down_payment_amount || 0,
					};
					frappe.new_doc("Property Booking");
				}
			);
		},
	});
}
