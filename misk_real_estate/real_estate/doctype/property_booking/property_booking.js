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

		// Project / Cost Center — scoped to the booking's company, header + per-unit
		frm.set_query("project", () => ({ filters: { company: frm.doc.company || "" } }));
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company || "", is_group: 0 } }));
		frm.set_query("project", "property_unit", () => ({ filters: { company: frm.doc.company || "" } }));
		frm.set_query("cost_center", "property_unit", () => ({ filters: { company: frm.doc.company || "", is_group: 0 } }));

		// PDC Schedule row's Unit (post-submit reassignment) — only this booking's own units
		frm.set_query("unit", "pdc_schedule", () => ({
			filters: { name: ["in", (frm.doc.property_unit || []).map((r) => r.unit).filter(Boolean)] },
		}));
	},

	// First Installment Date — re-date every Installment row one month apart
	// starting from this date, e.g. setting 2026-03-01 fills 2026-03-01,
	// 2026-04-01, 2026-05-01, ... in row order. Owners Association Fee rows
	// move too — same convention as generate_pdc_schedule() itself (OA is
	// always due alongside the last installment) — so they're re-dated to
	// match the new last installment date, keeping that invariant intact.
	// Same non-destructive-within-session convention as cheque_prefix below:
	// a later date tweak leaves rows the user hand-edited since then alone,
	// but on the FIRST use per session (no baseline yet) applies to every row.
	first_installment_date(frm) {
		const base = frm.doc.first_installment_date;
		if (!base) return;
		const last = frm._last_generated_installment_dates;
		const generated = {};
		let last_installment_value = null;

		(frm.doc.pdc_schedule || []).filter(r => r.installment_type === "Installment").forEach((r, i) => {
			const value = frappe.datetime.add_months(base, i);
			generated[r.name] = value;
			last_installment_value = value;

			const cur = r.cheque_date;
			if (!last || !cur || cur === last[r.name]) {
				frappe.model.set_value(r.doctype, r.name, "cheque_date", value);
			}
		});

		if (last_installment_value) {
			(frm.doc.pdc_schedule || []).filter(r => r.installment_type === "Owners Association Fee").forEach(r => {
				generated[r.name] = last_installment_value;
				const cur = r.cheque_date;
				if (!last || !cur || cur === last[r.name]) {
					frappe.model.set_value(r.doctype, r.name, "cheque_date", last_installment_value);
				}
			});
		}

		// Only remember a baseline when there were actually rows to (re)date —
		// e.g. this field set BEFORE the very first save, while the PDC
		// Schedule table is still empty client-side (the server fills it in
		// on save instead — see generate_pdc_schedule). Recording an empty-
		// but-truthy {} here would make every future edit's `!last` fallback
		// never fire again this session, since `last[r.name]` is undefined
		// for every real row that shows up after that save.
		if (Object.keys(generated).length) {
			frm._last_generated_installment_dates = generated;
		}
		frm.refresh_field("pdc_schedule");
	},

	// Cheque No Prefix — auto-number every PDC row starting from this value, e.g.
	// entering "100" fills 100, 101, 102, ... (a trailing non-numeric prefix like
	// "CHQ-100" is kept fixed while "100" increments, zero-padding preserved).
	// A prefix with no trailing digits is just repeated on every row as-is.
	// Non-destructive ONLY within the same page session: once we've auto-filled
	// once here, a later prefix tweak leaves rows the user hand-edited since
	// then untouched. `_last_generated_cheque_nos` doesn't survive a reload, so
	// on the FIRST use per session (e.g. opening an already-submitted booking,
	// which always already has real cheque numbers from submit time) there's no
	// baseline to compare against — apply to every row rather than treating
	// pre-existing values as "hand-edited" and silently skipping all of them.
	cheque_prefix(frm) {
		const raw = (frm.doc.cheque_prefix || "").trim();
		const match = raw.match(/^(.*?)(\d+)$/);
		const last = frm._last_generated_cheque_nos;
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
			if (!last || !cur || cur === last[r.name]) {
				frappe.model.set_value(r.doctype, r.name, "cheque_no", value);
			}
		});

		// Same reasoning as first_installment_date above — don't record an
		// empty-but-truthy {} baseline when there were no rows yet to number.
		if (Object.keys(generated).length) {
			frm._last_generated_cheque_nos = generated;
		}
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

		// Create PDC Entries — manual trigger, mirrors the list-view bulk action
		// ("PDC Entries" under View does this too, on demand, then navigates —
		// this one is explicit/discoverable under Actions, matching the list view).
		const missing_pdc = (frm.doc.pdc_schedule || []).some(r => r.is_pdc && !r.pdc_entry && r.status !== "Cancelled");
		if (missing_pdc) {
			frm.add_custom_button(__("Create PDC Entries"), () => {
				frappe.confirm(
					__("Create PDC Entries for all PDC schedule rows that don't have one yet?"),
					() => {
						frappe.call({
							method: "misk_real_estate.real_estate.doctype.property_booking.property_booking.create_pdc_entries",
							args: { booking_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Creating PDC Entries..."),
							callback(r) {
								if (!r.exc) frm.reload_doc();
							},
						});
					}
				);
			}, __("Actions"));
		}

		// Create Missing Invoices — manual fallback when auto-creation failed or user wants draft
		// review. Covers both the combined Booking Amount/Down Payment advance invoices (can't
		// tell client-side whether one already exists, so this just checks something is owed —
		// the server-side call is a safe no-op if it's already invoiced) and due PDC rows.
		const missing_si = (frm.doc.pdc_schedule || []).some(r => !r.sales_invoice && r.status !== "Cancelled")
			|| (frm.doc.property_unit || []).some(r => flt(r.booking_amount) > 0 || flt(r.down_payment_amount) > 0);
		if (missing_si) {
			frm.add_custom_button(__("Create Missing Invoices"), () => {
				frappe.confirm(
					__("Create draft Sales Invoices for the Booking Amount/Down Payment (if not already invoiced) and any PDC row that doesn't have one yet? You can review and submit them before they become final."),
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

	// Booking-level Project/Cost Center/Payment Plan are the default for every
	// unit row — push into rows that don't already have their own value set.
	// Rows a user has explicitly overridden (or already inherited) are left
	// untouched.
	project(frm)       { _fill_blank_unit_field(frm, "project"); },
	cost_center(frm)   { _fill_blank_unit_field(frm, "cost_center"); },
	payment_plan(frm)  { _fill_blank_unit_field(frm, "payment_plan"); },

	// ── Unit filter — only show units in selected building + this booking's
	// own Company (unit's own company override, else its Building's) ─────────
	set_unit_filter(frm) {
		frm.set_query("unit", "property_unit", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			const filters = { unit_status: "Available" };
			if (row.building) filters["building"] = row.building;
			if (frm.doc.company) filters["company"] = frm.doc.company;
			return {
				query: "misk_real_estate.utils.company.get_units_for_company",
				filters,
			};
		});
	},

	// A manually added row has no declared default for Seq (unlike is_pdc,
	// which defaults to 1) — number it after the highest existing row so it
	// doesn't show 0.
	pdc_schedule_add(frm, cdt, cdn) {
		const max_seq = (frm.doc.pdc_schedule || []).reduce((m, r) => Math.max(m, cint(r.sequence_no)), 0);
		frappe.model.set_value(cdt, cdn, "sequence_no", max_seq + 1);
		_check_pdc_total(frm);
	},
	pdc_schedule_remove(frm) { _check_pdc_total(frm); },

	// New unit rows default to the booking's own Project/Cost Center/Payment
	// Plan — still overridable per row.
	property_unit_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.project) row.project = frm.doc.project;
		if (!row.cost_center) row.cost_center = frm.doc.cost_center;
		if (!row.payment_plan) row.payment_plan = frm.doc.payment_plan;
	},
});

