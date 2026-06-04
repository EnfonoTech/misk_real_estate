// Item form — Misk Real Estate
// Auto-generates item_code from item_group (building) + item_name (unit no.)
// Format: BUILDING-PREFIX-UNITNO  e.g. FURATH-F9, MISK-WALK-SH-1

frappe.ui.form.on("Item", {
	item_group(frm) {
		_suggest_item_code(frm);
	},

	item_name(frm) {
		_suggest_item_code(frm);
	},
});

function _suggest_item_code(frm) {
	if (!frm.is_new()) return;

	const group = (frm.doc.item_group || "").trim();
	const unit  = (frm.doc.item_name  || "").trim();
	if (!group || !unit) return;

	const prefix    = group.toUpperCase().replace(/\s+/g, "-").substring(0, 10);
	const suggested = `${prefix}-${unit}`;

	// Only set if user hasn't manually typed something different
	const current = (frm.doc.item_code || "").trim();
	if (!current || current === unit) {
		frm.set_value("item_code", suggested);
	}
}
