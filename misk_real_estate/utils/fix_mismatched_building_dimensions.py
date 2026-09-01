"""
One-off: finds and corrects Property Booking (header + property_unit rows)
whose project/cost_center don't match what their own Building (Item Group)
actually resolves to. This is the retroactive counterpart to the bug just
fixed in property_booking.py/js — a row's Building could be changed after
Project/Cost Center were already filled for a DIFFERENT building, leaving
the old building's values behind (confirmed live in production: a row
showing Building = REEF but Project/Cost Center = MR-Azz). The code fix
stops this going forward (self-heals on next save); this script corrects
whatever's already wrong right now.

A row is left alone whenever its Building has no project/cost_center
configured at all — nothing to judge a mismatch against.

SAFE BY DEFAULT: run() only PREVIEWS what it would change, writes nothing.
Pass apply=True to actually perform the correction.

Usage:
    bench --site <site> execute misk_real_estate.utils.fix_mismatched_building_dimensions.run
    # review the printed list, then:
    bench --site <site> execute misk_real_estate.utils.fix_mismatched_building_dimensions.run --kwargs "{'apply': True}"
"""

import frappe

from misk_real_estate.utils.company import get_building_dimensions


def run(apply=False):
    rows = frappe.db.sql("""
        SELECT pbu.name AS row_name, pbu.parent AS booking, pbu.building AS building,
               pbu.project AS project, pbu.cost_center AS cost_center
        FROM `tabProperty Booking Unit` pbu
        WHERE pbu.building IS NOT NULL AND pbu.building != ''
    """, as_dict=True)

    dims_cache = {}

    def dims(building):
        if building not in dims_cache:
            dims_cache[building] = get_building_dimensions(building)
        return dims_cache[building]

    mismatched_rows = []
    for r in rows:
        project, cost_center = dims(r.building)
        if not project or not cost_center:
            continue
        if r.project != project or r.cost_center != cost_center:
            mismatched_rows.append((r, project, cost_center))

    print(f"=== Property Booking Unit rows ===")
    print(f"{len(mismatched_rows)} mismatched (of {len(rows)} total with a Building set)")
    for r, project, cost_center in mismatched_rows[:50]:
        print(f"  {r.booking} / {r.building}: has ({r.project}, {r.cost_center}) -> should be ({project}, {cost_center})")

    # Header-level: only for bookings whose units all resolve to ONE building
    # (matches _fill_unit_dimensions' own scoping — a booking spanning
    # several buildings has no single correct header value).
    booking_buildings = {}
    for r in rows:
        booking_buildings.setdefault(r.booking, set()).add(r.building)
    single_building_bookings = {b: next(iter(bl)) for b, bl in booking_buildings.items() if len(bl) == 1}

    headers = frappe.db.get_all(
        "Property Booking",
        filters={"name": ("in", list(single_building_bookings.keys()))},
        fields=["name", "project", "cost_center"],
    )
    mismatched_headers = []
    for h in headers:
        project, cost_center = dims(single_building_bookings[h.name])
        if not project or not cost_center:
            continue
        if h.project != project or h.cost_center != cost_center:
            mismatched_headers.append((h, project, cost_center))

    print(f"\n=== Property Booking headers ===")
    print(f"{len(mismatched_headers)} mismatched")
    for h, project, cost_center in mismatched_headers[:50]:
        print(f"  {h.name}: has ({h.project}, {h.cost_center}) -> should be ({project}, {cost_center})")

    if not apply:
        print("\nDRY RUN ONLY — nothing written. Re-run with apply=True to perform the correction.")
        return

    for r, project, cost_center in mismatched_rows:
        frappe.db.set_value(
            "Property Booking Unit", r.row_name,
            {"project": project, "cost_center": cost_center}, update_modified=False,
        )
    for h, project, cost_center in mismatched_headers:
        frappe.db.set_value(
            "Property Booking", h.name,
            {"project": project, "cost_center": cost_center}, update_modified=False,
        )

    frappe.db.commit()
    print(f"\nCorrected {len(mismatched_rows)} unit rows and {len(mismatched_headers)} headers")
