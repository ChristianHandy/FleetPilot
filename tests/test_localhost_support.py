#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Test script for localhost support in the FleetPilot.
This verifies that localhost detection and handling works correctly.
"""

import sys
import os

# Add parent directory to path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from constants import is_localhost

def test_is_localhost():
    """Test the is_localhost function"""
    print("Testing is_localhost function...")
    
    # Test cases that should return True
    localhost_values = ['localhost', 'LOCALHOST', 'Localhost', '127.0.0.1', '::1', '0.0.0.0']
    for value in localhost_values:
        result = is_localhost(value)
        status = "✓" if result else "✗"
        print(f"  {status} is_localhost('{value}') = {result} (expected True)")
        if not result:
            print("    ERROR: Expected True but got False")
            raise AssertionError("test_is_localhost failed; see the output above")
    
    # Test cases that should return False
    remote_values = ['192.168.1.1', 'example.com', 'remote-server', '10.0.0.1']
    for value in remote_values:
        result = is_localhost(value)
        status = "✓" if not result else "✗"
        print(f"  {status} is_localhost('{value}') = {result} (expected False)")
        if result:
            print("    ERROR: Expected False but got True")
            raise AssertionError("test_is_localhost failed; see the output above")
    
    print("✓ All is_localhost tests passed!\n")
    return

def test_imports():
    """Test that all necessary imports work"""
    print("Testing imports...")
    try:
        import updater  # noqa: F401  (tests the import)
        import app  # noqa: F401  (tests the import)
        print("✓ All imports successful!\n")
        return
    except Exception as e:
        print(f"✗ Import failed: {e}\n")
        raise AssertionError("test_imports failed; see the output above")

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
