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
			// Make sure at least one editable unit row exists — more can be added.
			if (!(frm.doc.property_unit || []).length) {
				frm.add_child("property_unit");
				frm.refresh_field("property_unit");
			}
		}
		// Cache tax rate from existing taxes_and_charges
		if (frm.doc.taxes_and_charges) _cache_tax_rate(frm);

		// Limit Customer Bank Account to the selected customer's bank accounts
		frm.set_query("customer_bank_account", () => ({
			filters: { party_type: "Customer", party: frm.doc.customer || "" },
		}));
	},

	// Cheque No Prefix — auto-number every PDC row starting from this value, e.g.
	// entering "100" fills 100, 101, 102, ... (a trailing non-numeric prefix like
	// "CHQ-100" is kept fixed while "100" increments, zero-padding preserved).
	// A prefix with no trailing digits is just repeated on every row as-is.
	// Non-destructive: rows the user has hand-edited (value differs from what we
	// last auto-generated for that row) are left untouched.
	cheque_prefix(frm) {
		const raw = (frm.doc.cheque_prefix || "").trim();
		const match = raw.match(/^(.*?)(\d+)$/);
		const last = frm._last_generated_cheque_nos || {};
		const generated = {};

		(frm.doc.pdc_schedule || []).filter(r => r.is_pdc).forEach((r, i) => {
			let value = raw;
			if (match) {
				const [, prefixPart, numPart] = match;
				const next = String(parseInt(numPart, 10) + i).padStart(numPart.length, "0");
				value = prefixPart + next;
			}
			generated[r.name] = value;

			const cur = (r.cheque_no || "").trim();
			if (!cur || cur === last[r.name]) {
				frappe.model.set_value(r.doctype, r.name, "cheque_no", value);
			}
		});

		frm._last_generated_cheque_nos = generated;
		frm.refresh_field("pdc_schedule");
	},

	// ── Refresh — build action buttons based on state ─────────────────────────
	refresh(frm) {
		frm.trigger("set_unit_filter");

		// Advance payment buttons (Booking Amount / Down Payment) — only once the
		// booking has cleared the full approval workflow (Confirmed / docstatus 1).
		if (frm.doc.docstatus === 1) _add_advance_buttons(frm);

		// Mark Lost — release the reserved unit on a Draft that won't proceed
		if (frm.doc.docstatus === 0 && !frm.is_new() && frm.doc.status !== "Lost") {
			frm.add_custom_button(__("Mark Lost"), () => {
				frappe.confirm(
					__("Mark this booking as Lost and release unit(s) {0}?", [_all_units(frm)]),
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

		// PDC Schedule is locked (read-only) on the submitted form itself — Frappe
		// doesn't support unlocking a submitted child table for inline editing.
		// "Allow Edit" opens a dialog with an editable copy of the rows instead;
		// changes are applied server-side, blocked once any row has a PDC Entry
		// (server-enforced — see _validate_pdc_schedule_not_locked in property_booking.py).
		if (!has_pdc) {
			frm.add_custom_button(__("Allow Edit"), () => _edit_pdc_schedule(frm), __("PDC"));
		}

		// View PDC Entries — creates them on the fly if none exist yet, then opens the list.
		frm.add_custom_button(__("PDC Entries"), () => {
			frappe.call({
				method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_booking_pdc_entries",
				args: { booking_name: frm.doc.name },
				callback(r) {
					const names = r.message || [];
					if (names.length) {
						frappe.set_route("List", "PDC Entry", { name: ["in", names] });
						return;
					}
					frappe.call({
						method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.create_pdc_entries",
						args: { booking_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Creating PDC Entries..."),
						callback(r2) {
							if (r2.exc) return;
							const created = r2.message || [];
							if (!created.length) {
								frappe.msgprint(__("No PDC Entries for this booking yet."));
								return;
							}
							frappe.show_alert({
								message: __("{0} PDC Entries created.", [created.length]),
								indicator: "green"
							});
							frm.reload_doc();
							frappe.set_route("List", "PDC Entry", { name: ["in", created] });
						},
					});
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

		// Sales Agreement — generate once eligible (Booking Amount/Down Payment
		// fully received, every Installment/Management Fee PDC registered), or
		// open the existing one.
		_add_sales_agreement_button(frm);

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
					__("Mark unit(s) {0} as Sold? This cannot be undone.", [_all_units(frm)]),
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
		frm.set_query("unit", "property_unit", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			const filters = { unit_status: "Available" };
			if (row.building) filters["item_group"] = row.building;
			return { filters };
		});
	},

	pdc_schedule_add(frm)    { _check_pdc_total(frm); },
	pdc_schedule_remove(frm) { _check_pdc_total(frm); },
});

// ── Property Details — single-row table, mirrors Reservation's Units grid ────
frappe.ui.form.on("Property Booking Unit", {
	building(frm, cdt, cdn) {
		if (!frm._route_loading) {
			frappe.model.set_value(cdt, cdn, "unit", "");
			frappe.model.set_value(cdt, cdn, "unit_price", "");
		}
		frm.trigger("set_unit_filter");
	},

	unit(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		// Filter price_list to only those that have a price for this unit
		frm.set_query("price_list", "property_unit", () => ({
			query: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_price_lists_for_unit",
			filters: { unit: row.unit },
		}));
		if (!frm._route_loading) {
			frappe.model.set_value(cdt, cdn, "price_list", "");
			frappe.model.set_value(cdt, cdn, "unit_price", "");
		}
		// Reset tax cache — unit's Item Tax Template may differ
		frm._tax_rate = undefined;
		_cache_tax_rate(frm);
		_fetch_unit_price(frm, cdt, cdn);
	},

	price_list(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		_fetch_unit_price(frm, cdt, cdn);
		// Auto-fetch default down payment % from Price List
		if (row.price_list) {
			frappe.db.get_value("Price List", row.price_list, "down_payment_percentage", (r) => {
				if (r && r.down_payment_percentage) {
					frappe.model.set_value(cdt, cdn, "down_payment_percentage", r.down_payment_percentage);
				}
			});
		}
	},

	// ── Live calculation (row-scoped — these fields live on the unit row) ────
	unit_price(frm, cdt, cdn)     { _recalculate_row(frm, cdt, cdn); },
	booking_amount(frm, cdt, cdn) { _recalculate_row(frm, cdt, cdn); },
	payment_plan(frm, cdt, cdn)   { _recalculate_row(frm, cdt, cdn); },

	down_payment_percentage(frm, cdt, cdn) {
		// % of unit_price → calculate amount
		const row = locals[cdt][cdn];
		const price = flt(row.unit_price);
		const pct = flt(row.down_payment_percentage);
		if (!price || !pct) return;
		frappe.model.set_value(cdt, cdn, "down_payment_amount", flt((price * pct / 100).toFixed(3)));
		_recalc_installment_row(frm, cdt, cdn);
	},

	down_payment_amount(frm, cdt, cdn) {
		// Amount → back-calculate % against unit_price
		const row = locals[cdt][cdn];
		const price = flt(row.unit_price);
		const dp = flt(row.down_payment_amount);
		if (!price || !dp) return;
		frappe.model.set_value(cdt, cdn, "down_payment_percentage", flt((dp / price * 100).toFixed(3)));
		_recalc_installment_row(frm, cdt, cdn);
	},
});

function _recalc_installment_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const n = cint(row.number_of_installments);
	const price = flt(row.unit_price), booking = flt(row.booking_amount);
	const dp = flt(row.down_payment_amount);
	if (!n || !price) return;
	const after_dp = (price - booking) - dp;
	if (after_dp > 0) frappe.model.set_value(cdt, cdn, "monthly_installment", flt((after_dp / n).toFixed(3)));
}

function _recalculate_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const price = flt(row.unit_price);
	if (!price) return;

	// Down payment conversion — independent of payment plan, so changing
	// unit price / booking amount keeps the down payment in sync.
	const dp_amount = flt(row.down_payment_amount);
	const dp_pct = flt(row.down_payment_percentage);
	if (dp_amount > 0) {
		frappe.model.set_value(cdt, cdn, "down_payment_percentage", flt((dp_amount / price * 100).toFixed(3)));
	} else if (dp_pct > 0) {
		frappe.model.set_value(cdt, cdn, "down_payment_amount", flt((price * dp_pct / 100).toFixed(3)));
	}

	// Installments need a plan.
	if (!row.payment_plan) return;
	frappe.db.get_value("Payment Plan", row.payment_plan,
		["number_of_installments", "is_full_payment"], (r) => {
		if (!r) return;
		const booking = flt(row.booking_amount);

		const n = (!r.is_full_payment && r.number_of_installments) ? r.number_of_installments : 0;

		if (r.is_full_payment || n === 0) {
			frappe.model.set_value(cdt, cdn, "number_of_installments", 0);
			frappe.model.set_value(cdt, cdn, "down_payment_amount", 0);
			frappe.model.set_value(cdt, cdn, "down_payment_percentage", 0);
			frappe.model.set_value(cdt, cdn, "monthly_installment", 0);
			return;
		}

		frappe.model.set_value(cdt, cdn, "number_of_installments", n);
		const dp_pct = flt(row.down_payment_percentage) || 50;
		if (!row.down_payment_percentage) frappe.model.set_value(cdt, cdn, "down_payment_percentage", 50);
		const dp = flt((price * dp_pct / 100).toFixed(3));
		frappe.model.set_value(cdt, cdn, "down_payment_amount", dp);
		const after_dp = (price - booking) - dp;
		if (n > 0 && after_dp > 0) frappe.model.set_value(cdt, cdn, "monthly_installment", flt((after_dp / n).toFixed(3)));
	});
}

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
function _fetch_unit_price(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.unit) return;
	if (row.price_list) {
		frappe.db.get_value(
			"Item Price",
			{ item_code: row.unit, price_list: row.price_list },
			"price_list_rate",
			(r) => {
				if (r && r.price_list_rate) {
					frappe.model.set_value(cdt, cdn, "unit_price", r.price_list_rate);
				}
			}
		);
	} else {
		frappe.db.get_value("Item", row.unit, "standard_rate", (r) => {
			if (r && r.standard_rate) {
				frappe.model.set_value(cdt, cdn, "unit_price", r.standard_rate);
			}
		});
	}
}

// ── First unit row — used only as a fallback tax-rate source (mirrors the
// server's _get_unit_row()); most call sites should loop frm.doc.property_unit ──
function _get_unit_row(frm) {
	return (frm.doc.property_unit && frm.doc.property_unit[0]) || {};
}

function _all_units(frm) {
	return (frm.doc.property_unit || []).map(r => r.unit).filter(Boolean).join(", ");
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
// One combined invoice per purpose covers every unit on the booking, so one
// set of buttons per purpose (not per unit).
function _add_advance_buttons(frm) {
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_advance_invoice_status",
		args: { booking_name: frm.doc.name },
		callback(r) {
			if (r.exc) return;
			const status_by_purpose = r.message || {};
			const grp = __("Advance Payments");

			const block = (amount, purpose, invoiceLabel, paymentLabel) => {
				if (flt(amount) <= 0) return;
				const si = status_by_purpose[purpose];
				frm.add_custom_button(si ? __("Open " + invoiceLabel) : __(invoiceLabel),
					() => _open_advance_invoice(frm, purpose), grp);
				if (si) {
					frm.add_custom_button(__(paymentLabel),
						() => _record_advance_payment(frm, purpose), grp);
				}
			};

			block(frm.doc.total_booking_amount, "Booking Amount", "Booking Amount Invoice", "Record Booking Payment");
			block(frm.doc.total_down_payment_amount, "Down Payment", "Down Payment Invoice", "Record Down Payment");
		},
	});
}

// ── Sales Agreement (Contract Generation) ─────────────────────────────────────
function _add_sales_agreement_button(frm) {
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_sales_agreement",
		args: { booking_name: frm.doc.name },
		callback(r) {
			if (r.exc) return;
			const existing = r.message;
			if (existing) {
				frm.add_custom_button(__("Sales Agreement"), () => {
					frappe.set_route("Form", "Sales Agreement", existing);
				}, __("View"));
				return;
			}
			frm.add_custom_button(__("Generate Sales Agreement"), () => {
				frappe.call({
					method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.create_sales_agreement",
					args: { booking_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Checking eligibility..."),
					callback(res) {
						if (!res.exc && res.message) {
							frappe.set_route("Form", "Sales Agreement", res.message);
						}
					},
				});
			}, __("Actions"));
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
	const unit = _get_unit_row(frm).unit;
	if (!frm.doc.taxes_and_charges && !unit) {
		frm._tax_rate = 0;
		if (callback) callback();
		return;
	}
	frappe.call({
		method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.get_tax_rate_from_template",
		args: {
			taxes_and_charges: frm.doc.taxes_and_charges || "",
			unit: unit || "",
		},
		callback(r) {
			frm._tax_rate = flt(r.message) || 0;
			if (callback) callback();
		},
	});
}

// ── PDC Schedule edit (post-submit) ──────────────────────────────────────────
// The submitted form's own PDC Schedule grid can't be unlocked for inline
// editing (Frappe always renders a submitted child table read-only). Instead,
// open a dialog with an independent editable copy of the rows and push
// changes back through a dedicated server call — blocked once any row has a
// PDC Entry (see _validate_pdc_schedule_not_locked / update_pdc_schedule in
// property_booking.py).
function _edit_pdc_schedule(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Edit PDC Schedule"),
		size: "extra-large",
		fields: [{
			fieldname: "pdc_rows",
			fieldtype: "Table",
			label: __("PDC Schedule"),
			cannot_add_rows: true,
			cannot_delete_rows: true,
			in_place_edit: false,
			fields: [
				{ fieldname: "row_name", fieldtype: "Data", hidden: 1 },
				{ fieldname: "unit", label: __("Unit"), fieldtype: "Data", read_only: 1, in_list_view: 1 },
				{ fieldname: "installment_type", label: __("Type"), fieldtype: "Select",
					options: "Booking Amount\nDown Payment\nInstallment\nOwners Association Fee",
					in_list_view: 1, columns: 2 },
				{ fieldname: "cheque_date", label: __("Cheque Date"), fieldtype: "Date", in_list_view: 1 },
				{ fieldname: "cheque_no", label: __("Cheque No"), fieldtype: "Data", in_list_view: 1 },
				{ fieldname: "amount", label: __("Total Amount"), fieldtype: "Currency", in_list_view: 1 },
			],
			data: (frm.doc.pdc_schedule || []).map((r) => ({
				row_name: r.name,
				unit: r.unit,
				installment_type: r.installment_type,
				cheque_date: r.cheque_date,
				cheque_no: r.cheque_no,
				amount: r.amount,
			})),
		}],
		primary_action_label: __("Save"),
		primary_action(values) {
			frappe.call({
				method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.update_pdc_schedule",
				args: { booking_name: frm.doc.name, rows: values.pdc_rows },
				freeze: true,
				freeze_message: __("Updating PDC Schedule..."),
				callback(r) {
					if (!r.exc) {
						dialog.hide();
						frappe.show_alert({ message: __("PDC Schedule updated."), indicator: "green" });
						frm.reload_doc();
					}
				},
			});
		},
	});
	dialog.show();
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
			// Down Payment / OA Fee rows are still generated, still invoiced (cron /
			// All-at-Once) and still get PDC Entries — only hidden here so this table
			// reads as pure cheque-Installment schedule. Edit via "Allow Edit" dialog
			// or the Cheque Prefix auto-fill still reach every row regardless.
			if (row.installment_type !== "Installment") {
				$(this).hide();
				return;
			}
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


