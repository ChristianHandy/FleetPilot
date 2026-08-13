#!/bin/bash
# ============================================================
# FleetPilot — Raspberry Pi Install Script
# Supports: Raspberry Pi 3, 4, 5 (32-bit and 64-bit)
#           Raspberry Pi OS (Bullseye / Bookworm)
# ============================================================
set -e

REPO="https://github.com/ChristianHandy/FleetPilot.git"
INSTALL_DIR="/opt/fleetpilot"
SERVICE_NAME="fleetpilot"
PORT=5000
FP_USER="fleetpilot"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERR]${NC}  $1"; exit 1; }

echo ""
echo "  ███████╗██╗     ███████╗███████╗████████╗"
echo "  ██╔════╝██║     ██╔════╝██╔════╝╚══██╔══╝"
echo "  █████╗  ██║     █████╗  █████╗     ██║   "
echo "  ██╔══╝  ██║     ██╔══╝  ██╔══╝     ██║   "
echo "  ██║     ███████╗███████╗███████╗   ██║   "
echo "  ╚═╝     ╚══════╝╚══════╝╚══════╝   ╚═╝   "
echo "  ██████╗ ██╗██╗      ██████╗ ████████╗"
echo "  ██╔══██╗██║██║     ██╔═══██╗╚══██╔══╝"
echo "  ██████╔╝██║██║     ██║   ██║   ██║   "
echo "  ██╔═══╝ ██║██║     ██║   ██║   ██║   "
echo "  ██║     ██║███████╗╚██████╔╝   ██║   "
echo "  ╚═╝     ╚═╝╚══════╝ ╚═════╝    ╚═╝   "
echo ""
echo "  Raspberry Pi Installer"
echo "  ========================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    error "Please run as root: sudo bash install_raspberry_pi.sh"
fi

# Detect architecture
ARCH=$(uname -m)
info "Architecture: $ARCH"
case "$ARCH" in
    armv7l|armv6l) info "Raspberry Pi 32-bit detected" ;;
    aarch64)       info "Raspberry Pi 64-bit detected" ;;
    x86_64)        warn "Running on x86_64 — this script is optimized for Raspberry Pi but will work" ;;
    *)             warn "Unknown architecture: $ARCH" ;;
esac

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    info "OS: $PRETTY_NAME"
else
    warn "Cannot detect OS version"
fi

# Step 1: Update system
info "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
success "System updated"

# Step 2: Install system dependencies
info "Installing system dependencies..."
apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    git \
    curl \
    wget \
    openssh-client \
    sshpass \
    smartmontools \
    e2fsprogs \
    xfsprogs \
    dosfstools \
    lm-sensors \
    fancontrol \
    ipmitool \
    net-tools \
    nmap \
    nginx \
    libhidapi-hidraw0 \
    libhidapi-libusb0 \
    python3-hid \
    2>/dev/null || true
success "System dependencies installed"

# Step 3: Install optional tools (non-fatal)
info "Installing optional tools..."
apt-get install -y -qq liquidctl 2>/dev/null || \
    pip3 install liquidctl 2>/dev/null || \
    warn "liquidctl not available — fan controller USB support limited"

# Step 4: Create FleetPilot user
if ! id "$FP_USER" &>/dev/null; then
    useradd -r -s /bin/bash -d "$INSTALL_DIR" "$FP_USER"
    success "Created user: $FP_USER"
fi

# Step 5: Clone or update repository
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing FleetPilot installation..."
    cd "$INSTALL_DIR"
    git pull --ff-only 2>&1 | tail -2
    success "FleetPilot updated"
else
    info "Cloning FleetPilot repository..."
    git clone "$REPO" "$INSTALL_DIR"
    success "FleetPilot cloned to $INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Step 6: Create virtual environment
info "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Step 7: Install Python dependencies
info "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
# Install hid for USB fan controllers (Raspberry Pi specific)
pip install hid 2>/dev/null || true
success "Python dependencies installed"

deactivate

# Step 8: Separate immutable application code from mutable service data.
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/logs"
chown -R root:root "$INSTALL_DIR"
chown -R "$FP_USER:$FP_USER" "$INSTALL_DIR/data" "$INSTALL_DIR/logs"
chmod 0750 "$INSTALL_DIR/data" "$INSTALL_DIR/logs"

# Step 9: Install the restricted local Disk Tools helper and its sudo rule.
# The helper is root-owned, validates mode/filesystem/device, and blocks mounted system disks.
info "Installing protected Disk Tools helper..."
install -d -o root -g root -m 0755 /usr/local/lib/fleetpilot
install -o root -g root -m 0750 "$INSTALL_DIR/scripts/fleetpilot-disk-action" /usr/local/lib/fleetpilot/disk-action
cat > /etc/sudoers.d/fleetpilot-disk-action << EOF
# FleetPilot may invoke only the root-owned, argument-validating disk helper.
$FP_USER ALL=(root) NOPASSWD: /usr/local/lib/fleetpilot/disk-action *
EOF
chmod 0440 /etc/sudoers.d/fleetpilot-disk-action
visudo -cf /etc/sudoers.d/fleetpilot-disk-action >/dev/null || error "Invalid Disk Tools sudo rule"
success "Protected Disk Tools helper installed"

