"""`bench --site <site> daad-harvest`: collect Arabic found outside DaaD for human review."""

import csv
from pathlib import Path

import click
from babel.messages.pofile import read_po
from frappe.commands import get_site, pass_context

CORE_APPS = ("frappe", "erpnext", "hrms")
FIELDS = ["msgid", "msgctxt", "source", "found_translation", "daad_translation", "status", "approved"]


def _single(value):
	return value[0] if isinstance(value, (list, tuple)) else value


def _read_catalog(path):
	"""{(msgid, msgctxt): msgstr} from a PO file. Untranslated and fuzzy entries have an empty msgstr."""
	with open(path, "rb") as f:
		catalog = read_po(f)
	return {
		(_single(message.id), message.context or None): "" if message.fuzzy else (_single(message.string) or "")
		for message in catalog
		if message.id
	}


def _read_csv(path):
	"""{(msgid, msgctxt): msgstr} from a Frappe translation CSV, read the way Frappe loads it."""
	from frappe.translate import read_csv_file
	from frappe.utils import strip

	entries = {}
	for row in read_csv_file(str(path)):
		if len(row) not in (2, 3):
			continue
		msgid = row[0].replace("\\n", "\n")
		msgstr = strip(row[1].replace("\\n", "\n"))
		if msgid and msgstr:
			entries[(msgid, (row[2] or None) if len(row) == 3 else None)] = msgstr
	return entries


def _sources(apps):
	"""Yield (label, entries) for each Arabic source outside DaaD."""
	import frappe

	for app in apps:
		root = Path(frappe.get_app_path(app))
		po_path = root / "locale" / "ar.po"
		if po_path.exists():
			yield f"{app}:locale/ar.po", _read_catalog(po_path)
		csv_path = root / "translations" / "ar.csv"
		if csv_path.exists():
			yield f"{app}:translations/ar.csv", _read_csv(csv_path)

	records = frappe.get_all(
		"Translation", filters={"language": "ar"}, fields=["source_text", "translated_text", "context"]
	)
	yield "Translation", {(r.source_text, r.context or None): r.translated_text for r in records}


def build_rows(daad, sources):
	"""Review rows for every source entry that is new to DaaD, differs from it, or has no Arabic at all."""
	rows, untranslated, translated = [], {}, set()
	for label, entries in sources:
		app = label.partition(":")[0]
		for key, found in entries.items():
			current = daad.get(key)
			if not found:
				if app in CORE_APPS and not current:
					untranslated.setdefault(key, label)
				continue
			translated.add(key)
			if current == found:
				continue
			rows.append((key, label, found, current or "", "differs" if current else "new"))
	rows += [(key, label, "", "", "missing") for key, label in untranslated.items() if key not in translated]
	return rows


def harvest():
	import frappe
	from frappe.gettext.translate import get_po_path
	from frappe.utils import today

	daad = {key: value for key, value in _read_catalog(get_po_path("daad", "ar")).items() if value}
	apps = [app for app in frappe.get_installed_apps() if app != "daad"]
	rows = build_rows(daad, _sources(apps))

	target = Path(frappe.get_app_path("daad")) / "harvest" / f"{today()}.csv"
	target.parent.mkdir(parents=True, exist_ok=True)
	with open(target, "w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)
		writer.writerow(FIELDS)
		for (msgid, msgctxt), label, found, current, status in rows:
			writer.writerow([msgid, msgctxt or "", label, found, current, status, ""])

	counts = {status: sum(1 for row in rows if row[4] == status) for status in ("new", "differs", "missing")}
	click.echo(f"{target}: {len(rows)} rows, {counts}")
	return target, counts


def apply_file(path):
	"""Merge only rows with approved = yes into DaaD's ar.po, then compile it."""
	from frappe.gettext.translate import _compile_translation, get_po_path, write_catalog

	po_path = get_po_path("daad", "ar")
	with open(po_path, "rb") as f:
		catalog = read_po(f)

	added = updated = 0
	with open(path, newline="", encoding="utf-8") as f:
		for row in csv.DictReader(f):
			if (row.get("approved") or "").strip().lower() != "yes":
				continue
			msgid, msgctxt, msgstr = row["msgid"], row.get("msgctxt") or None, row.get("found_translation")
			if not msgid or not msgstr:
				click.echo(f"Skipped, no translation: {msgid!r}")
				continue
			message = catalog.get(msgid, msgctxt)
			if message is None:
				catalog.add(msgid, msgstr, context=msgctxt)
				added += 1
			elif message.string != msgstr:
				message.string = msgstr
				updated += 1

	write_catalog("daad", catalog, "ar")
	with open(po_path, "rb") as f:
		read_po(f)  # refuse to report success on a catalog that does not parse
	_compile_translation("daad", "ar", force=True)
	click.echo(f"Added {added}, updated {updated}. Run bench --site <site> clear-cache to see them.")
	return added, updated


@click.command("daad-harvest", help="Write a review CSV of Arabic found outside DaaD, or merge approved rows")
@click.option("--apply", "apply_path", type=click.Path(exists=True, dir_okay=False), help="Reviewed CSV to merge")
@pass_context
def daad_harvest(context, apply_path=None):
	import frappe

	frappe.init(site=get_site(context))
	frappe.connect()
	try:
		if apply_path:
			apply_file(apply_path)
		else:
			harvest()
	finally:
		frappe.destroy()


commands = [daad_harvest]
