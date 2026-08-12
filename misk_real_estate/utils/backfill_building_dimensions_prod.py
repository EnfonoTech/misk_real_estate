"""
One-off backfill for PRODUCTION: sets Project + Cost Center on Property
Booking (header + property_unit rows) from each unit's Building, using the
Project/Cost Center records that ALREADY exist in production (exported by
the user as Project.csv / "Cost Center (2).xlsx").

Scope, deliberately narrow per explicit instruction: Property Booking only
(header + property_unit child rows) — NOT Sales Invoice Item, NOT GL Entry.

SAFE BY DEFAULT: run() only PREVIEWS counts, writes nothing. Pass apply=True
to actually perform the update once the preview counts look right.

Usage (from the production bench):
    bench --site <production-site> execute misk_real_estate.utils.backfill_building_dimensions_prod.run
    # review the printed counts, then:
    bench --site <production-site> execute misk_real_estate.utils.backfill_building_dimensions_prod.run --kwargs "{'apply': True}"

IMPORTANT: BUILDING_MAP's keys must match the exact `building` value stored
on Property Booking Unit rows in production (the Item Group name) — this is
assumed to match misk.backup's naming (confirmed correct for "Misk Wallk"
earlier this session). If a building below shows 0 matched rows in the
preview but you know it should have bookings, the Item Group name in
production differs from the key here — fix the key and re-run before
passing apply=True.
"""

import frappe

# building (Item Group name, as stored on Property Booking Unit.building)
#   -> (Project ID, Cost Center ID)
# Values are the exact docnames from Project.csv / Cost Center (2).xlsx.
BUILDING_MAP = {
    "Souq Misk":       ("PROJ-0012", "MR-Souq Misk - MP"),
    "Azz":             ("PROJ-0011", "MR-Azz - MP"),
    "Reef":            ("PROJ-0009", "MR-Reef - MP"),
    "Misk Al Mawalah": ("PROJ-0010", "MR-Misk Mawalah - MP"),
    "Misk Wallk":      ("PROJ-0013", "MR-Misk Walk - MP"),
}


def run(apply=False):
    # Sanity-check the mapping targets actually exist before touching anything.
    for building, (project, cost_center) in BUILDING_MAP.items():
        if not frappe.db.exists("Project", project):
            print(f"WARNING: Project {project} (for {building}) does not exist — check BUILDING_MAP")
        if not frappe.db.exists("Cost Center", cost_center):
            print(f"WARNING: Cost Center {cost_center} (for {building}) does not exist — check BUILDING_MAP")

    rows = frappe.db.sql("""
        SELECT pbu.name AS row_name, pbu.parent AS booking, pbu.building AS building,
               pbu.project AS project, pbu.cost_center AS cost_center
        FROM `tabProperty Booking Unit` pbu
        WHERE pbu.building IS NOT NULL AND pbu.building != ''
    """, as_dict=True)

    seen_buildings = {}
    for r in rows:
        seen_buildings[r.building] = seen_buildings.get(r.building, 0) + 1

    print("=== Buildings found on Property Booking Unit rows (production) ===")
    for building, count in sorted(seen_buildings.items()):
        mapped = "-> " + str(BUILDING_MAP[building]) if building in BUILDING_MAP else "** NOT IN BUILDING_MAP **"
        print(f"  {building}: {count} rows  {mapped}")

    to_update_rows = [r for r in rows if r.building in BUILDING_MAP and not (r.project and r.cost_center)]
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
        project, cost_center = BUILDING_MAP[r.building]
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
        if building not in BUILDING_MAP:
            continue
        project, cost_center = BUILDING_MAP[building]
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
