# FleetPilot User Guide

**Version 2.0 — July 2026**

---

## Table of Contents

| # | Chapter |
|---|---------|
| 01 | Getting Started |
| 02 | Dashboard & Customization |
| 03 | Host Management & Adding Servers |
| 04 | Update Manager |
| 05 | VM Controller |
| 06 | Storage Controller |
| 07 | Disk Management & SMART |
| 08 | Backup Controller |
| 09 | Fan Controller & Cooling |
| 10 | CheckMK Integration |
| 11 | User Management & Plugins |

---

## 01 — Getting Started

FleetPilot is a centralized web platform designed for managing servers, virtual machines, storage systems, backups, and cooling infrastructure across heterogeneous IT environments. It runs as a Python Flask application on Linux and is accessible through any modern web browser (Chrome, Firefox, Edge). The application is optimized for screen resolutions of 1280×720 and above.

**Logging In.** Open the FleetPilot URL in your browser. Enter your username and password and click "Sign In". After successful authentication you will be redirected to the dashboard. The system includes built-in brute-force protection: after 10 failed login attempts within 60 seconds, the originating IP address is temporarily blocked.

**User Interface Layout.** The interface is divided into three persistent areas. The left-hand navigation bar provides access to every module. The main content area displays the active page. The header contains the language switcher, the light/dark theme toggle, and the user profile menu. The dark mode design is optimized for extended working sessions in low-light environments.

---

## 02 — Dashboard & Customization

The dashboard is the central overview page of FleetPilot. It aggregates all key metrics at a glance and can be fully customized to match each user's operational priorities.

**Quick Stats.** The top row of the dashboard features seven metric cards showing: Managed Hosts, Disk Drives (via Disk Tools), Update Runs, Active Users, VM Controllers, Storage Controllers, and Unique Tags. Each card is color-coded and includes a brief description.

**Widget System.** FleetPilot provides a fully drag-and-drop customizable widget system. Click the "Customize" button in the top-right corner to enter edit mode. In this mode you can reorder widgets by dragging them. To hide a widget, click the red "×" symbol on it; hidden widgets move to the "Hidden Widgets" panel and can be restored by clicking them there. Once satisfied, click "Save Layout" to persist the arrangement. Each user's layout is stored independently in the database. A "Reset" option restores the default layout.

The ten available widgets are summarized below.

| Widget | Description |
|--------|-------------|
| Quick Stats | Seven metric cards at the top of the page |
| Fleet Overview | Table of all managed hosts with status indicators |
| VM Controllers | Summary of connected Proxmox / Veeam endpoints |
| Storage Controllers | Summary of connected NAS / SAN endpoints |
| SMART Health Summary | Aggregated disk health across all monitored drives |
| Environment Breakdown | Pie chart of hosts by environment (Prod / Staging / Dev / Test) |
| Tag Cloud | Visual representation of all assigned host tags |
| Recent Updates | Last five update runs with result status |
| Navigation Cards | Quick-access tiles to all modules |
| Plugin Widgets | Output rendered by installed plugins |

---

## 03 — Host Management & Adding Servers

Host management is the operational core of FleetPilot. Every managed server, PC, or workstation is registered here and serves as the anchor for updates, SMART monitoring, SSH actions, and OS detection.

### Adding a Server

Click **"+ Add Host"** in the header of the Manage Hosts page. The form requires the following fields.

| Field | Description | Validation |
|-------|-------------|------------|
| **Name** | Unique display name for the host | Required |
| **IP / Hostname** | Network address of the server | IPv4, IPv6, or RFC-1123 hostname |
| **Environment** | Operational context | Production, Staging, Development, Testing |
| **Criticality** | Business impact level | Low, Medium, High, Critical |
| **SSH User** | Username for SSH connections | Optional (defaults to system user) |
| **Group** | Logical grouping label | Optional free text |
| **Tags** | Comma-separated metadata tags | Optional |
| **Description** | Free-text notes | Optional |

Click "Save" to store the host. The system immediately validates the IP address or hostname format and will reject invalid entries.

### OS Auto-Detection

After adding a host, click the **"Detect OS"** button in the host actions menu. FleetPilot connects via SSH, reads `/etc/os-release`, and automatically assigns the correct OS profile. The host card then displays the matching Linux distribution logo (Ubuntu, Debian, Proxmox, CentOS, etc.) or the Windows logo. This information is persisted in the host record.

### Custom Server Images

For better visual identification in large environments, you can upload a custom photograph or icon for any host. Click the **"Upload Image"** button in the host actions menu and select an image file. The image is stored on the server and displayed in the host card.

### Filtering and Searching

The search bar at the top of the Manage Hosts page filters hosts in real time by name, IP address, group, tag, or description. The dropdown menus provide additional filtering by environment, criticality, tag, and group. The view can be toggled between card view and list view.

### Host Actions

Each host card provides the following quick actions.

