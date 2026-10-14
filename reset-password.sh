#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# FleetPilot: reset a user's password on the server.
#
#   sudo bash /opt/fleetpilot/reset-password.sh            # user "admin", asks for a password
#   sudo bash /opt/fleetpilot/reset-password.sh alice      # another user
#   sudo bash /opt/fleetpilot/reset-password.sh --generate # create a random password and print it
#   sudo bash /opt/fleetpilot/reset-password.sh --list     # list users and roles
#
# The account is re-activated, two-factor sign-in stays as it is, and every open
# session of that user is signed out. The password never appears in a command line.
set -euo pipefail

die() { echo "Error: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"

INSTALL_DIR="${FP_INSTALL_DIR:-/opt/fleetpilot}"
[[ -d "$INSTALL_DIR" ]] || INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$INSTALL_DIR/venv/bin/python"
[[ -x "$PYTHON" ]] || die "No FleetPilot found in $INSTALL_DIR (set FP_INSTALL_DIR)."
DATA_DIR="$(grep -m1 '^FLEETPILOT_DATA_DIR=' "$INSTALL_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
DATA_DIR="${DATA_DIR:-$INSTALL_DIR/data}"
[[ -f "$DATA_DIR/users.db" ]] || die "No user database in $DATA_DIR."
RUN_AS="$(stat -c %U "$DATA_DIR/users.db")"   # keep the files owned by the service user

GENERATE=no; LIST=no; USERNAME="admin"
for arg in "$@"; do
    case "$arg" in
        --generate) GENERATE=yes ;;
        --list)     LIST=yes ;;
        -h|--help)  sed -n '2,10p' "$0"; exit 0 ;;
        -*)         die "Unknown option $arg" ;;
        *)          USERNAME="$arg" ;;
    esac
done

run_py() {   # run Python as the service user; the password comes in on stdin
    runuser -u "$RUN_AS" -- env FLEETPILOT_DATA_DIR="$DATA_DIR" PYTHONDONTWRITEBYTECODE=1 \
        "$PYTHON" -c "import sys; sys.path.insert(0, '$INSTALL_DIR'); $1" "${@:2}"
}

if [[ "$LIST" == yes ]]; then
    run_py "
import user_management as um
roles = um.roles_by_user()
for u in um.list_users():
    state = 'active' if u['active'] else 'disabled'
    print(f\"{u['username']:<24} {', '.join(sorted(roles.get(u['id'], []))) or '-':<24} {state}\")"
    exit 0
fi

if [[ "$GENERATE" == yes ]]; then
    PASSWORD="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(15))')"
else
    read -rsp "New password for '$USERNAME' (at least 12 characters): " PASSWORD; echo
    read -rsp "Repeat it: " AGAIN; echo
    [[ "$PASSWORD" == "$AGAIN" ]] || die "The passwords do not match."
fi
[[ ${#PASSWORD} -ge 12 ]] || die "The password must be at least 12 characters."

printf '%s' "$PASSWORD" | run_py "
import user_management as um, account_security as acs
name = sys.argv[1]
user = um.get_user(name)
if not user:
    sys.exit(f'No user called {name!r}. Use --list to see all users.')
um.update_user(user['id'], password=sys.stdin.read(), active=1)
acs.init_db()
print(f'Password changed; {acs.revoke_user_sessions(user[\"id\"])} open session(s) signed out.')" "$USERNAME"

# A first-install password left in .env would be confusing now; the database is what counts.
sed -i '/^DASHBOARD_PASSWORD=/d' "$INSTALL_DIR/.env" 2>/dev/null || true
if [[ "$GENERATE" == yes ]]; then
    echo "New password for $USERNAME: $PASSWORD"
fi
echo "Done. Sign in as $USERNAME."
