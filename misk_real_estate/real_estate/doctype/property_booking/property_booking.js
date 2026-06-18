// apps/misk_real_estate/misk_real_estate/real_estate/doctype/property_booking/property_booking.js

frappe.ui.form.on("Property Booking", {

	onload(frm) {
		if (frm.is_new()) {
			frm._route_loading = true;
			setTimeout(() => { frm._route_loading = false; }, 800);

			if (!frm.doc.company) {
				const company = frappe.defaults.get_user_default("company")
					|| frappe.defaults.get_global_default("company");
				if (company) frm.set_value("company", company);
			}
		}
		// Cache tax rate from existing taxes_and_charges
		if (frm.doc.taxes_and_charges) _cache_tax_rate(frm);

		// Limit Customer Bank Account to the selected customer's bank accounts
		frm.set_query("customer_bank_account", () => ({
			filters: { party_type: "Customer", party: frm.doc.customer || "" },
		}));

		frm._last_cheque_prefix = frm.doc.cheque_prefix || "";
	},

	// Cheque No Prefix — fill every PDC row's cheque_no with the prefix so the user
	// only has to type the last digits per row. Non-destructive: rows the user has
	// already completed (value differs from the prefix) are left untouched; blank
	// rows and rows still holding the old prefix are updated.
	cheque_prefix(frm) {
		const prefix = (frm.doc.cheque_prefix || "").trim();
		const old = frm._last_cheque_prefix || "";
		(frm.doc.pdc_schedule || []).forEach(r => {
			if (!r.is_pdc) return;
			const cur = (r.cheque_no || "").trim();
			if (!cur || cur === old) {
				frappe.model.set_value(r.doctype, r.name, "cheque_no", prefix);
			}
		});
		frm._last_cheque_prefix = prefix;
		frm.refresh_field("pdc_schedule");
	},

	// ── Refresh — build action buttons based on state ─────────────────────────
	refresh(frm) {
		frm.trigger("set_unit_filter");

		// Advance payment buttons (Booking Amount / Down Payment) — available on a
		// saved Draft and on submitted bookings, since advance may be collected
		// before the booking is confirmed.
		if (!frm.is_new()) _add_advance_buttons(frm);

		// Mark Lost — release the reserved unit on a Draft that won't proceed
		if (frm.doc.docstatus === 0 && !frm.is_new() && frm.doc.status !== "Lost") {
			frm.add_custom_button(__("Mark Lost"), () => {
				frappe.confirm(
					__("Mark this booking as Lost and release unit {0}?", [frm.doc.unit || ""]),
					() => {
						frappe.call({
							method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.mark_lost",
							args: { booking_name: frm.doc.name },
							freeze: true,
							callback(r) { if (!r.exc) frm.reload_doc(); },
						});
					}
				);
			}, __("Actions"));
		}

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

		// View PDC Entries (resolved via allocation rows)
		frm.add_custom_button(__("PDC Entries"), () => {
			frappe.call({
				method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_booking_pdc_entries",
				args: { booking_name: frm.doc.name },
				callback(r) {
					const names = r.message || [];
					if (!names.length) {
						frappe.msgprint(__("No PDC Entries for this booking yet."));
						return;
					}
					frappe.set_route("List", "PDC Entry", { name: ["in", names] });
				},
			});
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

		// Create Missing Invoices — manual fallback when auto-creation failed or user wants draft review
		const missing_si = (frm.doc.pdc_schedule || []).some(r => !r.sales_invoice && r.status !== "Cancelled");
		if (missing_si) {
			frm.add_custom_button(__("Create Missing Invoices"), () => {
				frappe.confirm(
					__("Create draft Sales Invoices for all PDC rows that don't have one yet? You can review and submit them before they become final."),
					() => {
						frappe.call({
							method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.create_missing_invoices",
							args: { booking_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Creating draft invoices..."),
							callback(r) {
								if (!r.exc) frm.reload_doc();
							},
						});
					}
				);
			}, __("Actions"));
		}

		// Mark as Sold — when all PDCs cleared and unit not yet sold
		const all_cleared = (frm.doc.pdc_schedule || []).length > 0 &&
			(frm.doc.pdc_schedule || []).every(r => ["Cleared", "Cancelled"].includes(r.status));
		if (all_cleared && frm.doc.status !== "Closed") {
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
			"Draft": "gray", "Confirmed": "blue", "Closed": "green", "Cancelled": "red"
		};
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "gray");

		// PDC Schedule — color-code rows by installment type
		_style_pdc_schedule(frm);

		// Hide + buttons in connection cards
		setTimeout(() => {
			frm.$wrapper.find(".form-link .btn-new, .links-header .btn-new, .form-link a.btn-new-doc, [class*='form-link'] .btn-new").hide();
		}, 500);
	},

	company(frm) {
		// Only auto-fill default tax template when NOT coming from a Quotation
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
		frm._tax_rate = undefined;  // reset cache so next edit re-fetches
		_cache_tax_rate(frm);
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
		if (!frm._route_loading) {
			frm.set_value("unit", "");
			frm.set_value("unit_price", "");
		}
		frm.trigger("set_unit_filter");
	},

	unit(frm) {
		// Filter price_list to only those that have a price for this unit
		frm.set_query("price_list", () => ({
			query: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_price_lists_for_unit",
			filters: { unit: frm.doc.unit },
		}));
		if (!frm._route_loading) {
			frm.set_value("price_list", "");
			frm.set_value("unit_price", "");
		}
		// Reset tax cache — unit's Item Tax Template may differ
		frm._tax_rate = undefined;
		_cache_tax_rate(frm);
		_fetch_unit_price(frm);
	},

	price_list(frm) {
		_fetch_unit_price(frm);
		// Auto-fetch default down payment % from Price List
		if (frm.doc.price_list) {
			frappe.db.get_value("Price List", frm.doc.price_list, "down_payment_percentage", (r) => {
				if (r && r.down_payment_percentage) {
					frm.set_value("down_payment_percentage", r.down_payment_percentage);
				}
			});
		}
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
		if (!n || !price) return;
		const after_dp = (price - booking) - dp;
		if (after_dp > 0) frm.set_value("monthly_installment", flt((after_dp / n).toFixed(3)));
	},

	recalculate(frm) {
		const price = flt(frm.doc.unit_price);
		if (!price) return;

		// Down payment conversion — independent of payment plan, so changing
		// unit price / booking amount keeps the down payment in sync.
		const dp_amount = flt(frm.doc.down_payment_amount);
		const dp_pct = flt(frm.doc.down_payment_percentage);
		if (dp_amount > 0) {
			frm.set_value("down_payment_percentage", flt((dp_amount / price * 100).toFixed(3)));
		} else if (dp_pct > 0) {
			frm.set_value("down_payment_amount", flt((price * dp_pct / 100).toFixed(3)));
		}

		// Installments need a plan.
		if (!frm.doc.payment_plan) return;
		frappe.db.get_value("Payment Plan", frm.doc.payment_plan,
			["number_of_installments", "is_full_payment"], (r) => {
			if (!r) return;
			const booking = flt(frm.doc.booking_amount);

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

	pdc_schedule_add(frm)    { _check_pdc_total(frm); },
	pdc_schedule_remove(frm) { _check_pdc_total(frm); },
});

// ── PDC Schedule: recalc net/tax when user edits Total Amount ────────────────
frappe.ui.form.on("PDC Schedule", {
	amount(frm, cdt, cdn) {
		const apply = (rate) => {
			const total = flt(locals[cdt][cdn].amount);
			if (!rate) {
				frappe.model.set_value(cdt, cdn, "net_amount", total);
				frappe.model.set_value(cdt, cdn, "tax_amount", 0);
			} else {
				const net = flt((total / (1 + rate / 100)).toFixed(3));
				frappe.model.set_value(cdt, cdn, "net_amount", net);
				frappe.model.set_value(cdt, cdn, "tax_amount", flt((total - net).toFixed(3)));
			}
			_check_pdc_total(frm);
		};

		if (frm._tax_rate !== undefined) {
			apply(frm._tax_rate);
		} else {
			_cache_tax_rate(frm, () => apply(frm._tax_rate || 0));
		}
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

// ── Live PDC total vs Expected (Installments + OA) check ─────────────────────
function _check_pdc_total(frm) {
	const expected = flt(frm.doc.expected_table_total);
	const actual = (frm.doc.pdc_schedule || []).reduce((s, r) => s + flt(r.amount), 0);
	// Live-update the displayed totals (server recomputes identically on save)
	frm.set_value("table_total", flt(actual.toFixed(3)));
	frm.set_value("table_difference", flt((actual - expected).toFixed(3)));
	if (!expected || !frm.doc.pdc_schedule) return;
	const diff   = Math.abs(actual - expected);
	if (diff > 0.01) {
		frm.page.set_indicator(
			__("Table total {0} ≠ expected {1} (diff {2})", [
				format_currency(actual, "OMR", 3),
				format_currency(expected, "OMR", 3),
				format_currency(diff, "OMR", 3),
			]),
			"orange"
		);
	} else {
		const colors = { "Draft": "gray", "Confirmed": "blue", "Closed": "green", "Cancelled": "red" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "gray");
	}
}

// ── Advance Payments: Booking Amount & Down Payment invoice/payment buttons ───
function _add_advance_buttons(frm) {
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_advance_invoice_status",
		args: { booking_name: frm.doc.name },
		callback(r) {
			if (r.exc) return;
			const status = r.message || {};
			const grp = __("Advance Payments");

			const block = (amount, si, purpose, invoiceLabel, paymentLabel) => {
				if (flt(amount) <= 0) return;
				frm.add_custom_button(si ? __("Open " + invoiceLabel) : __(invoiceLabel),
					() => _open_advance_invoice(frm, purpose), grp);
				if (si) {
					frm.add_custom_button(__(paymentLabel),
						() => _record_advance_payment(frm, purpose), grp);
				}
				// Collect this advance by post-dated cheque (single-purpose; combine manually)
				frm.add_custom_button(__(purpose + " by PDC"),
					() => _collect_advance_pdc(frm, purpose), grp);
			};

			block(frm.doc.booking_amount, status["Booking Amount"],
				"Booking Amount", "Booking Amount Invoice", "Record Booking Payment");
			block(frm.doc.down_payment_amount, status["Down Payment"],
				"Down Payment", "Down Payment Invoice", "Record Down Payment");
		},
	});
}

function _collect_advance_pdc(frm, purpose) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the booking before collecting an advance by PDC."));
		return;
	}
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.create_advance_pdc",
		args: { booking_name: frm.doc.name, purpose },
		freeze: true,
		freeze_message: __("Preparing PDC Entry..."),
		callback(r) {
			if (r.exc || !r.message) return;
			const data = r.message;
			// Build a fresh local PDC Entry (get_new_doc assigns a usable name) and
			// pre-fill the header + one allocation row. To combine, add more rows.
			frappe.model.with_doctype("PDC Entry", () => {
				const doc = frappe.model.get_new_doc("PDC Entry");
				doc.customer = data.customer;
				doc.customer_bank_account = data.customer_bank_account;
				doc.company = data.company;
				doc.cheque_date = data.cheque_date;
				const a = data.allocation || {};
				const row = frappe.model.add_child(doc, "PDC Allocation", "allocations");
				row.property_booking = a.property_booking;
				row.purpose = a.purpose;
				row.building = a.building;
				row.unit = a.unit;
				row.sales_invoice = a.sales_invoice;
				row.allocated_amount = a.allocated_amount;
				frappe.set_route("Form", "PDC Entry", doc.name);
			});
		},
	});
}

function _open_advance_invoice(frm, purpose) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the booking before raising the invoice."));
		return;
	}
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.make_advance_invoice",
		args: { booking_name: frm.doc.name, purpose },
		freeze: true,
		freeze_message: __("Preparing invoice..."),
		callback(r) {
			if (!r.exc && r.message) frappe.set_route("Form", "Sales Invoice", r.message);
		},
	});
}

