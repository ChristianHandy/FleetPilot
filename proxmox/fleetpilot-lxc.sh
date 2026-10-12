#!/usr/bin/env bash
# =============================================================================
#  FleetPilot — Proxmox VE helper script
#
#  Creates a Debian LXC container on this Proxmox host and installs FleetPilot
#  in it. Run on the Proxmox host as root (Shell of the node in the web UI):
#
#    bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)"
#
#  Update an existing FleetPilot container:
#
#    bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)" -- update 105
#
#  Unattended (all optional): CT_ID, CT_HOSTNAME, CT_CORES, CT_RAM (MB),
#  CT_DISK (GB), CT_STORAGE, CT_TEMPLATE_STORAGE, CT_BRIDGE, CT_VLAN,
#  CT_IP (dhcp or 192.168.1.50/24), CT_GW, CT_SSH_KEY (file), FP_HTTPS (yes|no),
#  FP_BRANCH (main), FP_DEFAULTS=1 (skip all questions).
# =============================================================================
set -euo pipefail

FP_RAW="${FP_RAW:-https://raw.githubusercontent.com/ChristianHandy/FleetPilot}"
FP_BRANCH="${FP_BRANCH:-main}"
FP_HTTPS="${FP_HTTPS:-yes}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
msg()  { echo -e "${CYAN} ➜${NC} $*"; }
ok()   { echo -e "${GREEN} ✔${NC} $*"; }
warn() { echo -e "${YELLOW} !${NC} $*"; }
die()  { echo -e "${RED} ✘ $*${NC}" >&2; exit 1; }

header() {
    clear 2>/dev/null || true
    echo -e "${BOLD}"
    echo "   ___ _          _   ___ _ _     _   "
    echo "  | __| |___ ___ | |_| _ (_) |___| |_ "
    echo "  | _|| / -_) -_)|  _|  _/ | / _ \\  _|"
    echo "  |_| |_\\___\\___| \\__|_| |_|_\\___/\\__|"
    echo -e "${NC}  Proxmox VE helper script · LXC container\n"
}

# ── Checks ───────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Run this as root on the Proxmox host."
command -v pct >/dev/null && command -v pveam >/dev/null || die "This is not a Proxmox VE host (pct/pveam not found)."
PVE_VERSION="$(pveversion 2>/dev/null | grep -oE 'pve-manager/[0-9]+' | cut -d/ -f2 || echo 0)"
[[ "$PVE_VERSION" -ge 8 ]] || warn "Proxmox VE 8 or newer is recommended (found: $(pveversion 2>/dev/null || echo unknown))."
[[ "$(dpkg --print-architecture 2>/dev/null || echo amd64)" == "amd64" ]] || die "Only amd64 Proxmox hosts are supported."

# ── Update mode ──────────────────────────────────────────────────────────────
if [[ "${1:-}" == "update" ]]; then
    CT_ID="${2:-}"
    [[ "$CT_ID" =~ ^[0-9]+$ ]] || die "Usage: fleetpilot-lxc.sh update <container ID>"
    pct status "$CT_ID" >/dev/null 2>&1 || die "Container $CT_ID does not exist."
    pct exec "$CT_ID" -- test -d /opt/fleetpilot/.git || die "Container $CT_ID has no FleetPilot installation."
    msg "Updating FleetPilot in container $CT_ID…"
    pct exec "$CT_ID" -- env FP_NONINTERACTIVE=1 FP_BRANCH="$FP_BRANCH" bash -c \
        "curl -fsSL '$FP_RAW/$FP_BRANCH/install.sh' | bash" || die "Update failed. Look inside: pct enter $CT_ID"
    ok "FleetPilot in container $CT_ID is up to date."
    exit 0
fi

# ── Settings ─────────────────────────────────────────────────────────────────
header
CT_ID="${CT_ID:-$(pvesh get /cluster/nextid 2>/dev/null || echo 100)}"
CT_HOSTNAME="${CT_HOSTNAME:-fleetpilot}"
CT_CORES="${CT_CORES:-2}"
CT_RAM="${CT_RAM:-2048}"
CT_DISK="${CT_DISK:-8}"
CT_BRIDGE="${CT_BRIDGE:-vmbr0}"
CT_VLAN="${CT_VLAN:-}"
CT_IP="${CT_IP:-dhcp}"
CT_GW="${CT_GW:-}"
CT_SSH_KEY="${CT_SSH_KEY:-}"

pick_storage() {   # pick_storage CONTENT → storage with the most free space for that content
    pvesm status -content "$1" 2>/dev/null | awk 'NR>1 && $3=="active" {print $6, $1}' | sort -rn | head -1 | awk '{print $2}'
}
CT_STORAGE="${CT_STORAGE:-$(pick_storage rootdir)}"
CT_TEMPLATE_STORAGE="${CT_TEMPLATE_STORAGE:-$(pick_storage vztmpl)}"
[[ -n "$CT_STORAGE" ]] || die "No storage for containers found (content type 'rootdir')."
[[ -n "$CT_TEMPLATE_STORAGE" ]] || die "No storage for templates found (content type 'vztmpl')."

