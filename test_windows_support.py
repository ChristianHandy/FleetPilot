#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Test script for Windows support in the FleetPilot.
This verifies that Windows detection and update command generation works correctly.
"""

import sys
import os

# Add parent directory to path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from constants import is_windows, get_platform
from updater import get_update_command, SUPPORTED_DISTRIBUTIONS

def test_platform_detection():
    """Test platform detection functions"""
    print("Testing platform detection...")
    
    platform = get_platform()
    print(f"  Current platform: {platform}")
    
    is_win = is_windows()
    print(f"  Is Windows: {is_win}")
    
    print("✓ Platform detection functions work!\n")
    return

def test_supported_distributions():
    """Test that Windows is in supported distributions"""
    print("Testing supported distributions...")
    
    if 'windows' in SUPPORTED_DISTRIBUTIONS:
        print(f"  ✓ 'windows' is in SUPPORTED_DISTRIBUTIONS: {SUPPORTED_DISTRIBUTIONS}")
    else:
        print(f"  ✗ 'windows' is NOT in SUPPORTED_DISTRIBUTIONS: {SUPPORTED_DISTRIBUTIONS}")
        raise AssertionError("test_supported_distributions failed; see the output above")
    
    print("✓ Windows is supported!\n")
    return

def test_windows_update_commands():
    """Test Windows update command generation"""
    print("Testing Windows update commands...")
    
    try:
        # Test repository-only update (Windows Update only)
        cmd, desc = get_update_command('windows', repo_only=True)
        print("  Repository-only update:")
        print(f"    Description: {desc}")
        print(f"    Command starts with: {cmd[:80]}...")
        
        if 'powershell' not in cmd.lower():
            print("  ✗ ERROR: Windows command should use PowerShell")
            raise AssertionError("test_windows_update_commands failed; see the output above")
        if 'Get-WindowsUpdate' not in cmd:
            print("  ✗ ERROR: Windows command should use Get-WindowsUpdate")
            raise AssertionError("test_windows_update_commands failed; see the output above")
        
        print("  ✓ Repository-only command is correct")
        
        # Test full update (Windows Update + winget)
        cmd, desc = get_update_command('windows', repo_only=False)
        print("  Full update:")
        print(f"    Description: {desc}")
        print(f"    Command starts with: {cmd[:80]}...")
        
        if 'powershell' not in cmd.lower():
            print("  ✗ ERROR: Windows command should use PowerShell")
            raise AssertionError("test_windows_update_commands failed; see the output above")
        if 'winget upgrade' not in cmd:
            print("  ✗ ERROR: Full update should include winget upgrade")
            raise AssertionError("test_windows_update_commands failed; see the output above")
        
        print("  ✓ Full update command is correct")
        
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        raise AssertionError("test_windows_update_commands failed; see the output above")
    
    print("✓ Windows update commands work correctly!\n")
    return

def test_linux_distributions_still_work():
    """Test that existing Linux distributions still work"""
    print("Testing Linux distributions still work...")
    
    linux_distros = ['ubuntu', 'debian', 'fedora', 'centos', 'arch']
    
    for distro in linux_distros:
        try:
            cmd, desc = get_update_command(distro, repo_only=False)
            print(f"  ✓ {distro}: {desc}")
        except Exception as e:
            print(f"  ✗ {distro}: ERROR - {e}")
            raise AssertionError("test_linux_distributions_still_work failed; see the output above")
    
    print("✓ All Linux distributions still work!\n")
    return

def test_unsupported_distribution():
    """Test that unsupported distributions raise ValueError"""
    print("Testing unsupported distribution handling...")
    
    try:
        cmd, desc = get_update_command('unsupported_os', repo_only=False)
        print("  ✗ ERROR: Should have raised ValueError for unsupported OS")
        raise AssertionError("test_unsupported_distribution failed; see the output above")
    except ValueError as e:
        print(f"  ✓ Correctly raised ValueError: {e}")
    except Exception as e:
        print(f"  ✗ ERROR: Unexpected exception: {e}")
        raise AssertionError("test_unsupported_distribution failed; see the output above")
    
    print("✓ Unsupported distribution handling works!\n")
    return

def test_imports():
    """Test that all necessary imports work"""
    print("Testing imports...")
    try:
        import updater  # noqa: F401  (tests the import)
        import constants  # noqa: F401  (tests the import)
        print("✓ All imports successful!\n")
        return
    except Exception as e:
        print(f"✗ Import failed: {e}\n")
        raise AssertionError("test_imports failed; see the output above")

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
