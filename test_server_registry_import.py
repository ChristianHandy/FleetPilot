"""The registry must import servers from the module databases FleetPilot actually writes."""
import sqlite3

import server_registry


def _db(path, sql, rows):
    con = sqlite3.connect(path)
    con.executescript(sql)
    for r in rows:
        con.execute(r)
    con.commit()
    con.close()


def test_imports_from_hw_monitor_fans_and_backups(tmp_path):
    hw = tmp_path / 'hw_monitor.db'
    _db(hw, "CREATE TABLE hw_servers (id INTEGER PRIMARY KEY, name TEXT, ip TEXT, ssh_port INTEGER, ssh_user TEXT, ssh_pass TEXT, enabled INTEGER DEFAULT 1);",
        ["INSERT INTO hw_servers(name, ip, ssh_port, ssh_user, ssh_pass) VALUES ('pve1', '192.0.2.11', 22, 'root', 'x')"])
    fans = tmp_path / 'fan_controller.db'
    _db(fans, "CREATE TABLE fc_devices (id INTEGER PRIMARY KEY, name TEXT, host TEXT, port INTEGER, username TEXT, password TEXT);",
        ["INSERT INTO fc_devices(name, host, port, username, password) VALUES ('rig', '192.0.2.12', 22, 'admin', 'gAAAAencrypted')"])
    backups = tmp_path / 'backup_controller.db'
    _db(backups, "CREATE TABLE backup_servers (id INTEGER PRIMARY KEY, name TEXT, host TEXT, port INTEGER, password TEXT, enabled INTEGER DEFAULT 1);",
        ["INSERT INTO backup_servers(name, host, port, password) VALUES ('pbs', 'https://192.0.2.13:8007', 8007, 'gAAAAencrypted')"])

    reg = server_registry.ServerRegistry(str(tmp_path))
    assert reg.import_from_hw_monitor_db(str(hw)) == 1
    assert reg.import_from_fan_controller_db(str(fans)) == 1
    assert reg.import_from_backup_db(str(backups)) == 1
    hosts = {s['name']: s for s in reg.list_servers()}
    assert hosts['pve1']['host'] == '192.0.2.11'
    assert hosts['pbs']['host'] == '192.0.2.13'
    # Encrypted module secrets are not copied into the registry.
    assert not hosts['rig'].get('password')