ask() {   # ask VAR "Question" — whiptail when available, plain prompt otherwise
    local var="$1" question="$2" current="${!1}" answer
    if command -v whiptail >/dev/null; then
        answer=$(whiptail --title "FleetPilot LXC" --inputbox "$question" 9 70 "$current" 3>&1 1>&2 2>&3) || exit 1
    else
        read -rp "$question [$current]: " answer; answer="${answer:-$current}"
    fi
    printf -v "$var" '%s' "$answer"
}

ADVANCED=no
if [[ "${FP_DEFAULTS:-0}" != "1" && -t 0 ]]; then
    if command -v whiptail >/dev/null; then
        whiptail --title "FleetPilot LXC" --yes-button "Default settings" --no-button "Advanced" --yesno \
"Create a FleetPilot container with these settings?

  ID ${CT_ID} · ${CT_CORES} cores · ${CT_RAM} MB RAM · ${CT_DISK} GB on ${CT_STORAGE}
  Network ${CT_BRIDGE}, ${CT_IP} · HTTPS ${FP_HTTPS}" 14 70 || ADVANCED=yes
    else
        read -rp "Use default settings (ID $CT_ID, $CT_CORES cores, $CT_RAM MB, $CT_DISK GB, $CT_IP)? [Y/n] " a
        [[ "${a,,}" == n* ]] && ADVANCED=yes
    fi
fi
if [[ "$ADVANCED" == "yes" ]]; then
    ask CT_ID "Container ID"
    ask CT_HOSTNAME "Host name"
    ask CT_CORES "CPU cores"
    ask CT_RAM "Memory in MB (at least 1024)"
    ask CT_DISK "Disk size in GB (at least 4)"
    ask CT_STORAGE "Storage for the container disk"
    ask CT_BRIDGE "Network bridge"
    ask CT_VLAN "VLAN tag (empty for none)"
    ask CT_IP "IPv4: dhcp, or address with prefix such as 192.168.1.50/24"
    [[ "$CT_IP" != "dhcp" ]] && ask CT_GW "Gateway (for example 192.168.1.1)"
    ask FP_HTTPS "HTTPS with a self-signed certificate (yes/no)"
fi

