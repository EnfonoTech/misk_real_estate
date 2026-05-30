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
# Runs monthly_long (1st of every month).
# Creates Sales Invoice for each PDC Schedule row due this month.
scheduler_events = {
    "monthly_long": [
        "misk_real_estate.pdc_management.cron.auto_invoice.run"
    ]
}

# ── Doc Events ────────────────────────────────────────────────────────────────
doc_events = {
    # PDC Entry on_update handled inside the controller class directly.
    # No external doc_events needed — controller's on_update fires automatically.
}

# ── Fixtures — run `bench export-fixtures` before every commit ────────────────
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            ["dt", "in", ["Payment Entry", "Sales Invoice", "Customer", "Employee", "Item"]]
        ]
    },
    {
        "dt": "Property Setter",
        "filters": [["doc_type", "in", ["Sales Order", "Property Booking", "Item"]]]
    },
    {
        "dt": "Workflow",
        "filters": [["document_type", "in", ["Property Booking"]]]
    },
    {
        "dt": "Role",
        "filters": [["name", "like", "Misk%"]]
    },
]

override_doctype_class = {}
