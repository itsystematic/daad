// DaaD: translate desk navigation labels that Frappe renders without __().
// Covers the module dock (tooltips and labels) and sidebar items / section headings.
(function () {
	const tr = (s) => (typeof s === "string" && s && typeof __ === "function" ? __(s) : s);

	function patch() {
		const ui = window.frappe && frappe.ui;
		if (!ui || !ui.Sidebar || !ui.Dock) return false;

		const S = ui.Sidebar.prototype;
		if (!S.__daad_i18n) {
			const dock_entry = S.dock_entry;
			if (dock_entry) {
				S.dock_entry = function (row) {
					const entry = dock_entry.call(this, row);
					if (entry && entry.label) entry.label = tr(entry.label);
					return entry;
				};
			}
			const make_item = S.make_sidebar_item;
			if (make_item) {
				S.make_sidebar_item = function (opts) {
					const item = opts && opts.item;
					if (item && item.label && !item.__daad_tr) {
						item.label = tr(item.label);
						item.__daad_tr = 1;
					}
					return make_item.call(this, opts);
				};
			}
			S.__daad_i18n = 1;
		}

		const D = ui.Dock.prototype;
		if (!D.__daad_i18n) {
			const name_tile = D.name_tile;
			if (name_tile) {
				D.name_tile = function ($el, label) {
					return name_tile.call(this, $el, tr(label));
				};
			}
			const module_logo = D.module_logo;
			if (module_logo) {
				D.module_logo = function () {
					const logo = module_logo.call(this);
					if (logo && logo.title) logo.title = tr(logo.title);
					return logo;
				};
			}
			D.__daad_i18n = 1;
		}
		return true;
	}

	// Core strings Frappe builds without __() (filter counter, tree level, search button title)
	function fixAttrs(root) {
		if (!root || !root.querySelectorAll) return;
		root.querySelectorAll('[title],[aria-label]').forEach((el) => {
			["title", "aria-label"].forEach((a) => {
				const v = el.getAttribute(a);
				if (!v || /[؀-ۿ]/.test(v)) return;
				let m = v.match(/^(\d+) Filters? Applied$/);
				let out = null;
				if (m) {
					const n = +m[1];
					out = n + " " + tr(n > 1 ? "Filters" : "Filter") + (n > 1 ? " مطبقة" : " مطبق");
				} else if (v === "Tree Level" || v === "Search") {
					out = tr(v === "Tree Level" ? "Level" : v);
				}
				if (out && out !== v) el.setAttribute(a, out);
			});
		});
	}
	if (window.frappe && frappe.boot && frappe.boot.lang === "ar" || document.documentElement.lang === "ar") {
		let pend = false;
		new MutationObserver(() => {
			if (pend) return;
			pend = true;
			setTimeout(() => { pend = false; fixAttrs(document.body); }, 300);
		}).observe(document.documentElement, { childList: true, subtree: true });
	}

	if (!patch()) {
		let tries = 0;
		const timer = setInterval(() => {
			if (patch() || ++tries > 100) clearInterval(timer);
		}, 50);
	}
})();
