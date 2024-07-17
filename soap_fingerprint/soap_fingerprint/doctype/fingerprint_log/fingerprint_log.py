# Copyright (c) 2024, DAS and contributors
# For license information, please see license.txt
import json

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, get_datetime, safe_json_loads

class FingerprintLog(Document):
	def validate(self):
		if self.type != "Import Data Log":
			return
		
		if not self.status:
			self.status = "Queued"

	@frappe.whitelist()
	def create_attendance(self):
		"""Execute repost item valuation via scheduler."""
		frappe.get_doc("Scheduled Job Type", "fingerprint_log.create_emloyee_check_in").enqueue(force=True)

def create_emloyee_check_in():
	# ambil smua import data log yang belum sync
	data_log = frappe.get_list("Fingerprint Log", filters={"type": "Import Data Log", "status": ["in", ["Queued"]]}, pluck="name", order_by="creation asc")
	for log_fp in data_log:
		# select fingerprint log agar menghindari race condition
		fp = frappe.get_doc("Fingerprint Log", log_fp, for_update=1)
		if fp.status not in ["Queued"]:
			frappe.db.commit()
			continue

		log = safe_json_loads(fp.data)
		for row in log.get("data", []):
			datetime, pin, status, verified, workcode = row.values()
			emp = frappe.db.get_value("Employee", { "fingerprint_pin": pin }, ["name"], cache=1, as_dict=1)
			# memastikan pin yang digunakan terdaftar pada erpnext
			if not emp:
				frappe.throw("Pin {} tidak memiliki Employee terdaftar".format(pin))

			datetime = get_datetime(datetime)
			if status == "0":	
				# jika status sama dengan 0 maka buat attendance draft
				new_attendance(emp, datetime)
			elif status == "1":
				# jika status sama dengan 1 maka cari attendance draft hari ini / kemarin untuk di submit 
				submit_attendance(emp, datetime)
			
		fp.status = "Completed"
		fp.save()
		
		frappe.db.commit()

def new_attendance(emp, datetime):
	date = datetime.date()
	if frappe.db.exists("Attendance", {"employee": emp.name, "attendance_date": date, "docstatus": ["!=", 2]}):
		return
	 
	# jika status = 0 dan belum ada attendance maka buat document
	att = frappe.new_doc("Attendance")
	att.update({
		"employee": emp.name, "attendance_date": date, 
		"in_time": datetime
	})
	att.save()

def submit_attendance(emp, datetime):
	date = datetime.date()

	# cek attendance hari ini yang jam ny lebih kecil dari jam checkout yang masih draft
	att_name = frappe.db.get_value("Attendance", {"employee": emp.name, "attendance_date": date, "in_time": ["<", datetime],"docstatus": 0}, "name")
	if not att_name:
		# jika tidak ada maka cek attendance di hari sebelumnya
		yt = add_days(date, -1)
		att_name = frappe.db.get_value("Attendance", {"employee": emp.name, "attendance_date": yt, "docstatus": 0}, "name")
	
	# jika tidak ada attendance draft maka skip 
	if not att_name:
		return
	 
	# jika status = 1 dan attendance belum disubmit maka tambahkan jam keluar dan submit document
	att = frappe.get_doc("Attendance", att_name)
	att.update({ 
		"out_time": datetime
	})
	att.submit()