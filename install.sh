#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# =============================================================================
#  FleetPilot installer
#  Debian 12/13, Ubuntu 22.04/24.04, Raspberry Pi OS (Bookworm/Trixie).
#  Run as root on the machine (or LXC container) that will host FleetPilot:
#
#    curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/install.sh | bash
#
#  Unattended install / options (environment variables):
#    FP_NONINTERACTIVE=1     never ask questions
#    FP_HTTPS=yes|no         HTTPS on port 443 with nginx and a self-signed
#                            certificate (default yes); "no" serves http://:5000
#    FP_ADMIN_PASSWORD=...   first admin password (default: generated)
#    FP_EXTRAS=yes|no        fan, IPMI and USB-HID tools (default: yes on a
#                            Raspberry Pi, no elsewhere)
#    FP_BRANCH=main          git branch or tag to install
#    FP_REPO=https://...     repository URL
#
#  Running it again updates an existing installation; data in
#  /opt/fleetpilot/data and the settings in /opt/fleetpilot/.env are kept.
# =============================================================================
set -euo pipefail

FP_REPO="${FP_REPO:-https://github.com/ChristianHandy/FleetPilot.git}"
FP_BRANCH="${FP_BRANCH:-main}"
FP_HTTPS="${FP_HTTPS:-yes}"
FP_NONINTERACTIVE="${FP_NONINTERACTIVE:-0}"
INSTALL_DIR="/opt/fleetpilot"
FP_USER="fleetpilot"
APP_PORT=5000
TLS_DIR="/etc/fleetpilot/tls"
CREDENTIALS_FILE="/root/fleetpilot-credentials.txt"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()   { echo -e "${RED}[FAIL]${NC}  $*" >&2; exit 1; }
step()  { echo -e "\n${BOLD}── $* ──${NC}"; }
ask_yes() {  # ask_yes "Question" default(y|n)
    local answer
    if [[ "$FP_NONINTERACTIVE" == "1" || ! -t 0 ]]; then [[ "$2" == "y" ]]; return; fi
    read -rp "$1 [$([[ $2 == y ]] && echo Y/n || echo y/N)] " answer
    answer="${answer:-$2}"; [[ "${answer,,}" == y* ]]
}

# ── Preflight ────────────────────────────────────────────────────────────────
step "Checking the system"
[[ $EUID -eq 0 ]] || die "Run as root (for example: sudo bash install.sh)."
[[ -r /etc/os-release ]] || die "Cannot detect the operating system."
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
    debian:12|debian:13|ubuntu:22.04|ubuntu:24.04|raspbian:12|raspbian:13) ok "System: ${PRETTY_NAME}" ;;
    *) warn "${PRETTY_NAME:-This system} is not tested; FleetPilot supports Debian 12/13, Ubuntu 22.04/24.04 and Raspberry Pi OS."
       ask_yes "Continue anyway?" n || exit 1 ;;
esac
IS_PI=no
grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null && IS_PI=yes
FP_EXTRAS="${FP_EXTRAS:-$IS_PI}"
command -v systemctl >/dev/null || die "systemd is required."
if [[ "$FP_HTTPS" == "yes" ]] && ss -ltn 2>/dev/null | grep -q ':443 ' && ! systemctl is-active --quiet nginx; then
    die "Port 443 is already in use by another program. Free it or run with FP_HTTPS=no."
fi

# ── Packages ─────────────────────────────────────────────────────────────────
step "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
PACKAGES=(python3 python3-venv python3-dev build-essential libffi-dev libssl-dev git curl ca-certificates
          openssh-client sudo iproute2 iputils-ping smartmontools e2fsprogs xfsprogs dosfstools util-linux)
if [[ "$FP_HTTPS" == "yes" ]]; then PACKAGES+=(nginx openssl); fi
apt-get install -y -qq --no-install-recommends "${PACKAGES[@]}" >/dev/null
ok "Base packages installed"
if [[ "$FP_EXTRAS" == "yes" ]]; then
    apt-get install -y -qq --no-install-recommends lm-sensors fancontrol ipmitool libhidapi-hidraw0 \
        libhidapi-libusb0 >/dev/null 2>&1 || warn "Some optional hardware tools are not available on this system."
    # USB fan controllers; FleetPilot runs these with the system Python, not its own venv.
    apt-get install -y -qq --no-install-recommends liquidctl python3-hid >/dev/null 2>&1 \
        || warn "liquidctl/python3-hid are not available here; USB fan controllers will not work."
    ok "Optional hardware tools installed (fans, IPMI, USB-HID)"
fi

