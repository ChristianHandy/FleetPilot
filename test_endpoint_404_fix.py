#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Test script to verify the /disks/pluginmanager/ endpoint fix
Tests that the endpoint exists and old endpoint returns 404
"""
import sys
import os

# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_endpoint_exists():
    """Test that /disks/pluginmanager/ endpoint exists"""
    print("Testing that /disks/pluginmanager/ endpoint exists...")
    try:
        from app import app
        
        # Create test client
        with app.test_client() as client:
            # Test without authentication (should redirect to login, not 404)
            response = client.get('/disks/pluginmanager/')
            print(f"  Status code: {response.status_code}")
            
            # Should be 302 (redirect) not 404
            if response.status_code == 404:
                print("✗ Endpoint returns 404 - endpoint does not exist")
                raise AssertionError("test_endpoint_exists failed; see the output above")
            elif response.status_code == 302:
                # Check redirect location
                location = response.headers.get('Location', '')
                print(f"  Redirects to: {location}")
                if 'login' in location.lower() or location.startswith('/?next='):
                    print("✓ Endpoint exists and redirects to login (as expected)")
                    return
                else:
                    print(f"✗ Unexpected redirect location: {location}")
                    raise AssertionError("test_endpoint_exists failed; see the output above")
            else:
                print(f"✓ Endpoint exists (status {response.status_code})")
                return
                
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test_endpoint_exists failed; see the output above")

def test_old_endpoint_404():
    """Test that old /pluginmanager/ endpoint returns 404"""
    print("\nTesting that old /pluginmanager/ endpoint returns 404...")
    try:
        from app import app
        
        # Create test client
        with app.test_client() as client:
            # Test old endpoint
            response = client.get('/pluginmanager/')
            print(f"  Status code: {response.status_code}")
            
            if response.status_code == 404:
                print("✓ Old endpoint correctly returns 404")
                return
            else:
                print(f"✗ Old endpoint should return 404 but returns {response.status_code}")
                raise AssertionError("test_old_endpoint_404 failed; see the output above")
                
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test_old_endpoint_404 failed; see the output above")

def test_endpoint_consistency():
    """Test that plugin manager endpoint is consistent with other disk routes"""
    print("\nTesting endpoint consistency with other disk routes...")
    try:
        from app import app
        
        # Get all routes
        disk_routes = []
        for rule in app.url_map.iter_rules():
            if rule.rule.startswith('/disks'):
                disk_routes.append(rule.rule)
        
        print(f"  Found {len(disk_routes)} disk-related routes")
        
        # Check that plugin manager is under /disks
        plugin_manager_routes = [r for r in disk_routes if 'pluginmanager' in r.lower()]
        
        if plugin_manager_routes:
            print(f"  Plugin manager routes: {plugin_manager_routes}")
            print("✓ Plugin manager endpoint is under /disks hierarchy")
            return
        else:
            print("✗ No plugin manager routes found under /disks")
            raise AssertionError("test_endpoint_consistency failed; see the output above")
            
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test_endpoint_consistency failed; see the output above")

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
