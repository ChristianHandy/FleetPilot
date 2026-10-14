# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""SQLite connections that close when their ``with`` block ends.

``sqlite3.Connection`` used as a context manager only commits or rolls back; it
stays open until garbage collection, which leaks file handles under load and
raises ResourceWarning. Every helper that is used as ``with get_db() as conn:``
creates its connection with ``factory=ClosingConnection``.
"""
import sqlite3


class ClosingConnection(sqlite3.Connection):
    """Commits (or rolls back) and then closes at the end of a ``with`` block."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()
