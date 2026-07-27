# apps/misk_real_estate/misk_real_estate/wps/report/wps_report/wps_report.py
"""
WPS Report — bank-file export for Wage Protection System payroll compliance.
Scoped by Employee.wps_company (which may differ from Employee.company), not
by Salary Slip's own operational company.
"""

import frappe
from frappe import _
from frappe.utils import flt

from misk_real_estate.wps.doctype.wps_settings.wps_settings import get_settings

FREQUENCY_CODE = {
    "Monthly": "M",
    "Fortnightly": "F",
    "Bimonthly": "B",
    "Weekly": "W",
    "Daily": "D",
}


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    summary = get_summary(data)
    return columns, data, None, None, summary


def get_columns():
    return [
        {"label": _("Employee ID Type"), "fieldname": "employee_id_type", "fieldtype": "Data", "width": 100},
        {"label": _("Employee ID"), "fieldname": "employee_id", "fieldtype": "Data", "width": 110},
        {"label": _("Reference Number"), "fieldname": "reference_number", "fieldtype": "Int", "width": 100},
        {"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 200},
        {"label": _("Employee BIC Code"), "fieldname": "employee_bic_code", "fieldtype": "Data", "width": 110},
        {"label": _("Employee Account"), "fieldname": "employee_account", "fieldtype": "Data", "width": 160},
        {"label": _("Salary Frequency"), "fieldname": "salary_frequency", "fieldtype": "Data", "width": 100},
        {"label": _("Number of Working days"), "fieldname": "number_of_working_days", "fieldtype": "Float", "width": 100},
        {"label": _("Net Salary"), "fieldname": "net_salary", "fieldtype": "Float", "width": 110},
        {"label": _("Basic Salary"), "fieldname": "basic_salary", "fieldtype": "Float", "width": 110},
        {"label": _("Extra hours"), "fieldname": "extra_hours", "fieldtype": "Float", "width": 90},
        {"label": _("Extra income"), "fieldname": "extra_income", "fieldtype": "Float", "width": 100},
        {"label": _("Deductions"), "fieldname": "deductions", "fieldtype": "Float", "width": 100},
        {"label": _("Social Security Deductions"), "fieldname": "social_security_deductions", "fieldtype": "Float", "width": 140},
        {"label": _("Notes / Comments"), "fieldname": "notes_comments", "fieldtype": "Data", "width": 150},
    ]


def get_data(filters):
    salary_slips = get_salary_slips(filters)
    if not salary_slips:
        return []

    earnings_map = get_component_map(salary_slips, "earnings")
    deductions_map = get_component_map(salary_slips, "deductions")

    settings = get_settings()
    basic_component = settings.basic_salary_component or "Basic"
    ss_component = settings.social_security_component

    rows = []
    for idx, slip in enumerate(salary_slips, start=1):
        earnings = earnings_map.get(slip.name, {})
        deductions = deductions_map.get(slip.name, {})

        basic_salary = flt(earnings.get(basic_component))
        extra_income = flt(slip.gross_pay) - basic_salary

        social_security = flt(deductions.get(ss_component)) if ss_component else 0.0
        other_deductions = flt(slip.total_deduction) - social_security

        rows.append({
            "employee_id_type": slip.employee_id_type or "",
            "employee_id": slip.civil_id or "",
            "reference_number": idx,
            "employee_name": slip.employee_name,
            "employee_bic_code": slip.bank_bic or "",
            "employee_account": slip.bank_account_no or slip.iban or "",
            "salary_frequency": FREQUENCY_CODE.get(slip.payroll_frequency, ""),
            "number_of_working_days": flt(slip.payment_days),
            "net_salary": flt(slip.net_pay),
            "basic_salary": basic_salary,
            "extra_hours": flt(slip.overtime_hours),
            "extra_income": extra_income,
            "deductions": other_deductions,
            "social_security_deductions": social_security,
            "notes_comments": "",
        })

    return rows


def get_salary_slips(filters):
    employee = frappe.qb.DocType("Employee")
    salary_slip = frappe.qb.DocType("Salary Slip")

    query = (
        frappe.qb.from_(salary_slip)
        .inner_join(employee)
        .on(salary_slip.employee == employee.name)
        .select(
            salary_slip.name,
            salary_slip.employee,
            salary_slip.employee_name,
            salary_slip.start_date,
            salary_slip.end_date,
            salary_slip.gross_pay,
            salary_slip.net_pay,
            salary_slip.total_deduction,
            salary_slip.payment_days,
            salary_slip.payroll_frequency,
            salary_slip.bank_account_no,
            salary_slip.overtime_hours,
            employee.iban,
            employee.employee_id_type,
            employee.civil_id,
            employee.bank_bic,
        )
        .where(salary_slip.docstatus == 1)
        .where(employee.wps_company == filters.get("wps_company"))
        .where(salary_slip.start_date >= filters.get("from_date"))
        .where(salary_slip.end_date <= filters.get("to_date"))
        .orderby(employee.employee_name)
    )
    return query.run(as_dict=True)


def get_component_map(salary_slips, parentfield):
    salary_detail = frappe.qb.DocType("Salary Detail")
    slip_names = [s.name for s in salary_slips]

    rows = (
        frappe.qb.from_(salary_detail)
        .select(salary_detail.parent, salary_detail.salary_component, salary_detail.amount)
        .where(salary_detail.parent.isin(slip_names))
        .where(salary_detail.parentfield == parentfield)
    ).run(as_dict=True)

    component_map = {}
    for row in rows:
        component_map.setdefault(row.parent, {})
        component_map[row.parent][row.salary_component] = (
            component_map[row.parent].get(row.salary_component, 0.0) + flt(row.amount)
        )
    return component_map


def get_summary(data):
    if not data:
        return []
    missing_bic = sum(1 for r in data if not r["employee_bic_code"])
    missing_id = sum(1 for r in data if not r["employee_id"])
    summary = [
        {"label": _("Total Employees"), "value": len(data), "datatype": "Int"},
        {"label": _("Total Net Salary"), "value": sum(r["net_salary"] for r in data), "datatype": "Currency"},
    ]
    if missing_bic:
        summary.append({"label": _("Missing BIC Code"), "value": missing_bic, "datatype": "Int", "color": "red"})
    if missing_id:
        summary.append({"label": _("Missing Employee ID"), "value": missing_id, "datatype": "Int", "color": "red"})
    return summary
