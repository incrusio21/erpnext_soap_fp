
frappe.listview_settings["Fingerprint Log"] = {
    onload: function (list_view) {
		let me = this;

		list_view.page.add_inner_button(__("Re-sync"), function () {
			frappe.call({
                method: "soap_fingerprint.soap_fingerprint.doctype.fingerprint_log.fingerprint_log.create_attendance",
                callback: function (r) {
                    frappe.show_alert({message: __("Update All Error Log to Queued"), indicator: "blue", });
                },
            });
		});
	}
}