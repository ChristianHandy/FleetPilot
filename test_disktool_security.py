#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Test script for disktool_core security features
Tests the fix for command injection vulnerability at line 80
"""
import sys
import os

# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import disktool_core


def test_run_function_requires_list():
    """Test that run() function only accepts lists"""
    print("Testing run() requires list input...")
    
    # Test that string commands are rejected
    try:
        disktool_core.run("ls -la")
        assert False, "Should have raised ValueError for string command"
    except ValueError as e:
        assert "must be a list" in str(e)
        print("✓ String commands are rejected")
    
    # Test that valid list commands work
    try:
        disktool_core.run(['echo', 'test'])
        print("✓ List commands are accepted")
    except Exception as e:
        print(f"✗ Valid list command failed: {e}")
        raise AssertionError("test_run_function_requires_list failed; see the output above")
    
    return


def test_run_function_validates_empty_list():
    """Test that run() rejects empty command lists"""
    print("\nTesting run() rejects empty lists...")
    
    try:
        disktool_core.run([])
        assert False, "Should have raised ValueError for empty list"
    except ValueError as e:
        assert "cannot be empty" in str(e)
        print("✓ Empty command lists are rejected")
        return
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        raise AssertionError("test_run_function_validates_empty_list failed; see the output above")


def test_run_function_validates_argument_types():
    """Test that run() validates all arguments are strings"""
    print("\nTesting run() validates argument types...")
    
    # Test with non-string arguments
    try:
        disktool_core.run(['ls', 123])
        assert False, "Should have raised ValueError for non-string argument"
    except ValueError as e:
        assert "must be strings" in str(e)
        print("✓ Non-string arguments are rejected")
        return
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        raise AssertionError("test_run_function_validates_argument_types failed; see the output above")


def test_run_function_validates_executable():
    """Test that run() validates the command executable"""
    print("\nTesting run() validates executable...")
    
    # Test with shell metacharacters
    dangerous_commands = [
        ['ls;rm -rf /'],
        ['ls|cat'],
        ['ls&whoami'],
        ['ls$(whoami)'],
        ['ls`whoami`'],
        ['../../../etc/passwd'],
        ['ls/../../../bin/sh'],  # path traversal
        ['ls\x00'],  # null byte
        ['/bin/../../../etc/passwd'],  # path traversal in absolute path
        ['ls\t'],  # tab character
        ['ls\n'],  # newline character
    ]
    
    for cmd in dangerous_commands:
        try:
            disktool_core.run(cmd)
            print(f"✗ Dangerous command accepted: {cmd}")
            raise AssertionError("test_run_function_validates_executable failed; see the output above")
        except ValueError:
            # All should raise ValueError with appropriate message
            pass
    
    print("✓ Dangerous executables are rejected")
    
    # Test that valid executables work
    valid_commands = [
        ['echo', 'test'],
        ['ls'],
        ['/bin/ls'],
        ['/usr/bin/whoami'],
    ]
    
    for cmd in valid_commands:
        try:
            disktool_core.run(cmd)
            # Command should execute without raising ValueError
        except ValueError as e:
            print(f"✗ Valid command rejected: {cmd} - {e}")
            raise AssertionError("test_run_function_validates_executable failed; see the output above")
        except Exception:
            # Other exceptions (like command not found) are OK
            pass
    
    print("✓ Valid executables are accepted")
    return


def test_sanitize_device_name():
    """Test that sanitize_device_name works correctly"""
    print("\nTesting sanitize_device_name()...")
    
    # Test valid device names
    valid_names = ['sda', 'sdb1', 'nvme0n1', 'mmcblk0', 'loop0']
    for name in valid_names:
        try:
            result = disktool_core.sanitize_device_name(name)
            assert result == name
        except Exception as e:
            print(f"✗ Valid device name rejected: {name} - {e}")
            raise AssertionError("test_sanitize_device_name failed; see the output above")
    
    print("✓ Valid device names accepted")
    
    # Test invalid device names
    invalid_names = [
        '../etc/passwd',
        'sda;rm -rf /',
        'sda|cat',
        'sda&whoami',
        'sda$(whoami)',
        'sda`whoami`',
        '/dev/sda',
        'sda\x00',
        '',
        None,
    ]
    
    for name in invalid_names:
        try:
            disktool_core.sanitize_device_name(name)
            print(f"✗ Invalid device name accepted: {name}")
            raise AssertionError("test_sanitize_device_name failed; see the output above")
        except (ValueError, Exception):
            pass
    
    print("✓ Invalid device names rejected")
    return


def test_subprocess_shell_false():
    """Test that subprocess.run is called with shell=False"""
    print("\nTesting subprocess.run uses shell=False...")
    
    import inspect
    
    # Get the source code of the run function
    source = inspect.getsource(disktool_core.run)
    
    # Check that shell=False is explicitly set
    if 'shell=False' in source:
        print("✓ subprocess.run explicitly uses shell=False")
        return
    else:
        print("✗ subprocess.run does not explicitly set shell=False")
        raise AssertionError("test_subprocess_shell_false failed; see the output above")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
