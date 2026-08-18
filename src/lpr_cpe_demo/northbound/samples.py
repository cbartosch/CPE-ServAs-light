"""Example messages, as each system would actually put them on the wire.

The units are the trap and they are reproduced faithfully. DOCSIS MIB objects are
in TENTHS of a dBmV or dB, TR-181 optical power is in HUNDREDTHS of a dBm, and
`docsIfSigQUncorrectables` is a CUMULATIVE counter, not a rate. An integration
that reads these as plain decibels is wrong by a factor of ten and reads a healthy
modem as catastrophically failed; one that reads the counter as a rate flags every
modem that has been up for a year.
"""

from __future__ import annotations

# --------------------------------------------------------------------- CPE
# TR-369 USP Notify carrying TR-181 paths. A real agent sends the changed
# parameters, not the whole tree.
CPE_USP_NOTIFY_HFC = {
    "header": {"msg_id": "usp-8f2c-0031", "msg_type": "NOTIFY"},
    "body": {
        "request": {
            "notify": {
                "subscription_id": "sub-pnm-hourly",
                "send_resp": False,
                "from_id": "os::LPR-CM-3410ABCD",
                "to_id": "proto::lpr-usp-controller",
                "event": {
                    "obj_path": "Device.",
                    "event_name": "Periodic!",
                    "params": {
                        "Device.DeviceInfo.SerialNumber": "3410ABCD9921",
                        "Device.DeviceInfo.ProductClass": "DOCSIS-3.1-GW",
                        "Device.DeviceInfo.SoftwareVersion": "7.14.2-LPR",
                        "Device.DeviceInfo.UpTime": "1843200",
                        # DOCSIS MIB values: TENTHS of a dBmV / dB
                        "docsIfDownChannelPower": "-118",
                        "docsIf3CmStatusUsTxPower": "521",
                        "docsIf3SignalQualityExtRxMER": "312",
                        "docsIfSigQUncorrectables": "418223",
                        "docsIf3CmtsCmUsStatusT3Timeouts": "37",
                    },
                },
            }
        }
    },
    # Not part of USP; added by the collector so a consumer can order samples.
    "_collector": {"receivedAt": "2026-08-18T03:58:14Z",
                   "collector": "pnm-collector-02"},
}

CPE_USP_NOTIFY_PON = {
    "header": {"msg_id": "usp-8f2c-0032", "msg_type": "NOTIFY"},
    "body": {"request": {"notify": {
        "subscription_id": "sub-pnm-hourly",
        "from_id": "os::LPR-ONT-77B1EE02",
        "event": {
            "obj_path": "Device.",
            "event_name": "Periodic!",
            "params": {
                "Device.DeviceInfo.SerialNumber": "77B1EE02",
                "Device.DeviceInfo.ProductClass": "XGS-PON-ONT",
                "Device.DeviceInfo.SoftwareVersion": "4.02.11",
                "Device.DeviceInfo.UpTime": "402",
                # TR-181 optical: HUNDREDTHS of a dBm
                "Device.Optical.Interface.1.CurrentDownstreamRxPower": "-2685",
                "Device.Optical.Interface.1.CurrentUpstreamTxPower": "241",
                "Device.Optical.Interface.1.Status": "Up",
            },
        }}}},
    "_collector": {"receivedAt": "2026-08-18T03:58:19Z",
                   "collector": "olt-ems-bridge-01"},
}

# --------------------------------------------------------------------- NXT
# MODELLED. Not read from any NXT specification. Field names are placeholders.
NXT_SNAPSHOT = {
    "snapshotId": "NXT-SNAP-20260818-0041",
    "takenAt": "2026-08-18T03:59:02Z",
    "subscriberId": "SUB-0099231",
    "serviceId": "SVC-HFC-0099231",
    "accessTechnology": "HFC",
    "serviceState": "degraded",
    "provisioningState": "in_sync",
    "topology": {
        "nodeId": "NODE-ARE-7500000",
        "delimiterId": "TAP-ARE-AD00042",
        "delimiterType": "tap",
        "householdsBehindDelimiter": 6,
        "headend": "ARE-HE-01",
    },
    "recentEvents": [
        {"at": "2026-08-18T02:14:00Z", "code": "T3_TIMEOUT_BURST", "count": 12},
        {"at": "2026-08-17T21:40:00Z", "code": "PARTIAL_SERVICE", "count": 1},
    ],
    "openTickets": ["JT-4471902"],
}