# Validate everything before touching the host.
[[ "$CT_ID" =~ ^[0-9]+$ && "$CT_ID" -ge 100 ]] || die "Container ID must be a number from 100 up."
pct status "$CT_ID" >/dev/null 2>&1 && die "ID $CT_ID is already in use."
qm status "$CT_ID" >/dev/null 2>&1 && die "ID $CT_ID is already used by a VM."
[[ "$CT_HOSTNAME" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$ ]] || die "Invalid host name."
[[ "$CT_CORES" =~ ^[0-9]+$ && "$CT_CORES" -ge 1 ]] || die "Invalid number of cores."
[[ "$CT_RAM" =~ ^[0-9]+$ && "$CT_RAM" -ge 1024 ]] || die "Use at least 1024 MB of memory."
[[ "$CT_DISK" =~ ^[0-9]+$ && "$CT_DISK" -ge 4 ]] || die "Use at least 4 GB of disk."
[[ "$CT_BRIDGE" =~ ^[a-zA-Z0-9_.-]+$ ]] && ip link show "$CT_BRIDGE" >/dev/null 2>&1 || die "Bridge $CT_BRIDGE not found."
[[ -z "$CT_VLAN" || ( "$CT_VLAN" =~ ^[0-9]+$ && "$CT_VLAN" -ge 1 && "$CT_VLAN" -le 4094 ) ]] || die "Invalid VLAN tag."
if [[ "$CT_IP" != "dhcp" ]]; then
    [[ "$CT_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]] || die "IP must look like 192.168.1.50/24."
    [[ "$CT_GW" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "A static IP needs a gateway such as 192.168.1.1."
fi
[[ "$FP_HTTPS" == "yes" || "$FP_HTTPS" == "no" ]] || die "HTTPS must be yes or no."
[[ -z "$CT_SSH_KEY" || -r "$CT_SSH_KEY" ]] || die "SSH key file $CT_SSH_KEY not readable."
pvesm status -content rootdir 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$CT_STORAGE" || die "Storage $CT_STORAGE cannot hold containers."

# ── Template ─────────────────────────────────────────────────────────────────
msg "Looking for the newest Debian template…"
pveam update >/dev/null 2>&1 || warn "Could not refresh the template list; using the cached one."
TEMPLATE="$(pveam available --section system 2>/dev/null | awk '{print $2}' | grep -E '^debian-13-standard_.*_amd64' | sort -V | tail -1)"
[[ -n "$TEMPLATE" ]] || TEMPLATE="$(pveam available --section system 2>/dev/null | awk '{print $2}' | grep -E '^debian-12-standard_.*_amd64' | sort -V | tail -1)"
[[ -n "$TEMPLATE" ]] || die "No Debian 12/13 template available. Check the host's internet access."
if ! pveam list "$CT_TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
    msg "Downloading $TEMPLATE to $CT_TEMPLATE_STORAGE…"
    pveam download "$CT_TEMPLATE_STORAGE" "$TEMPLATE" >/dev/null || die "Template download failed."
fi
ok "Template: $TEMPLATE"

# ── Container ────────────────────────────────────────────────────────────────
NET="name=eth0,bridge=$CT_BRIDGE"
if [[ "$CT_IP" == "dhcp" ]]; then NET+=",ip=dhcp"; else NET+=",ip=$CT_IP,gw=$CT_GW"; fi
[[ -n "$CT_VLAN" ]] && NET+=",tag=$CT_VLAN"
CREATE_ARGS=(
    "$CT_ID" "$CT_TEMPLATE_STORAGE:vztmpl/$TEMPLATE"
    --hostname "$CT_HOSTNAME" --cores "$CT_CORES" --memory "$CT_RAM" --swap 512
    --rootfs "$CT_STORAGE:$CT_DISK" --net0 "$NET"
    --unprivileged 1 --features nesting=1 --onboot 1 --ostype debian
    --tags fleetpilot --description "FleetPilot · https://github.com/ChristianHandy/FleetPilot"
)
[[ -n "$CT_SSH_KEY" ]] && CREATE_ARGS+=(--ssh-public-keys "$CT_SSH_KEY")
msg "Creating container $CT_ID ($CT_HOSTNAME)…"
pct create "${CREATE_ARGS[@]}" >/dev/null || die "pct create failed."
ok "Container $CT_ID created"
pct start "$CT_ID"

msg "Waiting for the network…"
for _ in $(seq 1 60); do
    pct exec "$CT_ID" -- getent hosts deb.debian.org >/dev/null 2>&1 && break
    sleep 1
done
pct exec "$CT_ID" -- getent hosts deb.debian.org >/dev/null 2>&1 \
    || die "Container $CT_ID has no internet access (DNS for deb.debian.org fails). Check bridge, VLAN and DHCP."
ok "Network ready"

# ── FleetPilot ───────────────────────────────────────────────────────────────
msg "Installing FleetPilot inside the container (takes a few minutes)…"
pct exec "$CT_ID" -- bash -c "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates >/dev/null"
pct exec "$CT_ID" -- env FP_NONINTERACTIVE=1 FP_HTTPS="$FP_HTTPS" FP_BRANCH="$FP_BRANCH" bash -c \
    "curl -fsSL '$FP_RAW/$FP_BRANCH/install.sh' | bash" || die "Installation failed. Look inside: pct enter $CT_ID"

CREDS="$(pct exec "$CT_ID" -- cat /root/fleetpilot-credentials.txt)"
URL="$(sed -n 's/^URL: *//p' <<<"$CREDS")"
PASS="$(sed -n 's/^Password: *//p' <<<"$CREDS")"
KEY="$(sed -n 's/^SSH key: *//p' <<<"$CREDS")"
pct set "$CT_ID" --description "FleetPilot · ${URL}
Credentials inside the container: /root/fleetpilot-credentials.txt
Update: run the helper script with 'update ${CT_ID}' on the host." >/dev/null

header
echo -e "${GREEN}${BOLD}  FleetPilot is ready in container ${CT_ID}.${NC}\n"
echo -e "  Open:       ${BOLD}${URL}${NC}"
[[ "$FP_HTTPS" == "yes" ]] && echo "              (accept the self-signed certificate once, or install your own later)"
echo -e "  User:       admin"
echo -e "  Password:   ${BOLD}${PASS}${NC}   ← change it after signing in, then set up 2FA"
echo ""
echo "  FleetPilot's SSH key for the servers you want to manage:"
echo "    ${KEY}"
echo "  Add it on the Proxmox host too, to manage this node:"
echo "    echo '${KEY}' >> /root/.ssh/authorized_keys"
echo ""
echo "  Good to know:"
echo "  · The container cannot see this host's disks directly: add the host under"
echo "    Manage Hosts (SSH) to see SMART data and run updates on it."
echo "  · Update later:  bash -c \"\$(curl -fsSL $FP_RAW/main/proxmox/fleetpilot-lxc.sh)\" -- update $CT_ID"
echo "  · Shell inside:  pct enter $CT_ID"
echo ""
