"""
One-off correction for two batches of data-entry mistakes, both supplied as
spreadsheets by the business:

  A. "MW 152 - For changes in Misk Real Estate"
     Unit MISK-WALLK-SH-152 was booked at 14,720 but the price is 14,220. The
     500 difference is taken out of the tail of the PDC schedule: one cheque
     drops 90 -> 40 (and is renumbered), and four later cheques (90+90+90+180
     = 450) were never real and come out altogether. 50 + 450 = 500, so the
     schedule still reconciles against the corrected price and
     table_difference stays at 0.

  B. "To rectify the date"
     Twelve PDC rows were typed with the wrong YEAR (2026 instead of 2027 or
     2028; one also has the wrong day/month). Each sits visibly out of
     sequence in its own booking's otherwise monthly schedule, which is how
     each was confirmed rather than guessed.

     The damage is not the date itself: because the rows looked due, the
     auto-invoice cron raised a Sales Invoice for every one of them, 1-2
     years early. All twelve are submitted, Overdue and completely unpaid -
     OMR 6,989 of receivables that should not exist yet. So each correction
     also cancels that invoice and unlinks it, which lets the cron raise a
     fresh, correct invoice when the real date finally arrives.

WHY DIRECT DB WRITES: every booking here is submitted (docstatus 1), as are
the Sales Agreements that mirror the same PDC Schedule rows. Cancel/amend
would renumber the bookings and their agreements for what is a correction of
typed data, not a change of business terms. These writes use
update_modified=False for the same reason: nobody edited these documents, a
mistake is being undone.

SAFE BY DEFAULT: run() only PREVIEWS, writes nothing. Pass apply=True to
perform it. Everything is validated BEFORE anything is written, and the whole
run is one transaction - any surprise aborts the lot rather than leaving the
data half-corrected.

Usage:
    bench --site <site> execute misk_real_estate.utils.fix_mw152_and_cheque_dates.run
    # review, then:
    bench --site <site> execute misk_real_estate.utils.fix_mw152_and_cheque_dates.run --kwargs "{'apply': True}"
"""

import frappe
from frappe.utils import flt


# ── A. MW 152 ────────────────────────────────────────────────────────────────
MW152_BOOKING = "PB-2026-0249"
MW152_UNIT = "MISK-WALLK-SH-152"
MW152_OLD_PRICE, MW152_NEW_PRICE = 14720.0, 14220.0

# cheque_no -> (old amount, new amount, new cheque_no)
MW152_REVISE = {"00000485": (90.0, 40.0, "123")}
# cheques that were never real
MW152_DELETE = ["00000486", "00000480", "00000477", "00000498"]


# ── B. wrong-year cheque dates ───────────────────────────────────────────────
# (booking, schedule idx, cheque_no, current date, corrected date)
DATE_FIXES = [
    ("PB-2026-0340", 19, "92577293", "2026-07-27", "2027-07-27"),
    ("PB-2026-0340", 31, "92596954", "2026-06-27", "2028-06-27"),
    ("PB-2026-0340", 32, "92596959", "2026-06-27", "2028-06-27"),
    ("PB-2026-0340", 33, "92596960", "2026-06-27", "2028-06-27"),
    ("PB-2026-0062-1", 21, "07064454", "2026-08-28", "2027-08-28"),
    ("PB-2026-0073", 20, "00027840", "2026-07-28", "2027-07-28"),
    ("PB-2026-0099", 20, "92466370", "2026-08-28", "2027-08-28"),
    ("PB-2026-0267", 4, "123", "2026-06-11", "2028-11-30"),
    ("PB-2026-0009", 18, "30188769", "2026-08-28", "2027-08-28"),
    ("PB-2026-0010", 18, "81618369", "2026-08-28", "2027-08-28"),
    ("PB-2026-0013", 17, "01363168", "2026-08-28", "2027-08-28"),
    ("PB-2026-0020", 18, "123", "2026-08-28", "2027-08-28"),
]


class Abort(Exception):
    """A precondition failed — nothing is written."""


def _say(msg=""):
    print(msg)


