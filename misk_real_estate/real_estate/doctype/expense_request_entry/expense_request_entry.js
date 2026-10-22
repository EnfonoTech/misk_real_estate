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
        // Company-scoped pickers. frm.doc.company is read INSIDE each callback
        // on purpose: set_query callbacks are re-evaluated every time the link
        // field is opened, so this tracks whatever company is on the form right
        // now. Capturing it in a `const` out here instead would freeze it at the
        // value present when refresh last ran — on a new document, the session
        // default applied in onload — and the pickers would keep offering that
        // company's records after the user picked a different one.
        frm.set_query("requested_by", () => ({ filters: { company: frm.doc.company || "" } }));
        frm.set_query("department", () => ({ filters: { company: frm.doc.company || "" } }));
        frm.set_query("project", () => ({ filters: { company: frm.doc.company || "" } }));

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

    // Switching company invalidates every selection made against the old one.
    // Clearing beats leaving another company's employee or project sitting on
    // the form. Nothing to clear on a new document, so this is a no-op for the
    // onload default. Clearing requested_by also blanks department and
    // employee_name through the handler below.
    company(frm) {
        ["requested_by", "department", "project"].forEach((field) => {
            if (frm.doc[field]) frm.set_value(field, "");
        });
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