# ── Service user and code ────────────────────────────────────────────────────
step "Installing FleetPilot"
if ! id "$FP_USER" &>/dev/null; then
    useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$FP_USER"
    ok "Created service user '$FP_USER'"
fi
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Existing installation found: updating it (data and .env are kept)"
    git -C "$INSTALL_DIR" fetch --quiet origin "$FP_BRANCH"
    git -C "$INSTALL_DIR" -c core.hooksPath=/dev/null checkout --quiet -B "$FP_BRANCH" "origin/$FP_BRANCH" 2>/dev/null \
        || git -C "$INSTALL_DIR" -c core.hooksPath=/dev/null checkout --quiet "$FP_BRANCH"
else
    [[ -e "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]] && \
        die "$INSTALL_DIR exists but is not a FleetPilot checkout. Move it away first."
    git clone --quiet --branch "$FP_BRANCH" "$FP_REPO" "$INSTALL_DIR"
fi
ok "Code at $INSTALL_DIR ($(git -C "$INSTALL_DIR" rev-parse --short HEAD))"

python3 -m venv "$INSTALL_DIR/venv"
# Exact versions with hashes: every install gets the tested packages, and pip refuses anything altered.
"$INSTALL_DIR/venv/bin/pip" install --quiet --disable-pip-version-check --require-hashes -r "$INSTALL_DIR/requirements-lock.txt"
ok "Python packages installed"

# Code is owned by root; only data, logs and the SSH key belong to the service.
chown -R root:root "$INSTALL_DIR"
install -d -o "$FP_USER" -g "$FP_USER" -m 0750 "$INSTALL_DIR/data" "$INSTALL_DIR/logs"
install -d -o "$FP_USER" -g "$FP_USER" -m 0700 "$INSTALL_DIR/.ssh"
if [[ ! -f "$INSTALL_DIR/.ssh/id_ed25519" ]]; then
    sudo -u "$FP_USER" ssh-keygen -q -t ed25519 -N "" -C "fleetpilot@$(hostname)" -f "$INSTALL_DIR/.ssh/id_ed25519"
    ok "SSH key for managed hosts created"
fi
chown -R "$FP_USER:$FP_USER" "$INSTALL_DIR/data" "$INSTALL_DIR/logs" "$INSTALL_DIR/.ssh"

# ── Root helpers with narrow sudo rules ──────────────────────────────────────
install -d -o root -g root -m 0755 /usr/local/lib/fleetpilot
for helper in disk-action update proxy-apply; do
    install -o root -g root -m 0750 "$INSTALL_DIR/scripts/fleetpilot-$helper" "/usr/local/lib/fleetpilot/$helper"
done
cat > /etc/sudoers.d/fleetpilot <<EOF
# FleetPilot may run only these root-owned helpers, each with fixed arguments.
$FP_USER ALL=(root) NOPASSWD: /usr/local/lib/fleetpilot/disk-action *
$FP_USER ALL=(root) NOPASSWD: /usr/local/lib/fleetpilot/update check, /usr/local/lib/fleetpilot/update apply, /usr/local/lib/fleetpilot/update restart
$FP_USER ALL=(root) NOPASSWD: /usr/local/lib/fleetpilot/proxy-apply apply, /usr/local/lib/fleetpilot/proxy-apply status
EOF
chmod 0440 /etc/sudoers.d/fleetpilot
visudo -cf /etc/sudoers.d/fleetpilot >/dev/null || die "Invalid sudo rule"
# Older installers used broad rules (dd, mkfs, ...); remove them.
rm -f /etc/sudoers.d/fleetpilot-disk-action /etc/sudoers.d/fleetpilot-update /etc/sudoers.d/fleetpilot-proxy-apply
ok "Protected helpers installed"

if [[ "$FP_EXTRAS" == "yes" ]]; then
    cat > /etc/udev/rules.d/99-fleetpilot-hid.rules <<'EOF'
# USB fan controllers used by FleetPilot (readable by the plugdev group only)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3904", ATTRS{idProduct}=="f001", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", MODE="0660", GROUP="plugdev"
EOF
    udevadm control --reload-rules 2>/dev/null || true
    usermod -aG plugdev "$FP_USER" 2>/dev/null || true
fi

# ── Settings (.env); existing values are never overwritten ───────────────────
step "Writing settings"
ENV_FILE="$INSTALL_DIR/.env"
touch "$ENV_FILE"; chown root:"$FP_USER" "$ENV_FILE"; chmod 0640 "$ENV_FILE"
set_env() {   # set_env KEY VALUE [force]
    if grep -q "^$1=" "$ENV_FILE"; then
        # An if, not '&&': under set -e a false test would end the script on updates.
        if [[ "${3:-}" == "force" ]]; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; fi
    else
        echo "$1=$2" >> "$ENV_FILE"
    fi
}
set_env SECRET_KEY "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
set_env FLEETPILOT_DATA_DIR "$INSTALL_DIR/data"
set_env DASHBOARD_USERNAME admin
NEW_PASSWORD=""
# Only a first install creates the admin account; later runs leave sign-in data alone.
if [[ ! -f "$INSTALL_DIR/data/users.db" ]] && ! grep -q "^DASHBOARD_PASSWORD=" "$ENV_FILE"; then
    NEW_PASSWORD="${FP_ADMIN_PASSWORD:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(15))')}"
    set_env DASHBOARD_PASSWORD "$NEW_PASSWORD"
elif grep -q "^DASHBOARD_PASSWORD=" "$ENV_FILE"; then
    # An earlier run stopped before the first sign-in data was saved: show that password again.
    NEW_PASSWORD="$(grep -m1 "^DASHBOARD_PASSWORD=" "$ENV_FILE" | cut -d= -f2-)"
fi
if [[ "$FP_HTTPS" == "yes" ]]; then
    # Behind nginx: trust its X-Forwarded-* headers, cookies only over HTTPS.
    set_env GUNICORN_BIND "127.0.0.1:$APP_PORT" force
    set_env FLEETPILOT_PRODUCTION true force
    set_env FLEETPILOT_TRUST_PROXY true force
    set_env FLEETPILOT_COOKIE_SECURE true force
    # Self-signed certificate: no HSTS, or browsers could refuse the page for a year.
    set_env FLEETPILOT_HSTS false
else
    # Served directly: never trust forwarded headers, a client could fake its address.
    set_env GUNICORN_BIND "0.0.0.0:$APP_PORT" force
    set_env FLEETPILOT_TRUST_PROXY false force
    set_env FLEETPILOT_COOKIE_SECURE false force
fi
ok "Settings in $ENV_FILE"

# ── systemd service ──────────────────────────────────────────────────────────
step "Installing the service"
sed -e "s|/opt/fleetpilot|$INSTALL_DIR|g" -e "s|^User=.*|User=$FP_USER|" -e "s|^Group=.*|Group=$FP_USER|" \
    "$INSTALL_DIR/deploy/fleetpilot.service" > /etc/systemd/system/fleetpilot.service
[[ "$FP_EXTRAS" == "yes" ]] || sed -i 's/^SupplementaryGroups=.*/SupplementaryGroups=/' /etc/systemd/system/fleetpilot.service
systemctl daemon-reload
systemctl enable --quiet fleetpilot
systemctl restart fleetpilot
ok "Service fleetpilot enabled"

# ── HTTPS with nginx ─────────────────────────────────────────────────────────
HOST_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="src") print $(i+1)}' | head -1)"
HOST_IP="${HOST_IP:-$(hostname -I | awk '{print $1}')}"
if [[ "$FP_HTTPS" == "yes" ]]; then
    step "Setting up HTTPS"
    install -d -m 0750 "$TLS_DIR"
    if [[ ! -f "$TLS_DIR/fullchain.pem" ]]; then
        openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 825 -sha256 \
            -subj "/CN=$(hostname)" \
            -addext "subjectAltName=DNS:$(hostname),DNS:$(hostname).local,IP:${HOST_IP:-127.0.0.1},IP:127.0.0.1" \
            -keyout "$TLS_DIR/privkey.pem" -out "$TLS_DIR/fullchain.pem" 2>/dev/null
        chmod 0600 "$TLS_DIR/privkey.pem"
        ok "Self-signed certificate created (replace it with your own in $TLS_DIR at any time)"
    fi
    # Debian 12's nginx predates "http2 on;", so use the listen-parameter form.
    sed -e "s|/etc/ssl/fleetpilot|$TLS_DIR|g" -e "s|server_name fleetpilot.example.internal;|server_name _;|" \
        -e 's|^\(\s*\)listen 443 ssl;|\1listen 443 ssl http2;|' -e 's|^\(\s*\)listen \[::\]:443 ssl;|\1listen [::]:443 ssl http2;|' \
        -e '/^\s*http2 on;/d' -e '/ssl_stapling/d' -e '/Strict-Transport-Security/d' \
        "$INSTALL_DIR/deploy/nginx-fleetpilot-tls.conf" \
        | awk '/^server \{/{block++} block==1{next} {print}' > /etc/nginx/sites-available/fleetpilot-tls
    # (The port-80 redirect block is left out: port 80 stays free for FleetPilot's HAProxy ingress.)
    cp "$INSTALL_DIR/deploy/nginx-fleetpilot.conf" /etc/nginx/sites-available/fleetpilot   # 127.0.0.1:8080 for HAProxy
    ln -sf /etc/nginx/sites-available/fleetpilot-tls /etc/nginx/sites-enabled/fleetpilot-tls
    ln -sf /etc/nginx/sites-available/fleetpilot /etc/nginx/sites-enabled/fleetpilot
    rm -f /etc/nginx/sites-enabled/default
    nginx -t 2>/dev/null || { nginx -t; die "nginx configuration test failed"; }
    systemctl enable --quiet nginx
    systemctl reload nginx 2>/dev/null || systemctl restart nginx
    ok "nginx serves FleetPilot on https://${HOST_IP}"
