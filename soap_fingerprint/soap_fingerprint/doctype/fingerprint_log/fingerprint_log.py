# Copyright (c) 2024, DAS and contributors
# For license information, please see license.txt
import json

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, get_datetime, safe_json_loads
from frappe.utils.data import time_diff_in_seconds

class FingerprintLog(Document):
	def validate(self):
		if self.get("datetime"):
			datetime = get_datetime(self.datetime)
			self.posting_date = datetime.date()
			self.posting_time = datetime.time()

		if self.type != "Import Data Log":
			return
		
		if not self.status:
			self.status = "Queued"

	@frappe.whitelist()
	def create_attendance(self):
		"""Execute repost item valuation via scheduler."""
		# if self.status not in ["Queued", "Completed"]:
		# 	frappe.db.set_value(self.doctype, self.name, "status", "Queued")
			
		frappe.get_doc("Scheduled Job Type", "fingerprint_log.create_emloyee_check_in").enqueue(force=True)

@frappe.whitelist()
def create_attendance():
	"""Execute repost item valuation via scheduler."""
	frappe.db.sql(""" UPDATE `tabFingerprint Log` set status = "Queued" WHERE status not in ("Queued", "Completed")  """)
	frappe.get_doc("Scheduled Job Type", "fingerprint_log.create_emloyee_check_in").enqueue(force=True)

def create_emloyee_check_in():
	# ambil smua import data log yang belum sync
	data_log = frappe.get_list("Fingerprint Log", filters={
		"type": "Import Data Log", 
		"status": ["in", ["Queued", "Partialy Completed"]],
	}, pluck="name", order_by="creation asc")
	
	for log_fp in data_log:
		# select fingerprint log agar menghindari race condition
		fp = frappe.get_doc("Fingerprint Log", log_fp, for_update=1)
		data_error = []

		if fp.status not in ["Queued", "Partialy Completed"]:
			frappe.db.commit()
			continue

		if fp.status == "Queued":
			log = safe_json_loads(fp.data)
			data = log.get("data", [])
		else:
			data = safe_json_loads(fp.data_error)
		
		update = 0
		for row in data:
			datetime, pin, status, verified, workcode = row.values()
			emp = frappe.db.get_value("Employee", { "fingerprint_pin": pin }, ["name", "company"], cache=1, as_dict=1)
			# memastikan pin yang digunakan terdaftar pada erpnext
			if not emp:
				data_error.append(row)
				continue

			datetime = get_datetime(datetime)
			print(log_fp, emp, datetime)
			update, error = shift_asigment_attendance(emp, datetime, status).execute()
			if error:
				data_error.append(row)
		
		if not update:
			frappe.db.commit()
			continue

		if data_error:
			fp.status = "Partialy Completed"
		else:
			fp.status = "Completed"

		fp.data_error = frappe.as_json(data_error)
		fp.save()
		
		frappe.db.commit()

def new_attendance(emp, datetime):
	date = datetime.date()
	
	att = frappe.get_value("Attendance", {"employee": emp.name, "attendance_date": date, "docstatus": ["!=", 2]}, ["name", 'in_time', "docstatus"], as_dict=1)
	if att and att.docstatus == 1:
		return

	# if att and time_diff_in_seconds(datetime, att.in_time) > 1200:
	# 	# jika check in terakhir sudah lebih dari setengah jam. maka d anggap check out
	# 	att = frappe.get_doc("Attendance", att.name)
	# 	att.update({ 
	# 		"out_time": datetime
	# 	})
	# 	att.submit()
	if not att:	 
		# jika status = 0 dan belum ada attendance maka buat document
		att = frappe.new_doc("Attendance")
		att.update({
			"employee": emp.name, "company": emp.company, "attendance_date": date, 
			"in_time": datetime
		})
		att.save()

def submit_attendance(emp, datetime):
	date = datetime.date()

	# cek attendance hari ini yang jam ny lebih kecil dari jam checkout yang masih draft
	att_name = frappe.db.get_value("Attendance", {"employee": emp.name, "attendance_date": date, "in_time": ["<", datetime],"docstatus": ["<", 2]}, ["name", "docstatus"], as_dict=1) 
	if not att_name:
		# jika tidak ada maka cek attendance di hari sebelumnya
		yt = add_days(date, -1)
		att_name = frappe.db.get_value("Attendance", {"employee": emp.name, "attendance_date": yt, "docstatus": 0}, ["name", "docstatus"], as_dict=1)
	
	# jika tidak ada attendance draft maka skip 
	if not att_name:
		return

	if att_name.docstatus == 1:
		return
		 
	# jika status = 1 dan attendance belum disubmit maka tambahkan jam keluar dan submit document
	att = frappe.get_doc("Attendance", att_name.name)
	att.update({ 
		"out_time": datetime
	})
	att.submit()