| Action | Description |
|--------|-------------|
| **Edit** | Modify all host properties |
| **SSH** | Copy a direct SSH command to the clipboard |
| **MAC** | Retrieve the MAC address via ARP |
| **Update** | Trigger a system update on this host |
| **Detect OS** | Run OS auto-detection via SSH |
| **Upload Image** | Set a custom image for this host |
| **Delete** | Permanently remove the host (red trash button) |

---

## 04 — Update Manager

The Update Manager provides centralized execution and tracking of system updates across all managed hosts, as well as self-maintenance of the FleetPilot instance.

**Starting an Update.** Navigate to a host and click "Update", or use the Update Dashboard to manage all hosts simultaneously. FleetPilot connects via SSH and executes `apt update && apt upgrade -y`. The system supports password authentication and features automatic root detection: if the configured user is `root`, the `sudo` prefix is omitted automatically. The entire update process is streamed in real time to the browser via Server-Sent Events (SSE).

**Update History.** The Update Dashboard maintains a complete history of all performed updates, recording the timestamp, host name, and the final result (success or failure). The five most recent updates are also shown in the "Recent Updates" dashboard widget.

**Automatic Updates.** FleetPilot supports configuring automatic update schedules. Settings are found in the host properties under "Maintenance Window".

**FleetPilot Self-Update.** FleetPilot can update itself directly from its GitHub repository. Navigate to Server → Update in the sidebar. The self-update mechanism includes an automatic stash feature: before pulling the latest changes, any untracked or manually modified files are safely stashed, preventing update failures caused by file conflicts. After the pull, the FleetPilot service is automatically restarted.

---

## 05 — VM Controller

The VM Controller integrates virtualization platforms, enabling monitoring and control of virtual machines and containers directly from FleetPilot.

### Connecting Proxmox VE

Click **"+ Add Endpoint"** and select "Proxmox VE". Provide the following details.

| Field | Default | Description |
|-------|---------|-------------|
| Host | — | IP address or hostname of the Proxmox node |
| Port | 8006 | HTTPS API port |
| User | root | Proxmox username (format: `user@realm`, e.g. `root@pam`) |
| API Token / Password | — | Authentication credential |
| SSL Verify | Enabled | Disable for self-signed certificates |

After saving, FleetPilot tests the connection. The system features an automatic exponential backoff retry mechanism (up to 3 attempts with 1 s → 2 s → 4 s delays) to handle transient network timeouts gracefully. HTTP 4xx/5xx errors are not retried.

### VM Overview

After a successful connection, all virtual machines and containers in the Proxmox cluster are listed. For each VM, the interface displays the current status, CPU usage, RAM consumption, and uptime. The "View" button opens the Proxmox web interface directly for that VM.

### VM Power Actions

The following power actions can be triggered directly from FleetPilot and are secured with CSRF tokens to prevent cross-site request forgery.

| Action | Description |
|--------|-------------|
| **Start** | Power on the VM |
| **Stop** | Force power off (equivalent to pulling the power) |
| **Shutdown** | Graceful ACPI shutdown |

### Disk Inventory

The "Disks" button on the VM Controller detail page shows all physical hard drives of the Proxmox host, including SMART status, model, capacity, and condition. This data is automatically fed into the SMART monitoring module.

### Veeam Integration

If Veeam Backup & Replication is connected to the Proxmox environment, FleetPilot can display and trigger Veeam backup jobs directly from the VM detail page.

---

## 06 — Storage Controller

The Storage Controller integrates Network Attached Storage (NAS) and Storage Area Network (SAN) systems, providing unified visibility into storage pools, volumes, and physical drives.

### Adding a Storage System

Click **"+ Add Controller"** and select the platform type.

| Platform | Authentication | Protocol |
|----------|---------------|----------|
| **Unraid** | API Key (`x-api-key` header) | HTTPS GraphQL (port 443) |
| **TrueNAS** | API Key | HTTPS REST |
| **Generic NAS** | Username / Password | HTTP or HTTPS |

For Unraid servers running version 6.12 or newer, FleetPilot uses the Unraid Connect GraphQL API. The API key must be generated in the Unraid web interface under Settings → API Keys. Enter the host IP address, port 443, and the API key when adding the endpoint.

### Pool and Volume Overview

After connecting, FleetPilot displays all storage pools and volumes with their utilization metrics. Fill levels are color-coded: yellow above 75% and red above 90% to alert administrators to capacity constraints.

### Disk Inventory (Unraid)

The disk inventory view provides a complete breakdown of all drives connected to the Unraid server. The following information is displayed for each drive.

| Field | Description |
|-------|-------------|
| **Name** | Logical disk name (disk1, disk2, parity, cache, etc.) |
| **Pool** | Assignment (array, parity, cache) |
| **Size** | Capacity in GB or TB |
| **Temperature** | Current drive temperature in °C |
| **Health** | SMART health status (GOOD, WARNING, FAILING) |
| **Model** | Manufacturer model string |
| **Serial** | Drive serial number |

---

## 07 — Disk Management & SMART

The Disk Management module proactively monitors the health of all hard drives and SSDs using the SMART (Self-Monitoring, Analysis and Reporting Technology) protocol.

