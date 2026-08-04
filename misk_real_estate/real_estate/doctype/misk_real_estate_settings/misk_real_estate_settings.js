// apps/misk_real_estate/misk_real_estate/real_estate/doctype/misk_real_estate_settings/misk_real_estate_settings.js

frappe.ui.form.on("Misk Real Estate Settings", {
	setup(frm) {
		frm.set_query("income_account", "income_account_mapping", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				filters: {
					company: row.company || "",
					root_type: "Income",
					is_group: 0,
				},
			};
		});
	},
});
