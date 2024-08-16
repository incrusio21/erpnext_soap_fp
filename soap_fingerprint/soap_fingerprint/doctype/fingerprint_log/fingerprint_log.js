// Copyright (c) 2024, DAS and contributors
// For license information, please see license.txt

frappe.ui.form.on('Fingerprint Log', {
	refresh: function(frm) {
		if(frm.doc.status != "Completed"){
			frm.add_custom_button(__('Re-sync'), function(){
				frappe.call({
					doc: frm.doc,
					method: "create_attendance",
					freeze: true
				})
			})
		}
	}
});