# --------------------------------------------------------------------- WFM
# TMF697 Work Order.
WFM_WORK_ORDER = {
    "id": "WO-2026-0818-0442",
    "href": "https://wfm.example/tmf-api/workOrder/v4/workOrder/WO-2026-0818-0442",
    "@type": "WorkOrder",
    "state": "acknowledged",
    "orderDate": "2026-08-18T04:12:00Z",
    "requestedCompletionDate": "2026-08-19T04:00:00Z",
    "appointment": {"id": "APPT-88231",
                    "validFor": {"startDateTime": "2026-08-18T13:00:00Z",
                                 "endDateTime": "2026-08-18T17:00:00Z"}},
    "workOrderItem": [{
        "id": "1", "action": "add", "state": "acknowledged",
        "workOrderItemSpecification": {"id": "WOS-DIRTY-BOOTS-MR",
                                       "name": "Plant maintenance request"},
    }],
    "relatedParty": [
        {"id": "CREW-ARE-04", "role": "assignedCrew", "@referredType": "Organization"},
        {"id": "TECH-11872", "name": "field technician", "role": "technician"},
    ],
    "place": [{"id": "PLC-0099231", "role": "serviceAddress",
               "geographicLocation": {"@type": "GeographicPoint",
                                      "latitude": "18.4725", "longitude": "-66.7156"}}],
    "characteristic": [
        {"name": "crewType", "valueType": "string", "value": "dirty_boots"},
        {"name": "dispatchBase", "valueType": "string", "value": "BASE-AGU"},
        {"name": "requiredSkills", "valueType": "string", "value": "hfc_plant"},
        {"name": "delimiterId", "valueType": "string", "value": "TAP-ARE-AD00042"},
    ],
}

WFM_STATE_CHANGE_EVENT = {
    "eventId": "evt-wo-99120",
    "eventTime": "2026-08-18T15:41:03Z",
    "eventType": "WorkOrderStateChangeEvent",
    "event": {"workOrder": {
        "id": "WO-2026-0818-0442", "state": "completed",
        "characteristic": [
            {"name": "resolutionCode", "value": "TAP_PORT_REPLACED"},
            {"name": "noFaultFound", "valueType": "boolean", "value": "false"},
            {"name": "onSiteMinutes", "valueType": "integer", "value": "165"},
        ]}},
}

# ------------------------------------------------------------------ jTrack
# TMF621 Trouble Ticket.
JTRACK_TROUBLE_TICKET = {
    "id": "JT-4471902",
    "href": "https://jtrack.example/tmf-api/troubleTicket/v5/troubleTicket/JT-4471902",
    "@type": "TroubleTicket",
    "name": "Degraded HFC service, upstream Tx at ceiling",
    "description": ("Upstream Tx 52.1 dBmV against a 51 dBmV ceiling with rising "
                    "uncorrectables. Six households behind TAP-ARE-AD00042."),
    "severity": "major",
    "priority": "2",
    "status": "inProgress",
    "creationDate": "2026-08-18T04:00:00Z",
    "expectedResolutionDate": "2026-08-19T04:00:00Z",
    "ticketType": "serviceAssurance",
    "relatedEntity": [
        {"id": "SVC-HFC-0099231", "role": "affectedService",
         "@referredType": "Service"},
        {"id": "TAP-ARE-AD00042", "role": "suspectResource",
         "@referredType": "Resource"},
    ],
    "relatedParty": [{"id": "SUB-0099231", "role": "affectedCustomer"}],
    "externalIdentifier": [
        {"owner": "predictive-scan", "externalIdentifierType": "predictiveTicket",
         "id": "PRD-20260818-00515"},
    ],
    "note": [{"id": "1", "date": "2026-08-18T04:01:00Z", "author": "assurance-agent",
              "text": "Two remote attempts failed; a remote action cannot repair a "
                      "tap fault. Escalated for dispatch."}],
    "statusChangeHistory": [
        {"status": "acknowledged", "changeDate": "2026-08-18T04:00:00Z"},
        {"status": "inProgress", "changeDate": "2026-08-18T04:12:00Z",
         "changeReason": "work order WO-2026-0818-0442 raised"},
    ],
}

JTRACK_STATUS_EVENT = {
    "eventId": "evt-tt-33417",
    "eventTime": "2026-08-18T15:44:00Z",
    "eventType": "TroubleTicketStatusChangeEvent",
    "event": {"troubleTicket": {"id": "JT-4471902", "status": "resolved",
                                "resolutionDate": "2026-08-18T15:44:00Z"}},
}

SAMPLES = {
    "cpe_hfc": CPE_USP_NOTIFY_HFC, "cpe_pon": CPE_USP_NOTIFY_PON,
    "nxt": NXT_SNAPSHOT, "wfm_order": WFM_WORK_ORDER,
    "wfm_event": WFM_STATE_CHANGE_EVENT,
    "jtrack_ticket": JTRACK_TROUBLE_TICKET, "jtrack_event": JTRACK_STATUS_EVENT,
}
