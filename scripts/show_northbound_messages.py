#!/usr/bin/env python3
"""Print the northbound messages as each system would put them on the wire.

    PYTHONPATH=src python3 scripts/show_northbound_messages.py
    PYTHONPATH=src python3 scripts/show_northbound_messages.py --raw cpe_hfc
    PYTHONPATH=src python3 scripts/show_northbound_messages.py --contracts
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.northbound.adapters import counter_rate, parse  # noqa: E402
from lpr_cpe_demo.northbound.contracts import CONTRACTS, summary  # noqa: E402
from lpr_cpe_demo.northbound.samples import SAMPLES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", metavar="NAME", help=f"one of {sorted(SAMPLES)}")
    ap.add_argument("--contracts", action="store_true")
    args = ap.parse_args()

    if args.raw:
        print(json.dumps(SAMPLES[args.raw], indent=2))
        return 0

    info = summary()
    print("NORTHBOUND MESSAGE CONTRACTS\n")
    for contract in CONTRACTS:
        mark = "published spec" if contract.provenance == "STANDARD" else "INVENTED"
        print(f"  {contract.system:8s} {mark:15s} {contract.specification}")
        print(f"           transport: {contract.transport}")
    print(f"\n  {info['warning']}\n")

    if args.contracts:
        for contract in CONTRACTS:
            print(f"\n{contract.system} — {contract.provenance}")
            for field in contract.fields:
                flag = "req" if field.required else "opt"
                print(f"  [{flag}] {field.path:58s} {field.kind:6s} "
                      f"{field.provenance}")
                if field.note:
                    print(f"        {field.note}")
        return 0

    print("=" * 78)
    print("WHAT ARRIVES, AND WHAT IT MEANS AFTER CONVERSION\n")

    cpe = parse("CPE", SAMPLES["cpe_hfc"])
    raw = SAMPLES["cpe_hfc"]["body"]["request"]["notify"]["event"]["params"]
    print("CPE, TR-369 USP Notify carrying TR-181 and DOCSIS MIB objects")
    print(f"  on the wire : docsIfDownChannelPower={raw['docsIfDownChannelPower']!r}"
          f"  docsIf3SignalQualityExtRxMER="
          f"{raw['docsIf3SignalQualityExtRxMER']!r}")
    print(f"  converted   : {cpe.kpis}")
    print("  DOCSIS power and MER are TENTHS. Read as plain dBmV, -118 is a modem")
    print("  reported dead when it is at -11.8 and in service.")
    pon = parse("CPE", SAMPLES["cpe_pon"])
    print(f"  ONT optical is HUNDREDTHS: -2685 -> {pon.kpis['ont_rx_dbm']} dBm")
    print(f"  counters are cumulative: {cpe.counters}")
    print("  A rate needs two samples; one sample yields None, and a counter that")
    print("  went backwards means a reboot, not a negative rate.\n")

    nxt = parse("NXT", SAMPLES["nxt"])
    print("NXT, assurance snapshot — INVENTED SHAPE")
    print(f"  {nxt.snapshot_id}  service={nxt.service_state}  "
          f"provisioning={nxt.provisioning_state}")
    print(f"  delimiter {nxt.delimiter_id} carrying "
          f"{nxt.households_behind_delimiter} households")
    print(f"  open tickets {list(nxt.open_tickets)}")
    print("  Every field name above is a placeholder. Confirm against a real")
    print("  message before any integration work starts.\n")

    order = parse("WFM", SAMPLES["wfm_order"])
    done = parse("WFM", SAMPLES["wfm_event"])
    print("WFM, TMF697 Work Order")
    print(f"  {order.work_order_id}  {order.state} -> {done.state}")
    print(f"  crew={order.crew_type} base={order.dispatch_base} "
          f"delimiter={order.delimiter_id}")
    print(f"  on completion: code={done.resolution_code} "
          f"noFaultFound={done.no_fault_found} onSite={done.on_site_minutes}min")
    print("  Operator-specific fields ride in `characteristic`, which is where")
    print("  TMF697 puts anything the standard does not name.\n")

    ticket = parse("jTrack", SAMPLES["jtrack_ticket"])
    resolved = parse("jTrack", SAMPLES["jtrack_event"])
    print("jTrack, TMF621 Trouble Ticket")
    print(f"  {ticket.ticket_id}  {ticket.status}/{ticket.severity} -> "
          f"{resolved.status}")
    print(f"  affected service {ticket.affected_service}, suspect resource "
          f"{ticket.suspect_resource}")
    print(f"  predictive origin {ticket.predictive_ticket_id} carried in "
          f"externalIdentifier\n")

    print("=" * 78)
    print("HOW THEY JOIN UP\n")
    print(f"  delimiter {nxt.delimiter_id} appears in all three of NXT topology,")
    print(f"  the WFM characteristic and the jTrack suspectResource.")
    print(f"  jTrack {ticket.ticket_id} appears in the NXT snapshot's openTickets.")
    print(f"  The predictive ticket {ticket.predictive_ticket_id} survives into")
    print(f"  jTrack via externalIdentifier, so a scan-originated incident stays")
    print(f"  traceable after it becomes a real ticket.")
    print("\n  Without a shared delimiter identifier none of this correlates, which")
    print("  is the first thing to confirm against real messages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
