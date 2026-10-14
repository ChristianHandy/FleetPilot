# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pytest configuration."""
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    # Several older tests report failure by returning False instead of asserting.
    outcome = yield
    if outcome.get_result() is False:
        pytest.fail(f"{pyfuncitem.name} returned False")
