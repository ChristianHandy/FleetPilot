#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Test script for plugin manager functionality
"""
import sys
import os
from pathlib import Path

# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_plugin_manager_import():
    """Test that plugin manager can be imported"""
    print("Testing plugin manager import...")
    try:
        from addons import plugin_manager  # noqa: F401  (tests the import)
        print("✓ Plugin manager imported successfully")
        return
    except Exception as e:
        print(f"✗ Failed to import plugin manager: {e}")
        raise AssertionError("test_plugin_manager_import failed; see the output above")

def test_plugin_manager_blueprint():
    """Test that plugin manager blueprint is configured correctly"""
    print("\nTesting plugin manager blueprint...")
    try:
        from addons import plugin_manager  # noqa: F401  (tests the import)
        assert hasattr(plugin_manager, 'blueprint'), "Blueprint not found"
        assert plugin_manager.blueprint.url_prefix == '/disks/pluginmanager', "Incorrect URL prefix"
        print("✓ Plugin manager blueprint configured correctly")
        return
    except Exception as e:
        print(f"✗ Blueprint test failed: {e}")
        raise AssertionError("test_plugin_manager_blueprint failed; see the output above")

def test_plugin_validation():
    """Test plugin ID validation"""
    print("\nTesting plugin ID validation...")
    try:
        import re
        
        # Test valid plugin IDs
        valid_ids = ['example_plugin', 'backup_plugin', 'test123', 'my_plugin_v2']
        for pid in valid_ids:
            assert re.match(r'^[a-zA-Z0-9_]+$', pid), f"Valid ID rejected: {pid}"
        
        # Test invalid plugin IDs
        invalid_ids = ['../etc/passwd', 'plugin-name', 'plugin.py', 'plugin name', 'plugin;rm']
        for pid in invalid_ids:
            assert not re.match(r'^[a-zA-Z0-9_]+$', pid), f"Invalid ID accepted: {pid}"
        
        print("✓ Plugin ID validation working correctly")
        return
    except Exception as e:
        print(f"✗ Validation test failed: {e}")
        raise AssertionError("test_plugin_validation failed; see the output above")

def test_addon_loader_status():
    """Test that addon loader includes file information"""
    print("\nTesting addon loader status...")
    try:
        from addon_loader import AddonManager
        from flask import Flask
        import disktool_core
        
        app = Flask(__name__)
        addon_mgr = AddonManager(app, disktool_core)
        addon_mgr.load_addons('addons', 'templates/addons')
        
        # Check that status includes file information
        for plugin in addon_mgr.status:
            assert 'file' in plugin, f"Plugin {plugin.get('name')} missing 'file' field"
            assert 'name' in plugin, "Plugin missing 'name' field"
            assert 'status' in plugin, f"Plugin {plugin.get('name')} missing 'status' field"
        
        print(f"✓ Addon loader status includes file information for {len(addon_mgr.status)} plugins")
        return
    except Exception as e:
        print(f"✗ Addon loader test failed: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test_addon_loader_status failed; see the output above")

def test_remote_plugin_json_format():
    """Test that remote plugin JSON format is valid"""
    print("\nTesting remote plugin JSON format...")
    try:
        # Sample plugin data
        plugin_data = {
            "plugins": [
                {
                    "id": "test_plugin",
                    "name": "Test Plugin",
                    "description": "A test plugin",
                    "version": "1.0.0",
                    "author": "Test Author",
                    "url": "https://example.com/test_plugin.py"
                }
            ]
        }
        
        # Validate required fields
        for plugin in plugin_data['plugins']:
            assert 'id' in plugin, "Missing 'id' field"
            assert 'name' in plugin, "Missing 'name' field"
            assert 'description' in plugin, "Missing 'description' field"
            assert 'version' in plugin, "Missing 'version' field"
            assert 'author' in plugin, "Missing 'author' field"
            assert 'url' in plugin, "Missing 'url' field"
            
            # Validate ID format
            import re
            assert re.match(r'^[a-zA-Z0-9_]+$', plugin['id']), f"Invalid plugin ID: {plugin['id']}"
        
        print("✓ Remote plugin JSON format is valid")
        return
    except Exception as e:
        print(f"✗ JSON format test failed: {e}")
        raise AssertionError("test_remote_plugin_json_format failed; see the output above")

def test_security_checks():
    """Test security features"""
    print("\nTesting security checks...")
    try:
        # Test that plugin manager checks admin role
        from addons import plugin_manager  # noqa: F401  (tests the import)
        import inspect
        
        # Verify that install and uninstall functions exist
        assert hasattr(plugin_manager, 'install_plugin'), "install_plugin function missing"
        assert hasattr(plugin_manager, 'uninstall_plugin'), "uninstall_plugin function missing"
        
        # Check that they check for admin role
        install_source = inspect.getsource(plugin_manager.install_plugin)
        uninstall_source = inspect.getsource(plugin_manager.uninstall_plugin)
        
        assert 'current_user_has_role' in install_source, "Install doesn't check user role"
        assert 'current_user_has_role' in uninstall_source, "Uninstall doesn't check user role"
        assert 'admin' in install_source, "Install doesn't require admin role"
        assert 'admin' in uninstall_source, "Uninstall doesn't require admin role"
        
        # Verify plugin ID validation exists
        assert 'regex' in install_source.lower() or 're.match' in install_source, "Install doesn't validate plugin ID"
        assert 'regex' in uninstall_source.lower() or 're.match' in uninstall_source, "Uninstall doesn't validate plugin file"
        
        print("✓ Security checks in place")
        return
    except Exception as e:
        print(f"✗ Security test failed: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test_security_checks failed; see the output above")

def test_path_sanitization():
    """Test path sanitization to prevent path traversal attacks"""
    print("\nTesting path sanitization...")
    try:
        from addons import plugin_manager  # noqa: F401  (tests the import)
        
        # Test valid paths
        base_dir = 'addons'
        valid_path = plugin_manager.sanitize_path(base_dir, 'test_plugin.py')
        assert valid_path is not None, "Valid path rejected"
        assert base_dir in str(valid_path), "Valid path doesn't contain base directory"
        assert 'test_plugin.py' in str(valid_path), "Valid path doesn't contain filename"
        
        # Test path traversal attacks
        traversal_attempts = [
            '../etc/passwd',
            '../../etc/passwd',
            '../../../etc/passwd',
            '..\\..\\windows\\system32',
            'subdir/../../../etc/passwd',
            './../../etc/passwd',
            'addons/../../etc/passwd',
        ]
        
        base_path = Path(base_dir).resolve()
        for attempt in traversal_attempts:
            result = plugin_manager.sanitize_path(base_dir, attempt)
            # Path traversal should either return None or a path still within addons
            if result is not None:
                # If a result is returned, verify it's still within the base directory using secure method
                try:
                    result.relative_to(base_path)
                    # If we get here, the path is within base (which is acceptable)
                except ValueError:
                    # Path escaped the base directory - this is a failure
                    assert False, f"Path traversal not blocked: {attempt} -> {result}"
        
        # Test with templates directory
        template_base = 'templates/addons'
        valid_template = plugin_manager.sanitize_path(template_base, 'test.html')
        assert valid_template is not None, "Valid template path rejected"
        
        # Test absolute path attempts
        if os.name != 'nt':  # Unix-like systems
            abs_path_result = plugin_manager.sanitize_path(base_dir, '/etc/passwd')
            if abs_path_result is not None:
                try:
                    abs_path_result.relative_to(base_path)
                    # If we get here, it's contained (acceptable)
                except ValueError:
                    # Path escaped - this is a failure
                    assert False, "Absolute path not properly contained"
        
        print("✓ Path sanitization working correctly")
        return
    except Exception as e:
        print(f"✗ Path sanitization test failed: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("test_path_sanitization failed; see the output above")


def test_render_hooks_logs_error_and_hides_exception_from_page(caplog, capsys, tmp_path):
    """Test that render_hooks logs hook errors and writes only a fixed HTML comment (#161)."""
    import logging
    from flask import Flask
    from addon_loader import AddonManager

    plugin_dir = tmp_path / "addons"
    tpl_dir = tmp_path / "templates"
    plugin_dir.mkdir()
    tpl_dir.mkdir()
    (plugin_dir / "broken_widget.py").write_text(
        'def _boom(*args, **kwargs):\n'
        '    raise Exception("--><b>x</b>")\n'
        'addon_meta = {"name": "Broken Widget", "dashboard_widget": _boom}\n',
        encoding="utf-8",
    )

    app = Flask(__name__)
    addon_mgr = AddonManager(app, None)
    addon_mgr.load_addons(str(plugin_dir), str(tpl_dir))
    assert addon_mgr.status[0]["status"] == "ok"

    with caplog.at_level(logging.ERROR, logger="fleetpilot.plugins"):
        rendered = addon_mgr.render_hooks("dashboard_widgets")

    assert "--><b>x</b>" not in rendered
    assert "<b>x</b>" not in rendered
    assert rendered == "<!-- plugin hook failed, see log -->"
    assert capsys.readouterr().out == ""
    assert any(
        "Broken Widget" in rec.getMessage() and "--><b>x</b>" in (rec.exc_text or "")
        for rec in caplog.records
    )
    assert addon_mgr.status[0]["status"] == "error"


def test_hook_dispatchers_log_errors_with_plugin_name(caplog, capsys, tmp_path):
    """Test that fire_hooks, get_sidebar_links, and get_host_detail_tabs log instead of printing (#161)."""
    import logging
    from flask import Flask
    from addon_loader import AddonManager

    plugin_dir = tmp_path / "addons"
    tpl_dir = tmp_path / "templates"
    plugin_dir.mkdir()
    tpl_dir.mkdir()
    (plugin_dir / "noisy_plugin.py").write_text(
        'def _fail(*args, **kwargs):\n'
        '    raise RuntimeError("hook exploded")\n'
        'addon_meta = {\n'
        '    "name": "Noisy Plugin",\n'
        '    "update_post": _fail,\n'
        '    "sidebar_link": _fail,\n'
        '    "host_detail_tab": _fail,\n'
        '}\n',
        encoding="utf-8",
    )

    app = Flask(__name__)
    addon_mgr = AddonManager(app, None)
    addon_mgr.load_addons(str(plugin_dir), str(tpl_dir))

    with caplog.at_level(logging.ERROR, logger="fleetpilot.plugins"):
        addon_mgr.fire_hooks("update_post_hook", {}, {})
        assert addon_mgr.get_sidebar_links() == []
        assert addon_mgr.get_host_detail_tabs({"name": "nas"}) == []

    assert capsys.readouterr().out == ""
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("Noisy Plugin" in m and "update_post_hook" in m for m in messages)
    assert any("Noisy Plugin" in m and "sidebar_links" in m for m in messages)
    assert any("Noisy Plugin" in m and "host_detail_tabs" in m for m in messages)
    assert addon_mgr.status[0]["status"] == "error"


def test_example_and_tutorial_plugins_use_logger_not_print(caplog, capsys):
    """Test that example_plugin and tutorial_plugin log via fleetpilot.plugins instead of print (#161)."""
    import logging
    from addons import example_plugin, tutorial_plugin

    with caplog.at_level(logging.INFO, logger="fleetpilot.plugins"):
        example_plugin.register(None, None)
        tutorial_plugin.register(None, None)

    assert capsys.readouterr().out == ""
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("example_plugin" in m for m in messages)
    assert any("tutorial_plugin" in m for m in messages)


def test_example_dashboard_widget_renders_online_offline_and_unknown_counts():
    """Test that example_dashboard_widget and _dashboard_widget_payload report real status counts (#144)."""
    import app as fp_app
    from addons import example_dashboard_widget

    hosts_cfg = {
        "pve1": {"host": "10.0.0.1", "user": "root", "management": {"state": "manageable"}},
        "nas": {"host": "10.0.0.2", "user": "admin", "management": {"state": "web_only"}},
        "old-box": {"host": "10.0.0.3", "user": "root", "management": {"state": "unreachable"}},
        "new-box": {"host": "10.0.0.4", "user": "root"},
    }
    widget_hosts, widget_stats = fp_app._dashboard_widget_payload(hosts_cfg)

    assert widget_stats == {"total": 4, "online": 2, "offline": 1, "unknown": 1}
    by_name = {h["name"]: h["status"] for h in widget_hosts}
    assert by_name == {
        "pve1": "online",
        "nas": "online",
        "old-box": "offline",
        "new-box": "unknown",
    }

    html = example_dashboard_widget._render_widget(widget_hosts, widget_stats)
    assert "50%" in html
    assert "Online: <strong" in html and ">2</strong>" in html
    assert "Offline: <strong" in html and ">1</strong>" in html
    assert "Unknown: <strong" in html and ">1</strong>" in html
    assert "Total: <strong" in html and ">4</strong>" in html

    # Direct host-list call without stats dictionary (known online and offline only)
    direct_html = example_dashboard_widget._render_widget(
        [
            {"name": "h1", "status": "online"},
            {"name": "h2", "status": "online"},
            {"name": "h3", "status": "online"},
            {"name": "h4", "status": "offline"},
        ],
        {},
    )
    assert "75%" in direct_html
    assert ">3</strong>" in direct_html
    assert ">1</strong>" in direct_html
    assert "Unknown:" not in direct_html


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
