// Quotation customisation — Misk Real Estate
// Per-line: Building → Unit (Available only) → Price List (unit-filtered) → Payment Plan → installment calc
// Approval workflow badge + "Create Property Booking" button

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		_set_item_query(frm);
		_add_action_buttons(frm);
	},
});

frappe.ui.form.on("Quotation Item", {
	// Building changed — clear unit and re-apply item filter
	building(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "item_code", "");
		frappe.model.set_value(cdt, cdn, "price_list", "");
		frappe.model.set_value(cdt, cdn, "rate", 0);
		_set_item_query(frm);
	},

	// Unit selected — auto-fill building, reset price_list
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.item_code && !row.building) {
			frappe.db.get_value("Item", row.item_code, "item_group", (r) => {
				if (r && r.item_group) frappe.model.set_value(cdt, cdn, "building", r.item_group);
			});
		}
		frappe.model.set_value(cdt, cdn, "price_list", "");
		frappe.model.set_value(cdt, cdn, "rate", 0);
	},

	// Price List selected — filter to unit's price lists + fetch rate
	price_list(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code || !row.price_list) return;
		frappe.db.get_value(
			"Item Price",
			{ item_code: row.item_code, price_list: row.price_list },
			"price_list_rate",
			(r) => {
				if (r && r.price_list_rate) {
					frappe.model.set_value(cdt, cdn, "rate", r.price_list_rate);
				}
			}
		);
	},

	// Payment Plan selected — fetch installment count + recalculate
	payment_plan(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.payment_plan) return;
		frappe.db.get_value("Payment Plan", row.payment_plan,
			["number_of_installments", "is_full_payment"], (r) => {
			if (!r) return;
			const n = (!r.is_full_payment && r.number_of_installments) ? r.number_of_installments : 0;
			frappe.model.set_value(cdt, cdn, "number_of_installments", n);
			_recalc_row(cdt, cdn);
		});
	},

	// Rate changes → recalculate
	rate(frm, cdt, cdn) { _recalc_row(cdt, cdn); },

	// Down Payment % → calculate amount + recalc installment
	down_payment_percentage(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const price = flt(row.rate);
		if (!price || !row.down_payment_percentage) return;
		frappe.model.set_value(cdt, cdn, "down_payment_amount",
			flt((price * flt(row.down_payment_percentage) / 100).toFixed(3)));
		_recalc_row(cdt, cdn);
	},

	// Down Payment Amount → back-calculate % + recalc installment
	down_payment_amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const price = flt(row.rate);
		if (!price || !row.down_payment_amount) return;
		frappe.model.set_value(cdt, cdn, "down_payment_percentage",
			flt((flt(row.down_payment_amount) / price * 100).toFixed(3)));
		_recalc_row(cdt, cdn);
	},

	booking_amount(frm, cdt, cdn) { _recalc_row(cdt, cdn); },
});


// ── Open new Property Booking pre-filled from Quotation line ─────────────────
function _open_new_booking(frm, item) {
	const prefill = {
		quotation:          frm.doc.name,
		company:            frm.doc.company || "",
		building:           item.building || "",
		unit:               item.item_code || "",
		unit_price:         item.rate || 0,
		payment_plan:       item.payment_plan || frm.doc.payment_plan || "",
		price_list:         item.price_list || frm.doc.selling_price_list || "",
		booking_amount:     item.booking_amount || 0,
		down_payment_percentage: item.down_payment_percentage || 0,
		down_payment_amount: item.down_payment_amount || 0,
		owners_association_fee: item.owners_association_fee || 0,
	};

	const party_type = frm.doc.quotation_to;
	const party_name = frm.doc.party_name;

	if (party_type === "Customer") {
		prefill.customer = party_name;
		frappe.route_options = prefill;
		frappe.new_doc("Property Booking");
	} else {
		// Lead — check if already converted to customer
		frappe.db.get_value("Lead", party_name, "customer", (r) => {
			prefill.customer = (r && r.customer) ? r.customer : "";
			frappe.route_options = prefill;
			frappe.new_doc("Property Booking");
		});
	}
}

// ── Item query: filter by building + Available units only ─────────────────────
function _set_item_query(frm) {
	frm.fields_dict["items"].grid.get_field("item_code").get_query = function(doc, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		const filters = { unit_status: "Available" };
		if (row && row.building) filters["item_group"] = row.building;
		return { filters };
	};

	// Price list query: filtered to prices available for this unit
	frm.fields_dict["items"].grid.get_field("price_list").get_query = function(doc, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		if (!row || !row.item_code) return {};
		return {
			query: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_price_lists_for_unit",
			filters: { unit: row.item_code },
		};
	};
}

// ── Recalculate monthly installment for one row ───────────────────────────────
function _recalc_row(cdt, cdn) {
	const row = locals[cdt][cdn];
	const n = cint(row.number_of_installments);
	const price = flt(row.rate);
	const booking = flt(row.booking_amount);
	const dp = flt(row.down_payment_amount);
	if (!n || !price || !booking) {
		frappe.model.set_value(cdt, cdn, "monthly_installment", 0);
		return;
	}
	const after_dp = (price - booking) - dp;
	if (after_dp > 0) {
		frappe.model.set_value(cdt, cdn, "monthly_installment", flt((after_dp / n).toFixed(3)));
	}
}


// ── Action buttons ────────────────────────────────────────────────────────────
function _add_action_buttons(frm) {
	const state = frm.doc.workflow_state;

	if (frm.doc.docstatus === 1 && state === "Confirmed") {
		const pending = (frm.doc.items || []).filter(r => !r.property_booking);
		pending.forEach(item => {
			const label = item.item_code + (item.building ? ` — ${item.building}` : "");
			frm.add_custom_button(__(label), () => {
				_open_new_booking(frm, item);
			}, __("Create Property Booking"));
		});
	}

	frm.add_custom_button(__("Property Bookings"), () => {
		frappe.set_route("List", "Property Booking", { quotation: frm.doc.name });
	}, __("View"));
}
