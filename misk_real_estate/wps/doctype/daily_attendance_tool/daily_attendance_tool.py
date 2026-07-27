# apps/misk_real_estate/misk_real_estate/wps/doctype/daily_attendance_tool/daily_attendance_tool.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from misk_real_estate.wps.attendance_hooks import (
    get_employees_assigned_to_project,
    get_employees_assigned_to_shift,
    get_shift_assignment,
    get_shift_hours,
)


class DailyAttendanceTool(Document):
    def validate(self):
        # Defensive backstop: total_hours is normally kept in sync client-side
        # as the user edits overtime_hours, but recompute here too in case a
        # row was added/changed via the API rather than the form.
        for row in self.employees:
            row.total_hours = flt(row.working_hours) + flt(row.overtime_hours)

        self._validate_leave_type()

    def _validate_leave_type(self):
        # leave_type's mandatory_depends_on (mirroring Attendance's own field)
        # is a client-side-only condition — Frappe's server-side mandatory
        # check only enforces plain reqd=1 fields, so an On Leave/Half Day row
        # would otherwise happily save (and go on to create an Attendance
        # with no leave_type) without this explicit check.
        for row in self.employees:
            if row.status in ("On Leave", "Half Day") and not row.leave_type:
                frappe.throw(
                    _("Row {0}: Leave Type is required when Status is {1}.").format(row.idx, row.status)
                )

    def before_submit(self):
        """Submitting IS marking attendance — builds and submits one
        Attendance per row in the same step, mirroring the Expense Entry
        submit-is-generate convention already used elsewhere in this app."""
        if not self.employees:
            frappe.throw(_("Add at least one employee row before submitting."))

        created, skipped = [], []
        for row in self.employees:
            if frappe.db.exists("Attendance", {
                "employee": row.employee,
                "attendance_date": self.attendance_date,
                "docstatus": ["!=", 2],
            }):
                skipped.append(row.employee_name or row.employee)
                continue

            attendance = frappe.get_doc({
                "doctype": "Attendance",
                "employee": row.employee,
                "attendance_date": self.attendance_date,
                "company": self.company,
                "status": row.status,
                "leave_type": row.leave_type,
                "project": row.project,
                "shift": row.shift,
                "working_hours": row.working_hours,
                "overtime_hours": row.overtime_hours,
                "daily_attendance_tool": self.name,
            })
            attendance.insert(ignore_permissions=True)
            attendance.submit()
            created.append(attendance.name)

        if not created:
            frappe.throw(
                _("No attendance was created — every selected employee already has attendance marked for {0}.").format(
                    self.attendance_date
                )
            )

        message = _("Marked attendance for {0} employee(s).").format(len(created))
        if skipped:
            message += "<br>" + _(
                "Skipped {0} employee(s) who already had attendance for this date: {1}"
            ).format(len(skipped), ", ".join(skipped))
        frappe.msgprint(message, title=_("Attendance Marked"), indicator="green")

    def on_cancel(self):
        for name in frappe.get_all(
            "Attendance",
            filters={"daily_attendance_tool": self.name, "docstatus": 1},
            pluck="name",
        ):
            frappe.get_doc("Attendance", name).cancel()


@frappe.whitelist()
def get_employees(company, attendance_date, employee_category=None, project=None, shift=None):
    filters = {"status": "Active", "company": company}
    if employee_category:
        filters["employee_category"] = employee_category

    employees = frappe.get_all(
        "Employee", filters=filters, fields=["name", "employee_name"]
    )

    if project:
        assigned = set(get_employees_assigned_to_project(project, attendance_date))
        employees = [e for e in employees if e.name in assigned]

    if shift:
        assigned = set(get_employees_assigned_to_shift(shift, attendance_date))
        employees = [e for e in employees if e.name in assigned]

    rows = []
    for emp in employees:
        details = get_shift_assignment(emp.name, attendance_date)
        shift = details.shift_type if details else None
        normal_hours = get_shift_hours(shift) if shift else 0
        rows.append({
            "employee": emp.name,
            "employee_name": emp.employee_name,
            "status": "Present",
            "project": details.project if details else None,
            "shift": shift,
            "working_hours": normal_hours,
            "overtime_hours": 0,
            "total_hours": normal_hours,
        })
    return rows
