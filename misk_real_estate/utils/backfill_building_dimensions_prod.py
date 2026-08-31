"""
One-off backfill for PRODUCTION: sets Project + Cost Center on Property
Booking (header + property_unit rows) from each unit's Building — reads
Item Group.project / Item Group.cost_center directly (same source
_fill_unit_dimensions() uses for new bookings), so this stays correct
automatically as long as the Building records are set up, no hardcoded
mapping to keep in sync.

Scope, deliberately narrow per explicit instruction: Property Booking only
(header + property_unit child rows) — NOT Sales Invoice Item, NOT GL Entry.

SAFE BY DEFAULT: run() only PREVIEWS counts, writes nothing. Pass apply=True
to actually perform the update once the preview counts look right.

Usage (from the production bench):
    bench --site <production-site> execute misk_real_estate.utils.backfill_building_dimensions_prod.run
    # review the printed counts, then:
    bench --site <production-site> execute misk_real_estate.utils.backfill_building_dimensions_prod.run --kwargs "{'apply': True}"
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

    seen_buildings = {}
    for r in rows:
        seen_buildings[r.building] = seen_buildings.get(r.building, 0) + 1

    building_dims = {}
    print("=== Buildings found on Property Booking Unit rows (production) ===")
    for building, count in sorted(seen_buildings.items()):
        project, cost_center = get_building_dimensions(building)
        building_dims[building] = (project, cost_center)
        status = f"-> ({project}, {cost_center})" if project and cost_center else "** Item Group has no project/cost_center set **"
        print(f"  {building}: {count} rows  {status}")

    resolvable_buildings = {b for b, (p, c) in building_dims.items() if p and c}
    to_update_rows = [r for r in rows if r.building in resolvable_buildings and not (r.project and r.cost_center)]
    print(f"\n{len(to_update_rows)} Property Booking Unit rows would be updated (of {len(rows)} total)")

    booking_buildings = {}
    for r in rows:
        booking_buildings.setdefault(r.booking, set()).add(r.building)
    single_building_bookings = {b: bl for b, bl in booking_buildings.items() if len(bl) == 1}
    print(f"{len(single_building_bookings)} bookings resolve to a single building "
          f"(eligible for header project/cost_center fill); "
          f"{len(booking_buildings) - len(single_building_bookings)} span multiple buildings (header left as-is)")

    if not apply:
        print("\nDRY RUN ONLY — nothing written. Re-run with apply=True to perform the update.")
        return

    updated_rows = 0
    for r in to_update_rows:
        project, cost_center = building_dims[r.building]
        updates = {}
        if not r.project:
            updates["project"] = project
        if not r.cost_center:
            updates["cost_center"] = cost_center
        frappe.db.set_value("Property Booking Unit", r.row_name, updates, update_modified=False)
        updated_rows += 1
    print(f"\nUpdated {updated_rows} Property Booking Unit rows")

    headers = frappe.db.get_all(
        "Property Booking",
        filters={"name": ("in", list(single_building_bookings.keys()))},
        fields=["name", "project", "cost_center"],
    )
    updated_headers = 0
    for h in headers:
        if h.project and h.cost_center:
            continue
        building = next(iter(single_building_bookings[h.name]))
        if building not in resolvable_buildings:
            continue
        project, cost_center = building_dims[building]
        updates = {}
        if not h.project:
            updates["project"] = project
        if not h.cost_center:
            updates["cost_center"] = cost_center
        if updates:
            frappe.db.set_value("Property Booking", h.name, updates, update_modified=False)
            updated_headers += 1
    print(f"Updated {updated_headers} Property Booking headers")

    frappe.db.commit()
    print("done")
