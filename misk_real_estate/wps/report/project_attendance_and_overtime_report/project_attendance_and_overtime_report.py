# apps/misk_real_estate/misk_real_estate/wps/report/project_attendance_and_overtime_report/project_attendance_and_overtime_report.py
"""
Project Attendance and Overtime Report — per employee/project totals (days
present + overtime hours) for a period, sourced from Attendance.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
        {"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
        {"label": _("Project"), "fieldname": "project", "fieldtype": "Data", "width": 140},
        {"label": _("Total Days"), "fieldname": "total_days", "fieldtype": "Float", "width": 100},
        {"label": _("Total Overtime Hours"), "fieldname": "total_overtime_hours", "fieldtype": "Float", "width": 140},
    ]


def get_data(filters):
    attendance = frappe.qb.DocType("Attendance")
    employee = frappe.qb.DocType("Employee")

    query = (
        frappe.qb.from_(attendance)
        .inner_join(employee)
        .on(attendance.employee == employee.name)
        .select(
            attendance.employee,
            employee.employee_name,
            attendance.project,
            attendance.status,
            attendance.overtime_hours,
        )
        .where(attendance.docstatus == 1)
        .where(attendance.company == filters.get("company"))
        .where(attendance.attendance_date >= filters.get("from_date"))
        .where(attendance.attendance_date <= filters.get("to_date"))
        .where(attendance.status.isin(["Present", "Half Day"]))
    )

    if filters.get("project"):
        query = query.where(attendance.project == filters.get("project"))
    if filters.get("employee"):
        query = query.where(attendance.employee == filters.get("employee"))

    rows = query.run(as_dict=True)

    grouped = {}
    for row in rows:
        project_label = row.project or _("(No Project)")
        key = (row.employee, project_label)
        if key not in grouped:
            grouped[key] = {
                "employee": row.employee,
                "employee_name": row.employee_name,
                "project": project_label,
                "total_days": 0.0,
                "total_overtime_hours": 0.0,
            }
        grouped[key]["total_days"] += 0.5 if row.status == "Half Day" else 1.0
        grouped[key]["total_overtime_hours"] += flt(row.overtime_hours)

    return sorted(grouped.values(), key=lambda r: (r["employee_name"] or "", r["project"]))
