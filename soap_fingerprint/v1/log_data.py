# Copyright (c) 2024, DAS and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import add_to_date

@frappe.whitelist()
def get_last_sync_time(machine_no):
    last_time = frappe.db.get_value("Fingerprint Log", {"machine_no": machine_no}, ["posting_date", "posting_time"], order_by="posting_date, posting_time desc")
    
    return [add_to_date(None, days=-1, as_string=True), "00:00:00"] if not last_time or not last_time[0] else last_time