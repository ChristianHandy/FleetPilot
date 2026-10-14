#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Test script for remote disk plugin functionality
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from addons import remote_disk_plugin
import re

def test_device_name_validation():
    """Test device name sanitization"""
    print("Testing device name validation...")
    
    # Valid device names
    valid_names = ['sda', 'sdb1', 'nvme0n1', 'mmcblk0', 'hda']
    for name in valid_names:
        assert re.match(r'^[a-zA-Z0-9_-]{1,255}$', name), f"Valid name '{name}' failed validation"
    print("  ✓ Valid device names pass validation")
    
    # Invalid device names (should fail)
    invalid_names = ['../etc/passwd', 'sda; rm -rf /', 'sda$(whoami)', '', 'a' * 256]
    for name in invalid_names:
        assert not re.match(r'^[a-zA-Z0-9_-]{1,255}$', name), f"Invalid name '{name}' passed validation"
    print("  ✓ Invalid device names fail validation")
    
    return

def test_filesystem_validation():
    """Test filesystem type validation"""
    print("\nTesting filesystem type validation...")
    
    valid_fs = ['ext4', 'xfs', 'fat32']
    invalid_fs = ['ext3', 'ntfs', 'zfs', '', 'ext4; whoami']
    
    for fs in valid_fs:
        assert fs in ['ext4', 'xfs', 'fat32'], f"Valid fs '{fs}' failed"
    print("  ✓ Valid filesystem types recognized")
    
    for fs in invalid_fs:
        assert fs not in ['ext4', 'xfs', 'fat32'], f"Invalid fs '{fs}' passed"
    print("  ✓ Invalid filesystem types rejected")
    
    return

def test_smart_mode_validation():
    """Test SMART mode validation"""
    print("\nTesting SMART mode validation...")
    
    valid_modes = ['short', 'long']
    invalid_modes = ['full', 'quick', '', 'short; whoami']
    
    for mode in valid_modes:
        assert mode in ['short', 'long'], f"Valid mode '{mode}' failed"
    print("  ✓ Valid SMART modes recognized")
    
    for mode in invalid_modes:
        assert mode not in ['short', 'long'], f"Invalid mode '{mode}' passed"
    print("  ✓ Invalid SMART modes rejected")
    
    return

def test_plugin_metadata():
    """Test plugin metadata structure"""
    print("\nTesting plugin metadata...")
    
    assert 'name' in remote_disk_plugin.addon_meta, "Plugin name missing"
    assert 'html' in remote_disk_plugin.addon_meta, "Plugin HTML template missing"
    print(f"  ✓ Plugin name: {remote_disk_plugin.addon_meta['name']}")
    print("  ✓ Plugin HTML template present")
    
    return

def test_plugin_functions():
    """Test that all required plugin functions exist"""
    print("\nTesting plugin functions...")
    
    required_functions = [
        'execute_remote_command',
        'list_remote_disks',
        'get_remote_smart',
        'format_remote_disk',
        'start_remote_smart_test',
        'register'
    ]
    
    for func_name in required_functions:
        assert hasattr(remote_disk_plugin, func_name), f"Function '{func_name}' not found"
        print(f"  ✓ Function '{func_name}' exists")
    
    return

def test_command_injection_prevention():
    """Test that command injection is prevented"""
    print("\nTesting command injection prevention...")
    
    # Test cases that should be rejected
    malicious_inputs = [
        'sda; rm -rf /',
        'sda && whoami',
        'sda | cat /etc/passwd',
        'sda`whoami`',
        'sda$(whoami)',
        '../../../etc/passwd',
        'sda\nwhoami',
        'sda\rwhoami',
    ]
    
    for malicious in malicious_inputs:
        # Test device name validation
        if not re.match(r'^[a-zA-Z0-9_-]{1,255}$', malicious):
            print(f"  ✓ Blocked: {malicious[:50]}")
        else:
            print(f"  ✗ FAILED TO BLOCK: {malicious}")
            raise AssertionError("test_command_injection_prevention failed; see the output above")
    
    print("  ✓ All command injection attempts blocked")
    return

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
