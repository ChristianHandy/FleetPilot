# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for SMART output parsing and disk health classification in smart_manager."""

import pytest

import smart_manager

SAMPLE_ATA_SMARTCTL = """\
smartctl 7.4 2023-08-01 r5530 [x86_64-linux-6.8.0] (local build)
=== START OF READ SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED

SMART Attributes Data Structure revision number: 16
Vendor Specific SMART Attributes with Thresholds:
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  5 Reallocated_Sector_Ct   0x0033   100   100   010    Pre-fail  Always       -       0
  9 Power_On_Hours          0x0032   099   099   000    Old_age   Always       -       4821
194 Temperature_Celsius     0x0022   064   045   000    Old_age   Always       -       36 (Min/Max 21/45)
197 Current_Pending_Sector  0x0012   100   100   000    Old_age   Always       -       2
198 Offline_Uncorrectable   0x0010   100   100   000    Offline   Offline      -       1
"""

SAMPLE_ATA_AIRFLOW_TEMP = """\
SMART overall-health self-assessment test result: FAILED!
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  5 Reallocated_Sector_Ct   0x0033   100   100   010    Pre-fail  Always       -       3
  9 Power_On_Hours          0x0032   098   098   000    Old_age   Always       -       8100
190 Airflow_Temperature_Cel 0x0022   059   051   045    Old_age   Always       -       41 (Min/Max 24/49)
"""

SAMPLE_NVME_SMARTCTL = """\
smartctl 7.4 2023-08-01 r5530 [x86_64-linux-6.8.0] (local build)
=== START OF SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED

SMART/Health Information (NVMe Log 0x02)
Critical Warning:                   0x00
Temperature:                        38 Celsius
Available Spare:                    100%
Available Spare Threshold:          10%
Percentage Used:                    2%
Data Units Read:                    12,345,678 [6.32 TB]
Data Units Written:                 8,765,432 [4.48 TB]
Power Cycles:                       142
Power On Hours:                     12,345
Unsafe Shutdowns:                   12
Media and Data Integrity Errors:    0
Error Information Log Entries:      0
"""


def _base_parsed(**overrides):
    data = {
        "overall_status": "PASSED",
        "temp": 35,
        "poh": 5000,
        "reallocated": 0,
        "pending": 0,
        "uncorrectable": 0,
        "attributes": [],
    }
    data.update(overrides)
    return data


def test_parse_smartctl_output_ata_table():
    parsed = smart_manager.parse_smartctl_output(SAMPLE_ATA_SMARTCTL)

    assert parsed["overall_status"] == "PASSED"
    assert parsed["temp"] == 36
    assert parsed["poh"] == 4821
    assert parsed["reallocated"] == 0
    assert parsed["pending"] == 2
    assert parsed["uncorrectable"] == 1

    by_id = {attr["id"]: attr for attr in parsed["attributes"]}
    assert set(by_id.keys()) == {5, 9, 194, 197, 198}
    assert by_id[5] == {
        "id": 5,
        "name": "Reallocated_Sector_Ct",
        "value": 100,
        "worst": 100,
        "threshold": 10,
        "raw_value": 0,
        "raw_string": "0",
    }
    assert by_id[194] == {
        "id": 194,
        "name": "Temperature_Celsius",
        "value": 64,
        "worst": 45,
        "threshold": 0,
        "raw_value": 36,
        "raw_string": "36 (Min/Max 21/45)",
    }


def test_parse_smartctl_output_ata_airflow_temperature_fallback_and_failed_status():
    parsed = smart_manager.parse_smartctl_output(SAMPLE_ATA_AIRFLOW_TEMP)

    assert parsed["overall_status"] == "FAILED"
    assert parsed["temp"] == 41
    assert parsed["poh"] == 8100
    assert parsed["reallocated"] == 3


def test_parse_smartctl_output_ata_194_takes_precedence_over_190():
    both_temps = (
        SAMPLE_ATA_AIRFLOW_TEMP
        + "194 Temperature_Celsius     0x0022   064   045   000    Old_age   Always       -       34\n"
    )
    parsed = smart_manager.parse_smartctl_output(both_temps)
    assert parsed["temp"] == 34


def test_parse_smartctl_output_nvme_fallback():
    parsed = smart_manager.parse_smartctl_output(SAMPLE_NVME_SMARTCTL)

    assert parsed["overall_status"] == "PASSED"
    assert parsed["temp"] == 38
    assert parsed["poh"] == 12345
    assert parsed["reallocated"] == 0
    assert parsed["pending"] == 0
    assert parsed["uncorrectable"] == 0
    assert parsed["attributes"] == []


