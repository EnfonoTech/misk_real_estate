// apps/misk_real_estate/misk_real_estate/real_estate/doctype/reservation/reservation.js

frappe.ui.form.on("Reservation", {
	setup(frm) {
		frm.set_query("quotation", () => ({
			filters: { docstatus: 1 },
		}));
	},

	onload(frm) {
		if (frm.is_new() && !frm.doc.sales_person) {
			frappe.call({
				method: "misk_real_estate.real_estate.doctype.reservation.reservation.get_default_sales_person",
				callback(r) {
					if (r.message) frm.set_value("sales_person", r.message);
				},
			});
		}
		if (frm.is_new() && !frm.doc.company) {
			const company = frappe.defaults.get_user_default("company")
				|| frappe.defaults.get_global_default("company");
			if (company) frm.set_value("company", company);
		}
	},

	refresh(frm) {
		_set_unit_query(frm);
		_add_action_buttons(frm);
	},

	quotation(frm) {
		_set_unit_query(frm);
		if (!frm.doc.quotation) return;
		frappe.db.get_value(
			"Quotation",
			frm.doc.quotation,
			["customer_name", "contact_mobile", "company"],
			(q) => {
				if (q.customer_name) frm.set_value("customer_name", q.customer_name);
				if (q.contact_mobile) frm.set_value("contact_mobile", q.contact_mobile);
				if (q.company) frm.set_value("company", q.company);
			}
		);
	},

	// Only auto-fill a default tax template when NOT coming from a Quotation —
	// same rule as property_booking.js's own company(frm) handler.
	company(frm) {
		if (frm.doc.company && !frm.doc.taxes_and_charges && !frm.doc.quotation) {
			frappe.call({
				method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_default_taxes_for_company",
				args: { company: frm.doc.company },
				callback(r) {
					if (r.message) frm.set_value("taxes_and_charges", r.message);
				},
			});
		}
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
	// Building changed — clear unit and re-apply the unit filter (same as
	// quotation.js's Building → Unit cascade)
	building(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "unit", "");
		frappe.model.set_value(cdt, cdn, "price_list", "");
		frappe.model.set_value(cdt, cdn, "selling_price", 0);
		_set_unit_query(frm);
	},

	// Unit selected — auto-fill building if not already set (fallback for
	// picking Unit before Building), reset price_list/selling_price
	unit(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.unit && !row.building) {
			frappe.db.get_value("Item", row.unit, "item_group", (r) => {
				if (r && r.item_group) frappe.model.set_value(cdt, cdn, "building", r.item_group);
			});
		}
		frappe.model.set_value(cdt, cdn, "price_list", "");
		frappe.model.set_value(cdt, cdn, "selling_price", 0);
	},

	// Price List selected — fetch rate then DP%, then calculate in sequence
	price_list(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.unit || !row.price_list) return;

		frappe.db.get_value(
			"Item Price",
			{ item_code: row.unit, price_list: row.price_list },
			"price_list_rate",
			(r) => {
				if (r && r.price_list_rate) {
					frappe.model.set_value(cdt, cdn, "selling_price", r.price_list_rate);
				}
				frappe.db.get_value("Price List", row.price_list, "down_payment_percentage", (dp) => {
					if (!dp || !dp.down_payment_percentage) return;
					frappe.model.set_value(cdt, cdn, "down_payment_percentage", dp.down_payment_percentage);
					const updated = locals[cdt][cdn];
					const price = flt(updated.selling_price);
					const pct = flt(updated.down_payment_percentage);
					if (price && pct) {
						frappe.model.set_value(cdt, cdn, "down_payment_amount",
							flt((price * pct / 100).toFixed(3)));
						_recalc_row(cdt, cdn);
					}
				});
			}
		);
	},

	// Payment Plan selected — fetch installment count + recalculate
	proposed_payment_plan(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.proposed_payment_plan) return;
		frappe.db.get_value("Payment Plan", row.proposed_payment_plan,
			["number_of_installments", "is_full_payment"], (r) => {
			if (!r) return;
			const n = (!r.is_full_payment && r.number_of_installments) ? r.number_of_installments : 0;
			frappe.model.set_value(cdt, cdn, "number_of_installments", n);
			_recalc_row(cdt, cdn);
		});
	},

	selling_price(frm, cdt, cdn) { _recalc_row(cdt, cdn); },

	// Down Payment % → calculate amount + recalc installment
	down_payment_percentage(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const price = flt(row.selling_price);
		if (!price || !row.down_payment_percentage) return;
		frappe.model.set_value(cdt, cdn, "down_payment_amount",
			flt((price * flt(row.down_payment_percentage) / 100).toFixed(3)));
		_recalc_row(cdt, cdn);
	},

	// Down Payment Amount → back-calculate % + recalc installment
	down_payment_amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const price = flt(row.selling_price);
		if (!price || !row.down_payment_amount) return;
		frappe.model.set_value(cdt, cdn, "down_payment_percentage",
			flt((flt(row.down_payment_amount) / price * 100).toFixed(3)));
		_recalc_row(cdt, cdn);
	},

	booking_amount(frm, cdt, cdn) { _recalc_row(cdt, cdn); },
});

