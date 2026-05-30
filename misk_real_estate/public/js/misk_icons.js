// Inject custom Misk Real Estate SVG icons into Frappe's icon sprite at runtime.
// Referenced as icon name "misk-tower" in Workspace documents.

(function injectMiskIcons() {
	const ICON_ID = "icon-misk-tower";

	function inject() {
		// Don't inject twice
		if (document.getElementById(ICON_ID)) return;

		// Find or create the hidden SVG sprite container Frappe uses
		let sprite = document.querySelector("svg#frappe-symbols, svg.frappe-icons, body > svg[style*='display:none'], body > svg[style*='display: none']");
		if (!sprite) {
			sprite = document.createElementNS("http://www.w3.org/2000/svg", "svg");
			sprite.setAttribute("style", "display:none;");
			sprite.setAttribute("xmlns", "http://www.w3.org/2000/svg");
			document.body.prepend(sprite);
		}

		const symbol = document.createElementNS("http://www.w3.org/2000/svg", "symbol");
		symbol.setAttribute("id", ICON_ID);
		symbol.setAttribute("viewBox", "0 0 24 24");
		symbol.setAttribute("xmlns", "http://www.w3.org/2000/svg");
		symbol.innerHTML = `
			<path d="M5 22V5a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17"
				stroke="var(--icon-stroke)" stroke-width="1.5"
				stroke-linecap="round" stroke-linejoin="round" fill="none"/>
			<path d="M3 22h18"
				stroke="var(--icon-stroke)" stroke-width="1.5"
				stroke-linecap="round"/>
			<path d="M12 4V2"
				stroke="var(--icon-stroke)" stroke-width="1.5"
				stroke-linecap="round"/>
			<rect x="7" y="8" width="3" height="3" rx="0.4"
				stroke="var(--icon-stroke)" stroke-width="1.2" fill="none"/>
			<rect x="14" y="8" width="3" height="3" rx="0.4"
				stroke="var(--icon-stroke)" stroke-width="1.2" fill="none"/>
			<rect x="7" y="14" width="3" height="3" rx="0.4"
				stroke="var(--icon-stroke)" stroke-width="1.2" fill="none"/>
			<rect x="14" y="14" width="3" height="3" rx="0.4"
				stroke="var(--icon-stroke)" stroke-width="1.2" fill="none"/>
			<path d="M10.5 22v-5h3v5"
				stroke="var(--icon-stroke)" stroke-width="1.2"
				stroke-linecap="round" stroke-linejoin="round" fill="none"/>
		`;
		sprite.appendChild(symbol);
	}

	// Run after DOM ready
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", inject);
	} else {
		inject();
	}

	// Also re-inject after Frappe desk loads (Frappe may rebuild DOM)
	if (typeof frappe !== "undefined" && frappe.router) {
		frappe.router.on("change", inject);
	} else {
		window.addEventListener("load", inject);
	}
})();