function _fill_blank_unit_field(frm, fieldname) {
	(frm.doc.property_unit || []).forEach((row) => {
		if (!row[fieldname]) {
			frappe.model.set_value(row.doctype, row.name, fieldname, frm.doc[fieldname]);
		}
	});
}

// ── Property Details — single-row table, mirrors Reservation's Units grid ────
frappe.ui.form.on("Property Booking Unit", {
	building(frm, cdt, cdn) {
		if (!frm._route_loading) {
			frappe.model.set_value(cdt, cdn, "unit", "");
			frappe.model.set_value(cdt, cdn, "unit_price", "");
		}
		frm.trigger("set_unit_filter");

		// Default Project/Cost Center from the Building — only fills a blank,
		// mirrors the server-side fallback in _fill_unit_dimensions
		// (property_booking.py) so it shows immediately instead of waiting
		// for the next save.
		const row = locals[cdt][cdn];
		if (row.building && (!row.project || !row.cost_center)) {
			frappe.db.get_value("Item Group", row.building, ["project", "cost_center"], (r) => {
				if (!r) return;
				if (!row.project && r.project) frappe.model.set_value(cdt, cdn, "project", r.project);
				if (!row.cost_center && r.cost_center) frappe.model.set_value(cdt, cdn, "cost_center", r.cost_center);
			});
		}
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
		// % of unit_price → calculate amount. Guarded by _skip_dp_sync (see
		// down_payment_amount below) — without it, this and down_payment_amount
		// call each other back-to-back: typing an amount computes % (rounded to
		// 3dp), which immediately re-computes amount FROM that rounded %,
		// silently drifting the user's typed value (e.g. 16000 -> 15999.984).
		if (frm._skip_dp_sync) return;
		const row = locals[cdt][cdn];
		const price = flt(row.unit_price);
		const pct = flt(row.down_payment_percentage);
		if (!price || !pct) return;
		frm._skip_dp_sync = true;
		frappe.model.set_value(cdt, cdn, "down_payment_amount", flt((price * pct / 100).toFixed(3)))
			.then(() => { frm._skip_dp_sync = false; });
		_recalc_installment_row(frm, cdt, cdn);
	},

	down_payment_amount(frm, cdt, cdn) {
		// Amount → back-calculate % against unit_price. See down_payment_percentage
		// above for why _skip_dp_sync exists — it holds while the triggered
		// set_value's own change-event chain runs (set_value's trigger fires
		// async, so the flag must be cleared via .then(), not right after the
		// call) so the reverse handler doesn't bounce a rounded % back into a
		// slightly-off amount.
		if (frm._skip_dp_sync) return;
		const row = locals[cdt][cdn];
		const price = flt(row.unit_price);
		const dp = flt(row.down_payment_amount);
		if (!price || !dp) return;
		frm._skip_dp_sync = true;
		frappe.model.set_value(cdt, cdn, "down_payment_percentage", flt((dp / price * 100).toFixed(3)))
			.then(() => { frm._skip_dp_sync = false; });
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
	// unit price / booking amount keeps the down payment in sync. Same
	// _skip_dp_sync guard as the down_payment_amount/percentage handlers —
	// setting one here would otherwise trigger that field's own handler,
	// which would try to compute the other one right back.
	const dp_amount = flt(row.down_payment_amount);
	const dp_pct = flt(row.down_payment_percentage);
	if (dp_amount > 0) {
		frm._skip_dp_sync = true;
		frappe.model.set_value(cdt, cdn, "down_payment_percentage", flt((dp_amount / price * 100).toFixed(3)))
			.then(() => { frm._skip_dp_sync = false; });
	} else if (dp_pct > 0) {
		frm._skip_dp_sync = true;
		frappe.model.set_value(cdt, cdn, "down_payment_amount", flt((price * dp_pct / 100).toFixed(3)))
			.then(() => { frm._skip_dp_sync = false; });
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

// unit_breakdown is stored as a JSON string (see _combined_pdc_row in
// property_booking.py) — parse it into "UNIT-A, UNIT-B" for display on a
// combined row (unit field blank). Returns "" for single-unit rows.
function _units_for_pdc_row(row) {
	if (!row.unit_breakdown) return "";
	try {
		return JSON.parse(row.unit_breakdown).map((c) => c.unit).join(", ");
	} catch (e) {
		return "";
	}
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
			// Combined row (one cheque covering several units on the same due
			// date) — the header `unit` field is blank, so show the unit list
			// from unit_breakdown instead of a blank cell.
			const units = _units_for_pdc_row(row);
			if (!row.unit && units) {
				$(this).find('.grid-static-col[data-fieldname="unit"] .static-area').text(units);
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