# Step 10: Create a protected runtime configuration. Existing values are preserved.
touch "$INSTALL_DIR/.env"
chmod 0600 "$INSTALL_DIR/.env"
chown root:"$FP_USER" "$INSTALL_DIR/.env"
ensure_env() {
    key="$1"; value="$2"
    grep -q "^${key}=" "$INSTALL_DIR/.env" || echo "${key}=${value}" >> "$INSTALL_DIR/.env"
}
ensure_env SECRET_KEY "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
ensure_env DASHBOARD_PASSWORD "CHANGE_THIS_AFTER_INSTALL"
ensure_env FLEETPILOT_PRODUCTION "false"
ensure_env FLEETPILOT_TRUST_PROXY "true"
ensure_env FLEETPILOT_COOKIE_SECURE "false"
ensure_env FLEETPILOT_SESSION_MINUTES "480"
ensure_env WTF_CSRF_ENABLED "false"
success "Protected runtime configuration prepared"

# Step 11: Create systemd service
info "Creating systemd service..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=FleetPilot Server Management Dashboard
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$FP_USER
WorkingDirectory=$INSTALL_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/gunicorn --config $INSTALL_DIR/gunicorn.conf.py app:app
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=fleetpilot

# Raspberry Pi specific: allow USB HID access
SupplementaryGroups=plugdev input
UMask=0027
ProtectSystem=full
ReadWritePaths=$INSTALL_DIR/data $INSTALL_DIR/logs
PrivateTmp=true
ProtectHome=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
EOF

# Step 12: Add udev rules for USB HID (Arctic Fan Controller etc.)
info "Adding USB HID udev rules..."
cat > /etc/udev/rules.d/99-fleetpilot-hid.rules << 'EOF'
# Arctic Fan Controller (ACFAN00351A)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3904", ATTRS{idProduct}=="f001", MODE="0666", GROUP="plugdev"
# Corsair Commander Pro
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", MODE="0666", GROUP="plugdev"
# Generic HID devices for FleetPilot
SUBSYSTEM=="usb", ATTRS{idVendor}=="3904", MODE="0666", GROUP="plugdev"
EOF
udevadm control --reload-rules 2>/dev/null || true
usermod -aG plugdev "$FP_USER" 2>/dev/null || true
success "USB HID rules added"

# Step 13: Enable and start service
info "Enabling and starting FleetPilot service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 3

# Step 14: Check if running
if systemctl is-active --quiet "$SERVICE_NAME"; then
    success "FleetPilot is running!"
else
    warn "FleetPilot may not have started. Check: journalctl -u fleetpilot -n 20"
fi

# Step 15: Get IP address
PI_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "  ============================================"
echo "  ✅  FleetPilot installed successfully!"
echo "  ============================================"
echo ""
echo "  🌐 Access FleetPilot at:"
echo "     http://$PI_IP:$PORT"
echo ""
echo "  🔑 Default login:"
echo "     Username: admin"
echo "     Password: FleetPilot2025"
echo ""
echo "  📋 Useful commands:"
echo "     sudo systemctl status fleetpilot"
echo "     sudo journalctl -u fleetpilot -f"
echo "     sudo systemctl restart fleetpilot"
echo ""
echo "  📁 Installation directory: $INSTALL_DIR"
echo "  📝 Config file: $INSTALL_DIR/.env"
echo ""

# Optional: Setup as QDevice for Proxmox cluster
echo "  ─────────────────────────────────────────────"
echo "  💡 Optional: Use this Pi as Proxmox QDevice"
echo "     (allows Proxmox cluster to run with 1 node)"
echo ""
read -p "  Install Proxmox QDevice (corosync-qnetd)? [y/N]: " INSTALL_QDEVICE
if [[ "$INSTALL_QDEVICE" =~ ^[Yy]$ ]]; then
    info "Installing corosync-qnetd..."
    apt-get install -y -qq corosync-qnetd corosync-pacemaker 2>/dev/null || \
    apt-get install -y -qq corosync-qnetd 2>/dev/null || \
    warn "corosync-qnetd not available in this repository"
    
    if which corosync-qnetd &>/dev/null; then
        # Initialize certificates
        corosync-qnetd-certutil -i 2>/dev/null || true
        # Start service
        systemctl enable corosync-qnetd 2>/dev/null || true
        systemctl start corosync-qnetd 2>/dev/null || true
        
        if systemctl is-active --quiet corosync-qnetd 2>/dev/null; then
            success "corosync-qnetd is running on port 5403"
            echo ""
            echo "  On each Proxmox node, run:"
            echo "  pvecm qdevice setup $PI_IP"
            echo ""
        else
            warn "corosync-qnetd could not be started"
        fi
    fi
fi

echo "  Installation complete! 🎉"
echo ""