// ── Recalculate monthly installment for one row ───────────────────────────────
function _recalc_row(cdt, cdn) {
	const row = locals[cdt][cdn];
	const n = cint(row.number_of_installments);
	const price = flt(row.selling_price);
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

// ── Restrict the Unit dropdown (Units grid) ───────────────────────────────────
// With a Quotation linked, only its own items are pickable (existing behaviour).
// Without one, fall back to a plain Available-units filter — same pattern as
// property_booking.js's own unit query.
function _set_unit_query(frm) {
	if (frm.doc.quotation) {
		frm.fields_dict["items"].grid.get_field("unit").get_query = () => ({
			query: "misk_real_estate.real_estate.doctype.reservation.reservation.get_quotation_units",
			filters: { quotation: frm.doc.quotation },
		});
	} else {
		frm.fields_dict["items"].grid.get_field("unit").get_query = (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			const filters = { unit_status: "Available" };
			if (row && row.building) filters["building"] = row.building;
			if (frm.doc.company) filters["company"] = frm.doc.company;
			return {
				query: "misk_real_estate.utils.company.get_units_for_company",
				filters,
			};
		};
	}

	// Price list query: filtered to prices available for this unit
	frm.fields_dict["items"].grid.get_field("price_list").get_query = (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		if (!row || !row.unit) return {};
		return {
			query: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_price_lists_for_unit",
			filters: { unit: row.unit },
		};
	};
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
		frappe.set_route("List", "Property Booking", { reservation: frm.doc.name });
	}, __("View"));
}

// ── Open new Property Booking pre-filled from a Reservation unit row ─────────
// Property Booking holds unit/price/payment-schedule fields on its child table
// (property_unit), so they can't be passed via frappe.route_options (that only
// sets scalar fields on the parent) — build the child row directly instead.
function _open_new_booking(frm, row) {
	if (frm.doc.quotation) {
		// Quotation-backed reservation — keep sourcing company/taxes/price list
		// from the Quotation, exactly as before.
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
						_build_booking(frm, row, {
							customer,
							company: q.company || "",
							taxes_and_charges: q.taxes_and_charges || "",
							price_list: q.selling_price_list || "",
						});
					}
				);
			},
		});
		return;
	}

	// Standalone reservation — source everything from the Reservation itself.
	_build_booking(frm, row, {
		customer: frm.doc.customer_name || "",
		company: frm.doc.company || "",
		taxes_and_charges: frm.doc.taxes_and_charges || "",
		price_list: row.price_list || "",
	});
}

function _build_booking(frm, row, ctx) {
	frappe.model.with_doctype("Property Booking", () => {
		const doc = frappe.model.get_new_doc("Property Booking");
		doc.reservation = frm.doc.name;
		doc.quotation = frm.doc.quotation;
		doc.customer = ctx.customer;
		doc.company = ctx.company;
		doc.sales_person = frm.doc.sales_person || "";
		doc.taxes_and_charges = ctx.taxes_and_charges;

		const unit_row = frappe.model.add_child(doc, "property_unit");
		unit_row.building = row.building || "";
		unit_row.unit = row.unit || "";
		unit_row.unit_price = row.selling_price || 0;
		unit_row.payment_plan = row.proposed_payment_plan || "";
		unit_row.price_list = ctx.price_list;
		unit_row.booking_amount = row.booking_amount || 0;
		unit_row.down_payment_percentage = row.down_payment_percentage || 0;
		unit_row.down_payment_amount = row.down_payment_amount || 0;
		unit_row.owners_association_fee = row.owners_association_fee || 0;

		frappe.set_route("Form", "Property Booking", doc.name);
	});
}