**SMART Dashboard.** The dashboard categorizes all monitored drives by health status: Healthy (green), Warning (yellow), or Critical (red). Critical SMART attributes — Reallocated Sectors, Pending Sectors, and Uncorrectable Errors — are prominently highlighted.

**Disk Tools.** The Disk Tools module enables direct disk management: starting SMART tests, viewing the complete attribute list, exporting the disk inventory, and importing SMART data from remote hosts.

**Automatic Polling.** FleetPilot polls SMART data automatically at configurable intervals. A manual poll can be triggered at any time using the "Poll Now" button. Critical status changes are reflected immediately in the dashboard widget.

---

## 08 — Backup Controller

The Backup Controller provides a unified interface for monitoring and managing backup solutions across the infrastructure.

### Supported Backup Systems

| Platform | Protocol | Authentication |
|----------|----------|----------------|
| **Proxmox Backup Server (PBS)** | HTTPS REST | API Token |
| **Duplicati** | HTTP REST | Password / Bearer Token |
| **Restic** | HTTP REST | Basic Auth |
| **BorgWarehouse** | HTTP REST | Bearer Token |
| **UrBackup** | HTTP | Session Auth |
| **Bacula** | SSH + bconsole | SSH Key / Password |
| **SSH Generic** | SSH | SSH Key / Password |

### Adding a Backup Server

Click **"+ Add Server"** on the Backup overview page. Select the server type; the form adapts to request the protocol-specific fields. After saving, FleetPilot tests the connection and begins polling in the background every 60 seconds.

### Monitoring and Actions

The backup server detail page displays datastores, backup jobs, recent snapshots, and quota usage. A 24-hour history chart visualizes backup activity over time. Administrators can manually trigger backup jobs directly from the FleetPilot interface using the "Trigger" button.

---

## 09 — Fan Controller & Cooling

The Fan Controller module enables remote monitoring and management of cooling systems across servers and workstations.

### Universal Fan Controller

FleetPilot supports the following controller backends.

| Backend | Tool | Use Case |
|---------|------|----------|
| **lm-sensors** | lm-sensors + fancontrol | Linux servers / desktops (PWM sysfs) |
| **ipmi** | ipmitool | Servers with IPMI/BMC (Dell iDRAC, HP iLO, Supermicro) |
| **nbfc** | nbfc-linux | Laptops |
| **liquidctl** | liquidctl | NZXT, Aquacomputer, Kraken, HUE 2 |
| **pwm_sysfs** | Built-in | Direct `/sys/class/hwmon` PWM control |

### Adding a Device

Click **"+ Add Device"** on the Fan Controller overview page. Enter the SSH connection details (host, port, username, password or SSH key). Then click **"Auto-Detect Controllers"** to let FleetPilot analyze the remote hardware. The system checks the chassis type, installed tools, and hardware vendor, then presents a prioritized list of suggested controller configurations with confidence levels (High / Medium / Low). Select the most appropriate suggestion and click "Use This" to pre-fill the form, or configure manually.

### Corsair Commander Pro

The dedicated Corsair Commander Pro module integrates via SSH and `liquidctl`. It provides:

- Real-time temperature and fan RPM readings from all connected sensors and fan headers.
- Manual fan speed control using fixed duty cycles (0–100%).
- Dynamic temperature-based fan curves with configurable control points.
- Interactive Chart.js graphs displaying historical temperature and RPM data.
- Polling every 30 seconds with 30-day history stored in the database.

---

## 10 — CheckMK Integration

FleetPilot integrates with CheckMK to bring advanced monitoring alerts directly into the dashboard.

**Connecting CheckMK.** Navigate to CheckMK in the sidebar. Enter the CheckMK URL, site name, and an API token. The API token must be created in CheckMK under Users → API Tokens. Click "Test Connection" to verify the credentials before saving.

**API Authentication.** All CheckMK API requests use Bearer Token authentication transmitted in the `Authorization: Bearer <token>` HTTP header. The token status and usage examples can be retrieved at any time via the `/api/checkmk/token_info` endpoint.

**Monitoring Data.** After a successful connection, FleetPilot displays real-time host statuses, service states, and active alerts aggregated from CheckMK. Data is updated automatically.

---

## 11 — User Management & Plugins

**User Roles.** FleetPilot implements role-based access control. Three roles are available.

| Role | Permissions |
|------|-------------|
| **Admin** | Full access to all modules, user management, and system settings |
| **Operator** | Can trigger updates, VM actions, and backup jobs; cannot manage users |
| **Viewer** | Read-only access to all dashboards and status pages |

**Managing Users.** Navigate to Users in the sidebar (Admin only). From there you can add new users, edit existing accounts, change passwords, and assign roles. Each user can customize their own dashboard layout and profile settings independently.

**Plugin Manager.** FleetPilot supports extending functionality through plugins. Navigate to Plugins in the sidebar to view installed plugins, upload new plugin files, or install plugins from the online repository. Plugins can add new dashboard widgets, sidebar entries, and API endpoints.

---

*FleetPilot User Guide — Version 2.0 — July 2026*