fi

# ── Check that it answers ────────────────────────────────────────────────────
step "Starting"
healthy() {
    for _ in $(seq 1 "$1"); do
        curl -fsS --max-time 2 "http://127.0.0.1:$APP_PORT/healthz" >/dev/null 2>&1 && return 0
        sleep 1
    done
    return 1
}
if ! healthy 30; then
    if [[ "$(systemd-detect-virt -c 2>/dev/null || true)" == "lxc" ]]; then
        # Some sandbox options need kernel features an unprivileged LXC container may lack
        # (the service then fails with 226/NAMESPACE). The container is the sandbox here.
        warn "Service did not start inside LXC; relaxing systemd sandbox options for containers"
        install -d /etc/systemd/system/fleetpilot.service.d
        printf '%s\n' '[Service]' PrivateTmp=false PrivateMounts=false ProtectSystem=false ProtectHome=false \
            ProtectKernelModules=false ProtectKernelLogs=false ProtectControlGroups=false ProtectClock=false \
            ProtectHostname=false RestrictNamespaces=false > /etc/systemd/system/fleetpilot.service.d/lxc.conf
        systemctl daemon-reload
        systemctl restart fleetpilot
        healthy 30 || die "FleetPilot did not start. See: journalctl -u fleetpilot -n 50"
    else
        die "FleetPilot did not start. See: journalctl -u fleetpilot -n 50"
    fi