class shift_asigment_attendance(object):
	def __init__(self, emp, datetime, status):
		self.employee = emp
		self.datetime = datetime
		self.status = status
		self.date = datetime.date()
		self.fg_setting = frappe.get_cached_doc("Fingerprint Setting", ["attendance_create_by",
			"batas_waktu_out_dari_shift", "batas_waktu_in_dari_start_shift", "batas_waktu_out_setelah_shift"])

	def execute(self):
		update, error = 0, 0
		if self.fg_setting.attendance_create_by == "Shift Assignment":
			update = self.create_update_attendance(check_yt=True)
		else:
			if self.status == "0":	
				# jika status sama dengan 0 maka buat attendance draft
				self.in_attendance()
				update = 1 
			elif self.status in ["1", "5"]:
				date = self.datetime.date()
				# cek attendance hari ini yang jam ny lebih kecil dari jam checkout yang masih draft
				att_name = frappe.db.get_value("Attendance", 
					{"employee": 
	  					self.employee.name, "attendance_date": date, "in_time": ["<", self.datetime],"docstatus": ["<", 2]}, ["name", "docstatus"], as_dict=1) 
				
				if not att_name:
					# jika tidak ada maka cek attendance di hari sebelumnya
					yt = add_days(date, -1)
					att_name = frappe.db.get_value("Attendance", 
						{"employee": self.employee.name, "attendance_date": yt, "docstatus": 0}, ["name", "docstatus"], as_dict=1)
				
				# jika tidak ada attendance draft maka skip 
				if not att_name or att_name.docstatus == 1:
					return
					
				# jika status sama dengan 1 maka cari attendance draft hari ini / kemarin untuk di submit 
				self.out_attendance(att_name, False)
				update = 1
			else:
				error = 1
		
		return update, error
	
	def create_update_attendance(self, date=None, check_yt=False):
		if not date:
			date = self.date

		# check attndance berdasarkan variabel date
		att = frappe.db.get_value("Attendance", {
			"employee": self.employee.name, "attendance_date": date, "docstatus": ["<", 2]}, 
			["name", "docstatus", "auto_check_out", "in_time", "out_time"], as_dict=1)
					
		# field shift blum pasti
		shift_asigment = frappe.get_value("Shift Assignment", {"employee": self.employee.name, "start_date": date}, ["shift_type", "shift_in", "shift_out"], as_dict=1)
		
		# jika tidak ada shift maka tidak ada attendance
		if shift_asigment:			
			# jika tidak ada att, datetime lebih kecil dari end shift dan datetime lebih kecil dari (batas_waktu_in_dari_shift) waktu in shift
			if not att and self.datetime < shift_asigment.shift_out \
				and time_diff_in_seconds(shift_asigment.shift_in, self.datetime) <= self.fg_setting.batas_waktu_in_dari_shift:
				self.in_attendance(shift_asigment.shift_type)
				return True
			
			# jika sudah ada att, datetime lebih besar dari waktu masuk shift dan datetime lebih kecil dari (batas_waktu_out_dari_shift) waktu out shift 
			elif att and \
				(att.docstatus == 0 or (att.docstatus == 1 and att.auto_check_out == 1)) and self.datetime > shift_asigment.shift_in \
				and (
					time_diff_in_seconds(shift_asigment.shift_out, self.datetime) <= self.fg_setting.batas_waktu_out_dari_shift
					and time_diff_in_seconds(self.datetime, shift_asigment.shift_out) <= self.fg_setting.batas_waktu_out_setelah_shift
				):
				# jika terdapat attendance draft dan lebih dari setengah jam dari waktu masuk maka di anggap out
				self.out_attendance(att.name)
				return True

		form_lembur = frappe.get_value("Form Lembur", {"employee": self.employee.name, "date": date}, ["jam_start_lembur", "jam_out_lembur"], as_dict=1)
		# jika terdapat lembur (lembur d buat sebelum terjadi fingerprint)
		if form_lembur:
			# jika tidak ada att, datetime lebih kecil dari end shift dan datetime lebih kecil dari (batas_waktu_in_dari_shift) waktu in shift
			if not att \
				and self.datetime < form_lembur.jam_out_lembur \
				and time_diff_in_seconds(form_lembur.jam_start_lembur, self.datetime) <= self.fg_setting.batas_waktu_in_dari_shift:
				self.in_attendance()
				return True
			elif att and \
				(att.docstatus == 0 or (att.docstatus == 1 and att.auto_check_out == 1))\
				and (
					time_diff_in_seconds(form_lembur.jam_out_lembur, self.datetime) <= self.fg_setting.batas_waktu_out_dari_shift
					and time_diff_in_seconds(self.datetime, form_lembur.jam_out_lembur) <= self.fg_setting.batas_waktu_out_setelah_shift
				):
				self.out_attendance(att.name)
				return True
			
		# check attendance hari sebelumny
		if check_yt:
			return self.yt_attendance(att.in_time if att else None)

	def yt_attendance(self, in_time=None):
		# jika data log lebih besar dari waktu in hari ini maka skip
		if in_time and self.datetime > in_time:
			return
		
		yt = add_days(self.date, -1)
		return self.create_update_attendance(date=yt)
	
	def in_attendance(self, shift_type=None):
		# jika status = 0 dan belum ada attendance maka buat document
		att = frappe.new_doc("Attendance")
		att.update({
			"shift": shift_type,
			"employee": self.employee.name, "company": self.employee.company, "attendance_date": self.date, 
			"in_time": self.datetime
		})
		att.save()

	def out_attendance(self, att, reset_auto_check_out=True):
		# jika status = 1 dan attendance belum disubmit maka tambahkan jam keluar dan submit document
		att = frappe.get_doc("Attendance", att)
		if not reset_auto_check_out and att.get("auto_check_out"):
			return
		
		att.update({ 
			"out_time": self.datetime
		})

		if att.docstatus == 1:
			att.auto_check_out = 0
			att.db_update()
		else:
			att.submit()	