function _record_advance_payment(frm, purpose) {
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.make_advance_payment",
		args: { booking_name: frm.doc.name, purpose },
		freeze: true,
		freeze_message: __("Preparing payment entry..."),
		callback(r) {
			if (!r.exc && r.message) {
				// Open a fresh, unsaved Payment Entry pre-filled with all data.
				const doc = frappe.model.sync(r.message)[0];
				frappe.set_route("Form", doc.doctype, doc.name);
			}
		},
	});
}

// ── Cache tax rate for PDC Schedule inline calculation ───────────────────────
function _cache_tax_rate(frm, callback) {
	if (!frm.doc.taxes_and_charges && !frm.doc.unit) {
		frm._tax_rate = 0;
		if (callback) callback();
		return;
	}
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_tax_rate_from_template",
		args: {
			taxes_and_charges: frm.doc.taxes_and_charges || "",
			unit: frm.doc.unit || "",
		},
		callback(r) {
			frm._tax_rate = flt(r.message) || 0;
			if (callback) callback();
		},
	});
}

// ── PDC Schedule visual grouping ─────────────────────────────────────────────
function _style_pdc_schedule(frm) {
	const colors = {
		"Booking Amount":         "#dbeafe",
		"Down Payment":           "#dcfce7",
		"Installment":            "#ffffff",
		"Owners Association Fee": "#fef9c3",
	};
	setTimeout(() => {
		const grid = frm.fields_dict.pdc_schedule && frm.fields_dict.pdc_schedule.grid;
		if (!grid) return;
		const rows = frm.doc.pdc_schedule || [];

		// Build name → row map for reliable lookup (index-based breaks due to Frappe's extra grid rows)
		const rowMap = {};
		rows.forEach(r => { rowMap[r.name] = r; });

		grid.wrapper.find(".grid-row[data-name]").each(function() {
			const row = rowMap[$(this).data("name")];
			if (!row) return;
			$(this).find(".data-row").css("background-color", colors[row.installment_type] || "#fff");
		});

		// Border between type groups
		let prev_type = null;
		rows.forEach(row => {
			if (prev_type !== null && row.installment_type !== prev_type) {
				grid.wrapper.find(`.grid-row[data-name="${row.name}"]`)
					.find(".data-row").css("border-top", "2px solid #d1d5db");
			}
			prev_type = row.installment_type;
		});
	}, 400);
}