def _agreement_rows(pdc_entry):
    """The Sales Agreement copies of a cheque's PDC Schedule row. An agreement
    mirrors its booking's schedule, so every edit below has to reach both or
    the signed contract and the booking stop agreeing."""
    return frappe.get_all(
        "PDC Schedule",
        filters={"pdc_entry": pdc_entry, "parenttype": "Sales Agreement"},
        fields=["name", "parent"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Planning — reads only, raises Abort on anything unexpected
# ──────────────────────────────────────────────────────────────────────────────

def _plan_mw152():
    plan = {"revise": [], "delete": [], "booking": MW152_BOOKING}

    unit = frappe.db.get_value(
        "Property Booking Unit",
        {"parent": MW152_BOOKING, "unit": MW152_UNIT},
        ["name", "unit_price"], as_dict=True,
    )
    if not unit:
        raise Abort(f"{MW152_UNIT} is not on {MW152_BOOKING}")
    if flt(unit.unit_price) == MW152_NEW_PRICE:
        _say(f"  NOTE: unit price is already {MW152_NEW_PRICE} — part A may have been applied already")
    elif flt(unit.unit_price) != MW152_OLD_PRICE:
        raise Abort(f"{MW152_UNIT} price is {unit.unit_price}, expected {MW152_OLD_PRICE}")
    plan["unit_row"] = unit.name

    for cheque, (old_amt, new_amt, new_no) in MW152_REVISE.items():
        row = _locate(MW152_BOOKING, cheque, expect_amount=old_amt)
        plan["revise"].append((row, new_amt, new_no))
    for cheque in MW152_DELETE:
        plan["delete"].append(_locate(MW152_BOOKING, cheque))

    removed = sum(flt(r["amount"]) for r in plan["delete"])
    reduced = sum(flt(r["amount"]) - new for r, new, _ in plan["revise"])
    drop = round(removed + reduced, 3)
    expected = round(MW152_OLD_PRICE - MW152_NEW_PRICE, 3)
    if drop != expected:
        raise Abort(f"schedule reduction {drop} does not match price drop {expected}")
    plan["drop"] = drop
    return plan


def _locate(booking, cheque_no, expect_amount=None):
    """The PDC Schedule row + PDC Entry for one cheque on one booking, with
    every reason it must not be touched checked up front."""
    rows = frappe.get_all(
        "PDC Schedule",
        filters={"parent": booking, "parenttype": "Property Booking", "cheque_no": cheque_no},
        fields=["name", "idx", "amount", "status", "pdc_entry", "sales_invoice", "cheque_date"],
    )
    if len(rows) != 1:
        raise Abort(f"{booking}: expected exactly 1 schedule row for cheque {cheque_no}, found {len(rows)}")
    r = rows[0]
    if r.status != "Pending":
        raise Abort(f"{booking} cheque {cheque_no}: status is {r.status}, only Pending rows may be changed")
    if r.sales_invoice:
        raise Abort(f"{booking} cheque {cheque_no}: already invoiced ({r.sales_invoice})")
    if expect_amount is not None and flt(r.amount) != flt(expect_amount):
        raise Abort(f"{booking} cheque {cheque_no}: amount is {r.amount}, expected {expect_amount}")

    entry = frappe.db.get_value(
        "PDC Entry", r.pdc_entry,
        ["name", "amount", "status", "gl_posted", "payment_entry", "batch", "cleared_amount"], as_dict=True,
    )
    if not entry:
        raise Abort(f"{booking} cheque {cheque_no}: PDC Entry {r.pdc_entry} missing")
    if entry.gl_posted or entry.payment_entry or flt(entry.cleared_amount) > 0:
        raise Abort(f"PDC Entry {entry.name}: money already posted against it")
    if entry.batch:
        raise Abort(f"PDC Entry {entry.name}: is in batch {entry.batch}")

    allocs = frappe.get_all("PDC Allocation", filters={"parent": entry.name},
                            fields=["name", "property_booking", "sales_invoice", "allocated_amount"])
    for a in allocs:
        if a.property_booking != booking:
            raise Abort(f"PDC Entry {entry.name} is shared with booking {a.property_booking}")
        if a.sales_invoice:
            raise Abort(f"PDC Entry {entry.name}: allocation already invoiced ({a.sales_invoice})")

    return {"row": r.name, "idx": r.idx, "cheque_no": cheque_no, "amount": r.amount,
            "cheque_date": r.cheque_date, "pdc_entry": entry.name, "allocs": [a.name for a in allocs],
            "agreement_rows": _agreement_rows(entry.name)}


def _plan_dates():
    plan = []
    for booking, idx, cheque_no, old, new in DATE_FIXES:
        rows = frappe.get_all(
            "PDC Schedule",
            filters={"parent": booking, "parenttype": "Property Booking", "idx": idx},
            fields=["name", "cheque_no", "cheque_date", "amount", "status", "pdc_entry", "sales_invoice"],
        )
        if len(rows) != 1:
            raise Abort(f"{booking} idx {idx}: expected 1 row, found {len(rows)}")
        r = rows[0]
        if r.cheque_no != cheque_no:
            raise Abort(f"{booking} idx {idx}: cheque is {r.cheque_no}, expected {cheque_no}")
        if str(r.cheque_date) != old:
            raise Abort(f"{booking} idx {idx}: date is {r.cheque_date}, expected {old}")
        if r.status != "Pending":
            raise Abort(f"{booking} idx {idx}: status is {r.status}, only Pending rows may be re-dated")

        inv = None
        if r.sales_invoice:
            si = frappe.db.get_value("Sales Invoice", r.sales_invoice,
                                     ["name", "docstatus", "outstanding_amount", "grand_total"], as_dict=True)
            if si and si.docstatus == 1:
                if flt(si.outstanding_amount) != flt(si.grand_total):
                    raise Abort(f"{si.name}: partly paid ({si.outstanding_amount} of {si.grand_total}) — "
                                "cancelling it would reverse a real receipt")
                paid = frappe.db.sql("""SELECT per.parent FROM `tabPayment Entry Reference` per
                    JOIN `tabPayment Entry` pe ON pe.name=per.parent
                    WHERE per.reference_name=%s AND pe.docstatus=1""", (si.name,))
                if paid:
                    raise Abort(f"{si.name}: has Payment Entries {paid}")
                inv = si
            elif si and si.docstatus == 2:
                inv = None  # already cancelled, just needs unlinking

        plan.append({
            "booking": booking, "idx": idx, "row": r.name, "cheque_no": cheque_no,
            "old": old, "new": new, "amount": r.amount, "pdc_entry": r.pdc_entry,
            "sales_invoice": r.sales_invoice, "cancel_invoice": inv,
            "allocs": frappe.get_all("PDC Allocation", filters={"parent": r.pdc_entry}, pluck="name"),
            "agreement_rows": _agreement_rows(r.pdc_entry),
        })
    return plan


# ──────────────────────────────────────────────────────────────────────────────
# Reporting + applying
# ──────────────────────────────────────────────────────────────────────────────

def run(apply=False):
    try:
        mw = _plan_mw152()
        dates = _plan_dates()
    except Abort as e:
        _say(f"\nABORTED — nothing written.\n  {e}")
        return

    _say("=" * 78)
    _say(f"A. MW 152 — {MW152_BOOKING} / {MW152_UNIT}")
    _say("=" * 78)
    _say(f"  unit price   {MW152_OLD_PRICE} -> {MW152_NEW_PRICE}   (schedule drops {mw['drop']}, matches)")
    for row, new_amt, new_no in mw["revise"]:
        _say(f"  REVISE idx={row['idx']:>2} cheque {row['cheque_no']} -> {new_no}, "
             f"amount {row['amount']} -> {new_amt}   [{row['pdc_entry']}]")
    for row in mw["delete"]:
        _say(f"  DELETE idx={row['idx']:>2} cheque {row['cheque_no']} amount {row['amount']}   "
             f"[{row['pdc_entry']}, +{len(row['agreement_rows'])} agreement row]")

    _say("")
    _say("=" * 78)
    _say("B. Wrong-year cheque dates")
    _say("=" * 78)
    total_si = 0.0
    for p in dates:
        note = ""
        if p["cancel_invoice"]:
            total_si += flt(p["cancel_invoice"].grand_total)
            note = f"  CANCEL {p['cancel_invoice'].name} ({p['cancel_invoice'].grand_total})"
        elif p["sales_invoice"]:
            note = f"  unlink {p['sales_invoice']} (already cancelled)"
        _say(f"  {p['booking']:<15} idx={p['idx']:>2} cheque {p['cheque_no']:<10} "
             f"{p['old']} -> {p['new']}  amt={p['amount']}{note}")
    _say(f"\n  {len(dates)} rows re-dated, OMR {round(total_si, 3)} of premature invoices cancelled")

    if not apply:
        _say("\nDRY RUN ONLY — nothing written. Re-run with apply=True to perform it.")
        return

    _apply(mw, dates)


def _apply(mw, dates):
    # ── A. MW 152 ────────────────────────────────────────────────────────────
    for row, new_amt, new_no in mw["revise"]:
        for table, name in [("PDC Schedule", row["row"])] + [("PDC Schedule", a["name"]) for a in row["agreement_rows"]]:
            frappe.db.set_value(table, name, {"amount": new_amt, "net_amount": new_amt,
                                              "cheque_no": new_no}, update_modified=False)
        frappe.db.set_value("PDC Entry", row["pdc_entry"], {"amount": new_amt, "cheque_no": new_no},
                            update_modified=False)
        for a in row["allocs"]:
            frappe.db.set_value("PDC Allocation", a, "allocated_amount", new_amt, update_modified=False)

    for row in mw["delete"]:
        for a in row["agreement_rows"]:
            frappe.db.delete("PDC Schedule", {"name": a["name"]})
        frappe.db.delete("PDC Schedule", {"name": row["row"]})
        # delete_doc runs PDC Entry.on_trash, which clears the batch/substitution
        # references for us and refuses outright if any GL was ever posted.
        frappe.delete_doc("PDC Entry", row["pdc_entry"], force=True, ignore_permissions=True)

    _renumber(MW152_BOOKING, "Property Booking")
    for sa in {a["parent"] for row in mw["delete"] for a in row["agreement_rows"]}:
        _renumber(sa, "Sales Agreement")

    frappe.db.set_value("Property Booking Unit", mw["unit_row"], "unit_price",
                        MW152_NEW_PRICE, update_modified=False)
    _resync_booking_totals(MW152_BOOKING)

    # ── B. dates ─────────────────────────────────────────────────────────────
    for p in dates:
        if p["cancel_invoice"]:
            si = frappe.get_doc("Sales Invoice", p["cancel_invoice"].name)
            si.flags.ignore_permissions = True
            si.cancel()
        for name in [p["row"]] + [a["name"] for a in p["agreement_rows"]]:
            frappe.db.set_value("PDC Schedule", name,
                                {"cheque_date": p["new"], "sales_invoice": None}, update_modified=False)
        frappe.db.set_value("PDC Entry", p["pdc_entry"], "cheque_date", p["new"], update_modified=False)
        for a in p["allocs"]:
            frappe.db.set_value("PDC Allocation", a, "sales_invoice", None, update_modified=False)

    frappe.db.commit()
    _say("\nApplied. Re-run without apply=True to confirm it now reports nothing to do.")


def _renumber(parent, parenttype):
    """Close the gaps left by deleted rows so idx stays 1..n, which is what the
    grid and every `order_by idx` read depends on."""
    rows = frappe.get_all("PDC Schedule", filters={"parent": parent, "parenttype": parenttype},
                          fields=["name"], order_by="idx")
    for i, r in enumerate(rows, start=1):
        frappe.db.set_value("PDC Schedule", r.name, "idx", i, update_modified=False)


def _resync_booking_totals(booking):
    """Recompute the stored roll-ups the booking shows, from the rows as they
    now stand. Done arithmetically rather than by re-saving: the document is
    submitted, and a save would re-run validate() over far more than the two
    things this script is allowed to change."""
    units = frappe.get_all("Property Booking Unit", filters={"parent": booking},
                           fields=["unit_price", "booking_amount", "down_payment_amount",
                                   "owners_association_fee"])
    total_price = sum(flt(u.unit_price) for u in units)
    oa = sum(flt(u.owners_association_fee) for u in units)
    expected = round(total_price - sum(flt(u.booking_amount) + flt(u.down_payment_amount) for u in units) + oa, 3)
    table_total = round(sum(flt(r.amount) for r in frappe.get_all(
        "PDC Schedule", filters={"parent": booking, "parenttype": "Property Booking"}, fields=["amount"])), 3)

    frappe.db.set_value("Property Booking", booking, {
        "total_unit_price": round(total_price, 3),
        "total_amount": round(total_price + oa, 3),
        "expected_table_total": expected,
        "table_total": table_total,
        "table_difference": round(table_total - expected, 3),
    }, update_modified=False)

    for sa in frappe.get_all("Sales Agreement", filters={"property_booking": booking}, pluck="name"):
        bk = frappe.db.get_value("Sales Agreement", sa, ["booking_amount", "down_payment_amount"], as_dict=True)
        frappe.db.set_value("Sales Agreement", sa, {
            "selling_price": round(total_price, 3),
            "balance_amount": round(total_price - flt(bk.booking_amount) - flt(bk.down_payment_amount), 3),
        }, update_modified=False)
