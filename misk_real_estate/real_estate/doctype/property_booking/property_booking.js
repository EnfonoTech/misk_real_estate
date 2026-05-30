// apps/misk_real_estate/misk_real_estate/real_estate/doctype/property_booking/property_booking.js

frappe.ui.form.on("Property Booking", {

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

		// View PDC Entries — always show after submission
		frm.add_custom_button(__("PDC Entries"), () => {
			frappe.set_route("List", "PDC Entry", { booking: frm.doc.name });
		}, __("View"));

		// View Sales Invoices linked to this booking
		frm.add_custom_button(__("Sales Invoices"), () => {
			frappe.set_route("List", "Sales Invoice", { custom_property_booking: frm.doc.name });
		}, __("View"));

		// View Payment Entries linked to this booking
		frm.add_custom_button(__("Payment Entries"), () => {
			frappe.set_route("List", "Payment Entry", { property_booking: frm.doc.name });
		}, __("View"));

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

		// Status indicator badge
		const colors = {
			"Draft": "grey", "Confirmed": "blue", "Converted": "green", "Cancelled": "red"
		};
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");
	},

	// ── Unit filter — only show units in selected building ───────────────────
	set_unit_filter(frm) {
		if (frm.doc.building) {
			frm.set_query("unit", () => ({
				filters: { item_group: frm.doc.building }
			}));
		}
	},

	building(frm) {
		frm.set_value("unit", "");
		frm.set_value("unit_price", "");
		frm.trigger("set_unit_filter");
	},

	unit(frm) {
		// Fetch standard_rate from Item when unit selected
		if (frm.doc.unit) {
			frappe.db.get_value("Item", frm.doc.unit, "standard_rate", (r) => {
				if (r && r.standard_rate) {
					frm.set_value("unit_price", r.standard_rate);
				}
			});
		}
	},

	// ── Live calculation ──────────────────────────────────────────────────────
	unit_price(frm) { frm.trigger("recalculate"); },
	booking_amount(frm) { frm.trigger("recalculate"); },
	down_payment_percentage(frm) { frm.trigger("recalculate"); },
	down_payment_type(frm) { frm.trigger("recalculate"); },
	payment_plan(frm) { frm.trigger("recalculate"); },

	// When user edits fixed amount directly — back-calculate %
	down_payment_amount(frm) {
		if (!frm.doc.down_payment_type) return;
		frm.trigger("recalculate_from_fixed");
	},

	recalculate_from_fixed(frm) {
		const price = flt(frm.doc.unit_price);
		const booking = flt(frm.doc.booking_amount);
		const dp = flt(frm.doc.down_payment_amount);
		const plan = frm.doc.payment_plan || "";
		let n = 0;
		if (plan.includes("12M")) n = 12;
		else if (plan.includes("24M")) n = 24;
		else if (plan.includes("36M")) n = 36;
		if (!price || !booking || !dp || !n) return;

		const remaining = price - booking;
		if (remaining > 0) {
			frm.set_value("down_payment_percentage", flt((dp / remaining * 100).toFixed(3)));
		}
		const after_dp = remaining - dp;
		if (n > 0 && after_dp > 0) {
			frm.set_value("monthly_installment", flt((after_dp / n).toFixed(3)));
		}
	},

	recalculate(frm) {
		const price = flt(frm.doc.unit_price);
		const booking = flt(frm.doc.booking_amount);
		if (!price || !booking) return;

		const plan = frm.doc.payment_plan || "";
		let n = 0;
		if (plan.includes("12M")) n = 12;
		else if (plan.includes("24M")) n = 24;
		else if (plan.includes("36M")) n = 36;

		if (plan === "Full Payment" || n === 0) {
			frm.set_value("number_of_installments", 0);
			frm.set_value("down_payment_amount", 0);
			frm.set_value("down_payment_percentage", 0);
			frm.set_value("monthly_installment", 0);
			return;
		}

		frm.set_value("number_of_installments", n);

		// Skip recalculate if user is in Fixed Amount mode (they control the amount)
		if (frm.doc.down_payment_type) return;

		const remaining = price - booking;
		const dp_pct = flt(frm.doc.down_payment_percentage) || 50;
		if (!frm.doc.down_payment_percentage) {
			frm.set_value("down_payment_percentage", 50);
		}
		const dp = flt((remaining * dp_pct / 100).toFixed(3));
		frm.set_value("down_payment_amount", dp);

		const after_dp = remaining - dp;
		if (n > 0 && after_dp > 0) {
			frm.set_value("monthly_installment", flt((after_dp / n).toFixed(3)));
		}
	},
});
