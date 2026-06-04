// Item list view — Misk Real Estate
// "Import Buildings & Units from Excel" button with template download inside the dialog.

frappe.listview_settings["Item"] = frappe.listview_settings["Item"] || {};

const _original_onload = frappe.listview_settings["Item"].onload;

frappe.listview_settings["Item"].onload = function(listview) {
	if (_original_onload) _original_onload(listview);

	listview.page.add_button(__("Import Buildings & Units"), function() {
		const d = new frappe.ui.Dialog({
			title: __("Import Buildings & Units from Excel"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<div style="margin-bottom:8px">
						<button class="btn btn-default btn-sm" id="misk-dl-template">
							${__("Download Template")}
						</button>
					</div>`,
				},
				{
					fieldname: "file",
					fieldtype: "Attach",
					label: __("Excel File (.xlsx)"),
					reqd: 1,
				},
			],
			primary_action_label: __("Import"),
			primary_action(values) {
				d.hide();
				frappe.call({
					method: "misk_real_estate.utils.import_units.run_from_file",
					args: { file_url: values.file },
					freeze: true,
					freeze_message: __("Importing buildings and units..."),
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: r.message || __("Import completed."),
								indicator: "green",
							});
							listview.refresh();
						}
					},
				});
			},
		});

		d.show();

		// Wire up the template download link after dialog renders
		d.$wrapper.find("#misk-dl-template").on("click", function(e) {
			e.preventDefault();
			window.open(
				frappe.urllib.get_full_url(
					"/api/method/misk_real_estate.utils.import_units.get_import_template"
				),
				"_blank"
			);
		});
	});
};