@pytest.mark.parametrize(
    "raw_output",
    [
        "",
        "   \n\n  ",
        "smartctl: command not found\nrandom garbage line without headers",
    ],
)
def test_parse_smartctl_output_empty_or_unrecognised(raw_output):
    parsed = smart_manager.parse_smartctl_output(raw_output)
    assert parsed == {
        "overall_status": "UNKNOWN",
        "temp": None,
        "poh": None,
        "reallocated": 0,
        "pending": 0,
        "uncorrectable": 0,
        "attributes": [],
    }


def test_classify_health_good_disk():
    assert smart_manager.classify_health(_base_parsed()) == "GOOD"


def test_classify_health_failed_overall_status_takes_precedence():
    parsed = _base_parsed(overall_status="FAILED", reallocated=0, temp=30)
    assert smart_manager.classify_health(parsed) == "FAILED"


@pytest.mark.parametrize(
    "field",
    ["reallocated", "pending", "uncorrectable"],
)
def test_classify_health_nonzero_sector_counters_are_critical(field):
    parsed = _base_parsed(**{field: 1})
    assert smart_manager.classify_health(parsed) == "CRITICAL"


@pytest.mark.parametrize(
    "temp,expected_rating",
    [
        (None, "GOOD"),
        (smart_manager.TEMP_WARNING - 1, "GOOD"),
        (smart_manager.TEMP_WARNING, "WARNING"),
        (smart_manager.TEMP_CRITICAL - 1, "WARNING"),
        (smart_manager.TEMP_CRITICAL, "CRITICAL"),
        (smart_manager.TEMP_CRITICAL + 10, "CRITICAL"),
    ],
)
def test_classify_health_temperature_bands(temp, expected_rating):
    parsed = _base_parsed(temp=temp)
    assert smart_manager.classify_health(parsed) == expected_rating


def test_classify_health_power_on_hours_thresholds():
    # POH_CRITICAL returns WARNING.
    assert (
        smart_manager.classify_health(_base_parsed(poh=smart_manager.POH_CRITICAL))
        == "WARNING"
    )
    assert (
        smart_manager.classify_health(
            _base_parsed(poh=smart_manager.POH_CRITICAL + 10_000)
        )
        == "WARNING"
    )

    # POH_WARNING (30,000h) is defined in smart_manager.py but not checked in
    # classify_health, so disks between POH_WARNING and POH_CRITICAL - 1 are rated GOOD.
    assert smart_manager.POH_WARNING < smart_manager.POH_CRITICAL
    assert (
        smart_manager.classify_health(_base_parsed(poh=smart_manager.POH_WARNING))
        == "GOOD"
    )
    assert (
        smart_manager.classify_health(_base_parsed(poh=smart_manager.POH_CRITICAL - 1))
        == "GOOD"
    )


@pytest.mark.parametrize("attr_id,attr_name", list(smart_manager.CRITICAL_ATTRS.items()))
def test_classify_health_critical_attribute_at_or_below_threshold(attr_id, attr_name):
    parsed = _base_parsed(
        attributes=[
            {
                "id": attr_id,
                "name": attr_name,
                "value": 10,
                "worst": 10,
                "threshold": 10,
                "raw_value": 0,
                "raw_string": "0",
            }
        ]
    )
    assert smart_manager.classify_health(parsed) == "CRITICAL"


@pytest.mark.parametrize("attr_id,attr_name", list(smart_manager.WARNING_ATTRS.items()))
def test_classify_health_warning_attribute_at_or_below_threshold(attr_id, attr_name):
    parsed = _base_parsed(
        attributes=[
            {
                "id": attr_id,
                "name": attr_name,
                "value": 15,
                "worst": 15,
                "threshold": 20,
                "raw_value": 0,
                "raw_string": "0",
            }
        ]
    )
    assert smart_manager.classify_health(parsed) == "WARNING"


def test_classify_health_zero_threshold_does_not_trigger_alert():
    parsed = _base_parsed(
        attributes=[
            {
                "id": 5,
                "name": "Reallocated_Sector_Ct",
                "value": 0,
                "worst": 0,
                "threshold": 0,
                "raw_value": 0,
                "raw_string": "0",
            }
        ]
    )
    assert smart_manager.classify_health(parsed) == "GOOD"
