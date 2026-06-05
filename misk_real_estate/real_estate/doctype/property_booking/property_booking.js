// apps/misk_real_estate/misk_real_estate/real_estate/doctype/property_booking/property_booking.js

frappe.ui.form.on("Property Booking", {

	onload(frm) {
		if (frm.is_new() && !frm.doc.company) {
			const company = frappe.defaults.get_user_default("company")
				|| frappe.defaults.get_global_default("company");
			if (company) frm.set_value("company", company);
		}
	},

	// ── Refresh — build action buttons based on state ─────────────────────────
	refresh(frm) {
		frm.trigger("set_unit_filter");

		if (frm.doc.docstatus !== 1) return;

		const has_pdc = (frm.doc.pdc_schedule || []).some(r => r.pdc_entry);

		// Create PDC Entries — show when submitted, no entries created yet
		if (!has_pdc) {
			frm.add_custom_button(__("Create PDC Entries"), () => {
				frappe.confirm(
					__("Create PDC Entry records for all {0} schedule rows?",
						[frm.doc.pdc_schedule ? frm.doc.pdc_schedule.length : 0]),
					() => {
						frappe.call({
							method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.create_pdc_entries",
							args: { booking_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Creating PDC Entries..."),
							callback(r) {
								if (!r.exc) {
									frappe.show_alert({
										message: __("{0} PDC Entries created.", [r.message.length]),
										indicator: "green"
									});
									frm.reload_doc();
								}
							},
						});
					}
				);
			}, __("PDC"));
		}

		// View PDC Entries
		frm.add_custom_button(__("PDC Entries"), () => {
			frappe.set_route("List", "PDC Entry", { booking: frm.doc.name });
		}, __("View"));

		// View Sales Invoices
		frm.add_custom_button(__("Sales Invoices"), () => {
			frappe.set_route("List", "Sales Invoice", { custom_property_booking: frm.doc.name });
		}, __("View"));

		// View Payment Entries
		frm.add_custom_button(__("Payment Entries"), () => {
			frappe.set_route("List", "Payment Entry", { property_booking: frm.doc.name });
		}, __("View"));

		// View source Quotation
		if (frm.doc.quotation) {
			frm.add_custom_button(__("Quotation"), () => {
				frappe.set_route("Form", "Quotation", frm.doc.quotation);
			}, __("View"));
		}

		// Generate Invoices Now — All at Once mode, no SIs created yet
		const has_si = (frm.doc.pdc_schedule || []).some(r => r.sales_invoice);
		if (frm.doc.invoice_generation === "All at Once" && !has_si) {
			frm.add_custom_button(__("Generate Invoices Now"), () => {
				frappe.confirm(
					__("Generate Sales Invoices for all {0} PDC schedule rows now?",
						[frm.doc.pdc_schedule ? frm.doc.pdc_schedule.length : 0]),
					() => {
						frappe.call({
							method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.trigger_invoice_generation",
							args: { booking_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Queuing invoice generation..."),
							callback(r) {
								if (!r.exc) {
									frappe.show_alert({
										message: __("Invoice generation queued. Refresh in a moment."),
										indicator: "blue"
									});
								}
							},
						});
					}
				);
			}, __("Actions"));
		}

		// Mark as Sold — when all PDCs cleared and unit not yet sold
		const all_cleared = (frm.doc.pdc_schedule || []).length > 0 &&
			(frm.doc.pdc_schedule || []).every(r => ["Cleared", "Cancelled"].includes(r.status));
		if (all_cleared && frm.doc.status !== "Converted") {
			frm.add_custom_button(__("Mark Unit Sold"), () => {
				frappe.confirm(
					__("Mark unit {0} as Sold? This cannot be undone.", [frm.doc.unit]),
					() => {
						frappe.call({
							method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.mark_unit_sold",
							args: { booking_name: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.exc) frm.reload_doc();
							},
						});
					}
				);
			}, __("Actions"));
		}

		// Regenerate PDC Schedule — only on Draft
		if (frm.doc.docstatus === 0 && frm.doc.pdc_schedule && frm.doc.pdc_schedule.length) {
			frm.add_custom_button(__("Regenerate PDC Schedule"), () => {
				frappe.confirm(
					__("This will clear all manually edited cheque dates and amounts and rebuild the schedule. Continue?"),
					() => {
						frappe.call({
							method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.regenerate_pdc_schedule",
							args: { booking_name: frm.doc.name },
							freeze: true,
							callback(r) { if (!r.exc) frm.reload_doc(); }
						});
					}
				);
			}, __("Actions"));
		}

		// Status indicator badge
		const colors = {
			"Draft": "grey", "Confirmed": "blue", "Converted": "green", "Cancelled": "red"
		};
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");

		// Hide + buttons in connection cards
		setTimeout(() => {
			frm.$wrapper.find(".form-link .btn-new, .links-header .btn-new, .form-link a.btn-new-doc, [class*='form-link'] .btn-new").hide();
		}, 500);
	},

	// ── Unit filter — only show units in selected building ───────────────────
	set_unit_filter(frm) {
		frm.set_query("unit", () => {
			const filters = { unit_status: "Available" };
			if (frm.doc.building) filters["item_group"] = frm.doc.building;
			return { filters };
		});
	},

	building(frm) {
		frm.set_value("unit", "");
		frm.set_value("unit_price", "");
		frm.trigger("set_unit_filter");
	},

	unit(frm) {
		// Filter price_list to only those that have a price for this unit
		frm.set_query("price_list", () => ({
			query: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_price_lists_for_unit",
			filters: { unit: frm.doc.unit },
		}));
		frm.set_value("price_list", "");
		frm.set_value("unit_price", "");
		_fetch_unit_price(frm);
	},

	price_list(frm) {
		_fetch_unit_price(frm);
	},

	// ── Live calculation ──────────────────────────────────────────────────────
	unit_price(frm)    { frm.trigger("recalculate"); },
	booking_amount(frm){ frm.trigger("recalculate"); },
	payment_plan(frm)  { frm.trigger("recalculate"); },

	down_payment_percentage(frm) {
		// % of unit_price → calculate amount
		const price = flt(frm.doc.unit_price);
		const pct = flt(frm.doc.down_payment_percentage);
		if (!price || !pct) return;
		frm.set_value("down_payment_amount", flt((price * pct / 100).toFixed(3)));
		frm.trigger("_recalc_installment");
	},

	down_payment_amount(frm) {
		// Amount → back-calculate % against unit_price
		const price = flt(frm.doc.unit_price);
		const dp = flt(frm.doc.down_payment_amount);
		if (!price || !dp) return;
		frm.set_value("down_payment_percentage", flt((dp / price * 100).toFixed(3)));
		frm.trigger("_recalc_installment");
	},

	_recalc_installment(frm) {
		const n = cint(frm.doc.number_of_installments);
		const price = flt(frm.doc.unit_price), booking = flt(frm.doc.booking_amount);
		const dp = flt(frm.doc.down_payment_amount);
		if (!n || !price || !booking) return;
		const after_dp = (price - booking) - dp;
		if (after_dp > 0) frm.set_value("monthly_installment", flt((after_dp / n).toFixed(3)));
	},

	recalculate(frm) {
		if (!frm.doc.payment_plan) return;
		frappe.db.get_value("Payment Plan", frm.doc.payment_plan,
			["number_of_installments", "is_full_payment"], (r) => {
			if (!r) return;
			const price = flt(frm.doc.unit_price), booking = flt(frm.doc.booking_amount);
			if (!price || !booking) return;

			const n = (!r.is_full_payment && r.number_of_installments) ? r.number_of_installments : 0;

			if (r.is_full_payment || n === 0) {
				frm.set_value("number_of_installments", 0);
				frm.set_value("down_payment_amount", 0);
				frm.set_value("down_payment_percentage", 0);
				frm.set_value("monthly_installment", 0);
				return;
			}

			frm.set_value("number_of_installments", n);
			const dp_pct = flt(frm.doc.down_payment_percentage) || 50;
			if (!frm.doc.down_payment_percentage) frm.set_value("down_payment_percentage", 50);
			const dp = flt((price * dp_pct / 100).toFixed(3));
			frm.set_value("down_payment_amount", dp);
			const after_dp = (price - booking) - dp;
			if (n > 0 && after_dp > 0) frm.set_value("monthly_installment", flt((after_dp / n).toFixed(3)));
		});
	},
});

// ── Unit price fetch (price list aware) ──────────────────────────────────────
function _fetch_unit_price(frm) {
	if (!frm.doc.unit) return;
	if (frm.doc.price_list) {
		frappe.db.get_value(
			"Item Price",
			{ item_code: frm.doc.unit, price_list: frm.doc.price_list },
			"price_list_rate",
			(r) => {
				if (r && r.price_list_rate) {
					frm.set_value("unit_price", r.price_list_rate);
				}
			}
		);
	} else {
		frappe.db.get_value("Item", frm.doc.unit, "standard_rate", (r) => {
			if (r && r.standard_rate) {
				frm.set_value("unit_price", r.standard_rate);
			}
		});
	}
}

