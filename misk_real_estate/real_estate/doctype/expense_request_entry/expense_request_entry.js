// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Expense Request Entry", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on("Expense Request Entry", {
    onload(frm) {
        if (frm.is_new() && !frm.doc.company) {
            const company = frappe.defaults.get_user_default("company")
                || frappe.defaults.get_global_default("company");
            if (company) frm.set_value("company", company);
        }
    },

    refresh(frm) {
        if (frm.doc.docstatus === 1) {

            // Purchase Invoice
            frm.add_custom_button(__("Purchase Invoice"), function () {
                frappe.route_options = {
                    custom_expense_request: frm.doc.name
                };
                frappe.new_doc("Purchase Invoice");
            }, __("Create"));

            // Journal Entry
            frm.add_custom_button(__("Journal Entry"), function () {
                frappe.route_options = {
                    custom_expense_request: frm.doc.name
                };
                frappe.new_doc("Journal Entry");
            }, __("Create"));

            // Expense Entry — plain shortcut, no field to fetch/prefill
            frm.add_custom_button(__("Expense Entry"), function () {
                frappe.new_doc("Expense Entry");
            }, __("Create"));

        }
    },

    requested_by(frm) {
        if (!frm.doc.requested_by) {
            frm.set_value({
                department: "",
                employee_name: ""
            });
            return;
        }

        frappe.db.get_value(
            "Employee",
            frm.doc.requested_by,
            ["department", "employee_name"]
        ).then(({ message }) => {
            if (message) {
                frm.set_value({
                    department: message.department,
                    employee_name: message.employee_name
                });
            }
        });
    }
});