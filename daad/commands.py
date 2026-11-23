"""DaaD's bench commands for Frappe v15, where DaaD's Arabic lives in `daad/translations/ar.csv`.

- `bench --site <site> daad-harvest` collects Arabic found outside DaaD for human review, and
  `--apply <file>` merges the reviewed rows marked approved.
- `bench daad-import-po <ar.po>` merges a PO catalog, such as `daad/locale/ar.po` on the
  version-16 branch, into the CSV.
"""

import csv
from pathlib import Path

import click
from babel.messages.pofile import read_po
from frappe.commands import get_site, pass_context

CORE_APPS = ("frappe", "erpnext", "hrms")
FIELDS = ["msgid", "msgctxt", "source", "found_translation", "daad_translation", "status", "approved"]
DAAD_CSV = Path(__file__).parent / "translations" / "ar.csv"


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


def _read_daad_csv():
	return _read_csv(DAAD_CSV) if DAAD_CSV.exists() else {}


def _by_msgid(item):
	(msgid, msgctxt), _msgstr = item
	return msgid, msgctxt or ""


def _write_daad_csv(entries):
	"""Write entries sorted so diffs stay small, then read the file back the way Frappe will."""
	DAAD_CSV.parent.mkdir(exist_ok=True)
	with open(DAAD_CSV, "w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f, lineterminator="\n")
		for (msgid, msgctxt), msgstr in sorted(entries.items(), key=_by_msgid):
			writer.writerow([msgid, msgstr, msgctxt] if msgctxt else [msgid, msgstr])

	if _read_csv(DAAD_CSV) != entries:
		raise click.ClickException(f"{DAAD_CSV} does not read back as written. Restore it with git.")


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


def merge(entries, updates):
	"""Apply (key, msgstr) updates to a copy of entries. Return it with the added and updated counts."""
	from frappe.utils import strip

	merged, added, updated = dict(entries), 0, 0
	for key, msgstr in updates:
		msgstr = strip(msgstr)
		current = merged.get(key)
		if not msgstr or current == msgstr:
			continue
		if current is None:
			added += 1
		else:
			updated += 1
		merged[key] = msgstr
	return merged, added, updated


def harvest():
	import frappe
	from frappe.utils import today

	apps = [app for app in frappe.get_installed_apps() if app != "daad"]
	rows = build_rows(_read_daad_csv(), _sources(apps))

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


def _approved(path):
	"""Yield (key, msgstr) for each review row marked approved = yes."""
	with open(path, newline="", encoding="utf-8") as f:
		for row in csv.DictReader(f):
			if (row.get("approved") or "").strip().lower() != "yes":
				continue
			msgid, msgctxt, msgstr = row["msgid"], row.get("msgctxt") or None, row.get("found_translation")
			if not msgid or not msgstr:
				click.echo(f"Skipped, no translation: {msgid!r}")
				continue
			yield (msgid, msgctxt), msgstr


def apply_file(path):
	"""Merge only rows with approved = yes into DaaD's ar.csv."""
	entries, added, updated = merge(_read_daad_csv(), _approved(path))
	_write_daad_csv(entries)
	click.echo(f"Added {added}, updated {updated}. Run bench --site <site> clear-cache to see them.")
	return added, updated


def import_po(path):
	"""Merge the translated entries of a PO catalog into DaaD's ar.csv. Rows the catalog lacks are kept."""
	translated = ((key, msgstr) for key, msgstr in _read_catalog(path).items() if msgstr)
	entries, added, updated = merge(_read_daad_csv(), translated)
	_write_daad_csv(entries)
	click.echo(
		f"{DAAD_CSV}: added {added}, updated {updated}, {len(entries)} rows. "
		"Run bench --site <site> clear-cache to see them."
	)
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


@click.command("daad-import-po", help="Merge a PO catalog, such as version-16's ar.po, into DaaD's ar.csv")
@click.argument("po_path", type=click.Path(exists=True, dir_okay=False))
def daad_import_po(po_path):
	import_po(po_path)


commands = [daad_harvest, daad_import_po]