fi
ok "FleetPilot is running"
# The admin account now exists in the database; the plain-text start password is no longer needed.
sed -i '/^DASHBOARD_PASSWORD=/d' "$ENV_FILE"

URL="http://${HOST_IP}:${APP_PORT}"
if [[ "$FP_HTTPS" == "yes" ]]; then URL="https://${HOST_IP}"; fi
{
    echo "FleetPilot $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "URL:       $URL"
    echo "User:      admin"
    if [[ -n "$NEW_PASSWORD" ]]; then echo "Password:  $NEW_PASSWORD"; else echo "Password:  unchanged"; fi
    echo "SSH key:   $(cat "$INSTALL_DIR/.ssh/id_ed25519.pub")"
} > "$CREDENTIALS_FILE"
chmod 0600 "$CREDENTIALS_FILE"

echo ""
echo -e "${GREEN}${BOLD}  FleetPilot is installed.${NC}"
echo ""
echo -e "  Open:      ${BOLD}$URL${NC}"
if [[ "$FP_HTTPS" == "yes" ]]; then echo "             (the browser warns about the self-signed certificate once; accept it or install your own)"; fi
echo "  User:      admin"
if [[ -n "$NEW_PASSWORD" ]]; then
    echo -e "  Password:  ${BOLD}$NEW_PASSWORD${NC}   (change it under My Profile, and set up 2FA)"
else
    echo "  Password:  unchanged"
fi
echo "  Saved to:  $CREDENTIALS_FILE (root only)"
echo ""
echo "  Give FleetPilot access to a server:   Manage Hosts → Install key, or add this line to"
echo "  ~/.ssh/authorized_keys on that server:"
echo "    $(cat "$INSTALL_DIR/.ssh/id_ed25519.pub")"
echo ""
echo "  Logs:      journalctl -u fleetpilot -f"
echo "  Update:    run this installer again, or System → FleetPilot update"
echo "  Guide:     $INSTALL_DIR/docs/installation.md"
echo ""

if [[ "$IS_PI" == "yes" ]] && ask_yes "Also run this Raspberry Pi as a Proxmox QDevice (corosync-qnetd)?" n; then
    apt-get install -y -qq corosync-qnetd >/dev/null && systemctl enable --now corosync-qnetd \
        && ok "QDevice ready. On a Proxmox node run: pvecm qdevice setup $HOST_IP" \
        || warn "corosync-qnetd could not be installed"
fi
