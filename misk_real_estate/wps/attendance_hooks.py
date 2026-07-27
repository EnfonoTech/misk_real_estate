# apps/misk_real_estate/misk_real_estate/wps/attendance_hooks.py

import frappe
from frappe.query_builder.functions import Sum


def validate(doc, method=None):
    if doc.project and doc.shift:
        return

    details = get_shift_assignment(doc.employee, doc.attendance_date)
    if not details:
        return
    if not doc.project:
        doc.project = details.project
    if not doc.shift:
        doc.shift = details.shift_type


@frappe.whitelist()
def get_shift_assignment_details(employee, attendance_date):
    """Client-side counterpart to validate() above — lets the Attendance form
    fill Project/Shift live as the user picks employee/date, instead of only
    on save."""
    return get_shift_assignment(employee, attendance_date)


def get_shift_assignment(employee, date):
    """The Shift Assignment (submitted, Active) covering `date` for
    `employee`, or None. Project lives on Shift Assignment (a custom field
    added there) alongside its own shift_type, so one lookup resolves both —
    no separate Employee Project Assignment doctype needed."""
    assignment = frappe.qb.DocType("Shift Assignment")
    result = (
        frappe.qb.from_(assignment)
        .select(assignment.shift_type, assignment.project)
        .where(assignment.employee == employee)
        .where(assignment.docstatus == 1)
        .where(assignment.status == "Active")
        .where(assignment.start_date <= date)
        .where((assignment.end_date.isnull()) | (assignment.end_date >= date))
        .orderby(assignment.start_date, order=frappe.qb.desc)
        .limit(1)
    ).run(as_dict=True)
    return result[0] if result else None


def get_employees_assigned_to_project(project, date):
    """All employees whose active Shift Assignment on `date` is to `project`."""
    assignment = frappe.qb.DocType("Shift Assignment")
    rows = (
        frappe.qb.from_(assignment)
        .select(assignment.employee)
        .where(assignment.project == project)
        .where(assignment.docstatus == 1)
        .where(assignment.status == "Active")
        .where(assignment.start_date <= date)
        .where((assignment.end_date.isnull()) | (assignment.end_date >= date))
    ).run(as_dict=True)
    return [row.employee for row in rows]


def set_salary_slip_overtime_hours(doc, method=None):
    """Salary Slip validate hook — keeps overtime_hours in sync with submitted
    Attendance over the slip's own pay period, so it always reflects the
    period actually being paid rather than a value entered once and left
    stale."""
    doc.overtime_hours = get_total_overtime_hours(doc.employee, doc.start_date, doc.end_date)


def get_employees_assigned_to_shift(shift, date):
    """All employees whose active Shift Assignment on `date` is to `shift`."""
    assignment = frappe.qb.DocType("Shift Assignment")
    rows = (
        frappe.qb.from_(assignment)
        .select(assignment.employee)
        .where(assignment.shift_type == shift)
        .where(assignment.docstatus == 1)
        .where(assignment.status == "Active")
        .where(assignment.start_date <= date)
        .where((assignment.end_date.isnull()) | (assignment.end_date >= date))
    ).run(as_dict=True)
    return [row.employee for row in rows]


def get_total_overtime_hours(employee, start_date, end_date):
    """Sum of submitted Attendance.overtime_hours for `employee` between
    `start_date` and `end_date` (inclusive) — shared by Salary Slip's own
    overtime_hours field and the WPS Report's Extra hours column, so both
    always agree."""
    attendance = frappe.qb.DocType("Attendance")
    result = (
        frappe.qb.from_(attendance)
        .select(Sum(attendance.overtime_hours).as_("total"))
        .where(attendance.employee == employee)
        .where(attendance.docstatus == 1)
        .where(attendance.attendance_date >= start_date)
        .where(attendance.attendance_date <= end_date)
    ).run(as_dict=True)
    return result[0].total or 0 if result else 0


@frappe.whitelist()
def get_shift_hours(shift):
    """A shift's normal working hours (end_time - start_time), handling an
    overnight shift where end_time wraps past midnight. Used to default
    Working Hours and to derive overtime_hours = max(0, worked hours - this)
    — defaults the user can still freely overwrite by hand."""
    if not shift:
        return 0

    start_time, end_time = frappe.db.get_value("Shift Type", shift, ["start_time", "end_time"])
    if start_time is None or end_time is None:
        return 0

    seconds = (end_time - start_time).total_seconds()
    if seconds < 0:
        seconds += 24 * 3600
    return round(seconds / 3600, 2)
