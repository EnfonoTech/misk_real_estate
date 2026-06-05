# misk_real_estate hooks

app_name = "misk_real_estate"
app_title = "Misk Real Estate"
app_publisher = "Enfono Technologies"
app_description = "Real estate booking and PDC management for Misk Group"
app_email = "sayanth@enfono.com"
app_license = "mit"

# ── Assets ────────────────────────────────────────────────────────────────────
app_include_css = ["/assets/misk_real_estate/css/misk_real_estate.css"]
app_include_js  = ["/assets/misk_real_estate/js/misk_icons.js"]

# ── B3: PDC Auto-Invoice Scheduler ────────────────────────────────────────────
# Runs daily. The configured day-of-month is read from Misk Real Estate Settings
# (invoice_day, default 5) — auto_invoice.run() skips if today is not that day.
scheduler_events = {
    "daily_long": [
        "misk_real_estate.pdc_management.cron.auto_invoice.run"
    ]
}

# ── Doc Events ────────────────────────────────────────────────────────────────
doc_events = {
    "Quotation": {
        "validate": "misk_real_estate.real_estate.custom.quotation_hooks.validate",
    },
}

# ── Fixtures — run `bench export-fixtures` before every commit ────────────────
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            ["dt", "in", ["Payment Entry", "Sales Invoice", "Customer", "Employee", "Item", "Quotation", "Quotation Item"]]
        ]
    },
    {
        "dt": "Property Setter",
        "filters": [["doc_type", "in", ["Sales Order", "Property Booking", "Item", "Quotation Item"]]]
    },
    {
        "dt": "Workflow State",
        "filters": [["workflow_state_name", "in", [
            "Draft", "Pending Sales Approval", "Pending Finance Approval", "Confirmed", "Rejected"
        ]]]
    },
    {
        "dt": "Workflow",
        "filters": [["document_type", "in", ["Quotation"]]]
    },
    {
        "dt": "Role",
        "filters": [["name", "like", "Misk%"]]
    },
    {
        "dt": "Number Card",
        "filters": [["name", "like", "Misk%"]]
    },
    {
        "dt": "Payment Plan"
    },
    {
        "dt": "Unit Type"
    },
    {
        "dt": "Floor"
    },
    {
        "dt": "Workspace",
        "filters": [["name", "=", "Misk Real Estate"]]
    },
]

doctype_js = {
    "Quotation": "real_estate/custom/quotation.js",
    "Item":      "real_estate/custom/item.js",
}

doctype_list_js = {
    "Item": "real_estate/custom/item_list.js",
}

override_doctype_class = {}
