# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""An SSH client that runs commands on emulated machines (replaces ssh_helper.create_client)."""
import io

from . import net


class _Session:
    def __init__(self, device, command, user):
        self.device, self.command, self.user = device, command, user
        self.stdin = []
        self.result = None

    def run(self):
        if self.result is None:
            rc, out, err = self.device.shell(self.command, "".join(self.stdin), self.user)
            self.result = (rc, io.BytesIO(out.encode()), io.BytesIO(err.encode()))
        return self.result


class _Channel:
    def __init__(self, session):
        self.session = session

    def recv_exit_status(self):
        return self.session.run()[0]

    def exit_status_ready(self):
        return True

    def shutdown_write(self):
        pass

    def settimeout(self, value):
        pass

    def close(self):
        pass


class _In:
    def __init__(self, session):
        self.session, self.channel = session, _Channel(session)

    def write(self, data):
        self.session.stdin.append(data.decode(errors="replace") if isinstance(data, bytes) else str(data))

    def flush(self):
        pass

    def close(self):
        pass


class _Out:
    def __init__(self, session, index):
        self.session, self.index, self.channel = session, index, _Channel(session)

    def _buf(self):
        return self.session.run()[self.index]

    def read(self, size=-1):
        return self._buf().read(size)

    def readline(self, size=-1):
        return self._buf().readline(size).decode(errors="replace")

    def readlines(self):
        return [line.decode(errors="replace") for line in self._buf().readlines()]

    def __iter__(self):
        return iter(self.readlines())

    def close(self):
        pass


class _SFTP:
    def __init__(self, device):
        self.device = device

    def _file(self, path, mode="r"):
        device = self.device

        class _F(io.StringIO):
            def close(inner):
                if "w" in mode or "a" in mode:
                    device.files[path] = inner.getvalue()
                super().close()

            def __enter__(inner):
                return inner

            def __exit__(inner, *exc):
                inner.close()

        return _F(device.files.get(path, "") if "a" in mode or "r" in mode else "")

    open = file = _file

    def mkdir(self, path, mode=0o777):
        pass

    def chmod(self, path, mode):
        pass

    def stat(self, path):
        if path not in self.device.files:
            raise FileNotFoundError(path)

    def put(self, local, remote, *a, **k):
        with open(local) as fh:
            self.device.files[remote] = fh.read()

    def close(self):
        pass


class LabSSHClient:
    def __init__(self, device, user):
        self.device, self.user = device, user

    def exec_command(self, command, bufsize=-1, timeout=None, get_pty=False, environment=None):
        session = _Session(self.device, command, self.user)
        return _In(session), _Out(session, 1), _Out(session, 2)

    def open_sftp(self):
        return _SFTP(self.device)

    def get_transport(self):
        return self

    def is_active(self):
        return self.device.powered

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def create_client(hostname, port=22, username="root", password=None, key_filename=None,
                  timeout=10.0, known_hosts_path=None, allow_agent=False, look_for_keys=None):
    device = net.lab.ssh_connect(hostname, port, username)
    if getattr(device, "password_only", False) and not password:
        import paramiko
        raise paramiko.AuthenticationException("Authentication failed.")
    return LabSSHClient(device, username)
