# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fuzz the parsers that read text FleetPilot does not control.

Router, disk and SOAP output comes from devices on the network, so a broken or
hostile device must not be able to crash FleetPilot or make a parser hang.

    pip install atheris
    python fuzz/fuzz_parsers.py -max_total_time=60

Parsers and validators may reject input with ValueError (that is how bad device
output reaches the user as "invalid response"). Any other exception is a finding,
and so is a slow input (-timeout=1: one second per input).
"""
import os
import sys

import atheris

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("FLEETPILOT_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".data"))

with atheris.instrument_imports():
    import arp_tracker
    import disktool_core
    import router_manager as rm
    import smart_manager

TEXT_PARSERS = [
    rm.parse_meminfo, rm.parse_uptime, rm.parse_loadavg, rm.parse_dnsmasq_leases,
    rm.parse_isc_leases, rm.parse_kea_csv, rm.parse_ip_json, rm.parse_linux_ifconfig,
    rm.parse_bsd_ifconfig, rm.parse_openwrt_interfaces, rm.parse_opkg_upgradable,
    rm.parse_routeros_kv, rm.parse_routeros_terse, rm.parse_routeros_uptime,
    rm.parse_routeros_size, rm.parse_soap_response, rm.parse_fritz_hostlist,
    rm.parse_fritz_mesh, smart_manager.parse_smartctl_output,
]
VALIDATORS = [
    disktool_core.sanitize_device_name, disktool_core.validate_ssh_user,
    arp_tracker.validate_ip_address, arp_tracker.validate_network_prefix,
]


def test_one_input(data):
    fdp = atheris.FuzzedDataProvider(data)
    choice = fdp.ConsumeIntInRange(0, len(TEXT_PARSERS) + len(VALIDATORS) - 1)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    target = TEXT_PARSERS[choice] if choice < len(TEXT_PARSERS) else VALIDATORS[choice - len(TEXT_PARSERS)]
    try:
        target(text)
    except ValueError:
        pass


def main():
    atheris.Setup(sys.argv + ["-timeout=1"], test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
