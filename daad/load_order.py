"""DaaD's Arabic must load after the apps it overrides. This only reports a wrong order, it never reorders."""

import frappe

MUST_LOAD_BEFORE_DAAD = ("frappe", "erpnext", "hrms")


def check_load_order():
	"""Warn in the Error Log and the console when an app DaaD overrides loads after it."""
	apps = frappe.get_installed_apps()
	if "daad" not in apps:
		return None

	position = apps.index("daad")
	late = [app for app in MUST_LOAD_BEFORE_DAAD if app in apps and apps.index(app) > position]
	if not late:
		return None

	message = (
		f"DaaD loads before {', '.join(late)}, so their translations override DaaD's Arabic. "
		f"Installed order: {', '.join(apps)}. Move daad after them in Installed Applications. "
		"DaaD did not change the order."
	)
	frappe.log_error(title="DaaD load order", message=message)
	print(f"WARNING: {message}")
	return message
