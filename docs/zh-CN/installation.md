# 安装 FleetPilot

本指南涵盖 FleetPilot 的所有安装方式，以及安装程序会配置什么、首次登录、HTTPS、更新、备份、卸载和故障排查。

*德语版：[de/installation.md](de/installation.md)*

**目录**

1. [选择安装方式](#1-choose-a-way-to-install)
2. [Proxmox VE：一条命令（推荐）](#2-proxmox-ve-one-command-recommended)
3. [Debian、Ubuntu 或 Raspberry Pi OS](#3-debian-ubuntu-or-raspberry-pi-os)
4. [首次登录](#4-first-sign-in)
5. [授予 FleetPilot 访问服务器的权限](#5-give-fleetpilot-access-to-your-servers)
6. [HTTPS 与自有证书](#6-https-and-your-own-certificate)
7. [更新](#7-updating)
8. [备份与恢复](#8-backup-and-restore)
9. [设置参考（`.env`）](#9-settings-reference-env)
10. [高安全环境](#10-high-security-sites)
11. [卸载](#11-uninstalling)
12. [故障排查](#12-troubleshooting)

---

## 1. 选择安装方式

| 您拥有 | 使用 | 耗时 |
|---|---|---|
| 一台 Proxmox VE 服务器 | [Proxmox 辅助脚本](#2-proxmox-ve-one-command-recommended)：它会创建一个容器，并在其中安装 FleetPilot | 约 4 分钟 |
| 一台 Debian/Ubuntu 服务器、虚拟机或容器 | [`install.sh`](#3-debian-ubuntu-or-raspberry-pi-os) | 约 3 分钟 |
| 一台 Raspberry Pi（3、4 或 5） | [`install.sh`](#3-debian-ubuntu-or-raspberry-pi-os)；它还会安装风扇和 USB 相关工具 | 约 5 分钟 |

**环境要求**

- Debian 12 或 13、Ubuntu 22.04 或 24.04，或 Raspberry Pi OS（Bookworm 或 Trixie），建议使用 64 位。
- 最低 1 个 CPU 核心、1 GB 内存和 4 GB 磁盘；建议 2 核、2 GB 内存和 8 GB 磁盘（Proxmox 脚本使用的就是这套配置）。
- 安装期间需要访问互联网（GitHub 和 Python 软件包索引）。
- 需要 root 权限。

FleetPilot 通过 SSH 管理其他机器，因此不需要运行在被管理的机器上。

---

## 2. Proxmox VE：一条命令（推荐）

打开 Proxmox 节点的 **Shell**（Web 界面 → 节点 → *Shell*），然后运行：

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)"
```

脚本只问一个问题：

- **默认设置**（Default settings）：下一个可用的容器 ID、2 核、2 GB 内存、8 GB 磁盘、`vmbr0` 上启用 DHCP、开启 HTTPS。存储位置自动选择。
- **高级**（Advanced）：选择容器 ID、主机名、核心数、内存、磁盘、存储、网桥、VLAN、带网关的静态 IP、容器 root 用户的 SSH 密钥，以及使用 HTTPS 还是纯 HTTP。

然后它会：

1. 下载最新的 Debian 13 容器模板（如果没有 13，则用 Debian 12）。
2. 创建一个**非特权**容器，启用嵌套、开机自启，标签为 `fleetpilot`。
3. 在其中用 `install.sh` 安装 FleetPilot（它会做什么见下一节）。
4. 把访问地址和凭据位置写入 Proxmox 界面中该容器的 **Notes**，并打印一份摘要：

```text
 ✔ FleetPilot is ready in container 114.
  Open:       https://192.168.1.62
  User:       admin
  Password:   (shown once; also in /root/fleetpilot-credentials.txt inside the container)
```

密码在首次安装时生成，只显示一次，并保存在容器内的 `/root/fleetpilot-credentials.txt`（仅 root 可读）。以后要查看：

```bash
pct exec 114 -- cat /root/fleetpilot-credentials.txt
```

### 无人值守安装

所有问题都可以提前用环境变量回答，例如：

```bash
CT_ID=150 CT_HOSTNAME=fleetpilot CT_RAM=4096 CT_IP=192.168.1.50/24 CT_GW=192.168.1.1 FP_DEFAULTS=1 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)"
```

| 变量 | 默认值 | 含义 |
|---|---|---|
| `CT_ID` | 下一个可用 ID | 容器 ID |
| `CT_HOSTNAME` | `fleetpilot` | 主机名 |
| `CT_CORES` / `CT_RAM` / `CT_DISK` | `2` / `2048`（MB）/ `8`（GB） | 资源 |
| `CT_STORAGE` | 第一个可用于容器的存储 | 根磁盘的存储位置，例如 `local-lvm` |
| `CT_TEMPLATE_STORAGE` | 第一个可用于模板的存储 | Debian 模板的存放位置，例如 `local` |
| `CT_BRIDGE` / `CT_VLAN` | `vmbr0` / 无 | 网络网桥和可选的 VLAN 标签 |
| `CT_IP` / `CT_GW` | `dhcp` / 无 | `dhcp`，或像 `192.168.1.50/24` 这样的地址加网关 |
| `CT_SSH_KEY` | 无 | 容器 root 用户的公钥文件 |
| `FP_HTTPS` | `yes` | `no` 表示在 5000 端口提供纯 HTTP |
| `FP_BRANCH` | `main` | 要安装的 Git 分支或标签 |
| `FP_DEFAULTS` | 未设置 | `1` 表示跳过所有提问 |

### 管理 Proxmox 宿主机本身

容器看不到宿主机的磁盘。要获取 Proxmox 节点的 SMART 数据、更新和硬件信息，请在**主机管理**中像添加其他服务器一样添加该节点。脚本会打印 FleetPilot 的公钥，以及在宿主机上授权它的完整命令。

要显示该节点上的虚拟机和容器，请在**虚拟机控制器**中用 API 令牌添加它（见[用户指南](user-guide.md#vm-controllers)）。

### 更新容器

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)" -- update 114
```

把 `114` 换成您的容器 ID。数据和设置会保留。

---

## 3. Debian、Ubuntu 或 Raspberry Pi OS

在将运行 FleetPilot 的机器上以 root 身份执行：

```bash
curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/install.sh | bash
```

或者从仓库副本安装：

```bash
git clone https://github.com/ChristianHandy/FleetPilot.git
```

```bash
sudo bash FleetPilot/install.sh
```

较旧的 `install-debian.sh` 和 `install_raspberry_pi.sh` 仍然可用；它们实际调用的是 `install.sh`。

### 安装程序会做什么

| 步骤 | 说明 |
|---|---|
| 软件包 | Python 3、venv、git、OpenSSH 客户端、`smartmontools`、`sudo`；HTTPS 还需要 nginx 和 OpenSSL。在 Raspberry Pi 上还会安装 `lm-sensors`、`ipmitool` 和 USB HID 库 |
| 服务用户 | 一个名为 `fleetpilot` 的系统用户，无密码、无登录 shell |
| 代码 | `/opt/fleetpilot`，属主为 root，**对服务只读** |
| 数据 | `/opt/fleetpilot/data`（数据库、设置、备份）和 `/opt/fleetpilot/logs`，属主为 `fleetpilot`，权限 0700/0750 |
| SSH 密钥 | 在 `/opt/fleetpilot/.ssh/id_ed25519` 生成新的 Ed25519 密钥，FleetPilot 用它访问您的服务器 |
| root 辅助程序 | `/usr/local/lib/fleetpilot` 下三个属主为 root 的小辅助程序（磁盘操作、FleetPilot 更新、代理应用）。一条 sudo 规则只允许以固定参数调用这三个程序，别的都不行 |
| 设置 | `/opt/fleetpilot/.env`（root:fleetpilot，0640），内含随机生成的 `SECRET_KEY`。已有值永远不会被覆盖 |
| 服务 | `fleetpilot.service`（gunicorn），开机自启，带 systemd 沙箱 |
| HTTPS | 443 端口上的 nginx，使用 `/etc/fleetpilot/tls` 中的自签名证书；FleetPilot 本身只监听 `127.0.0.1:5000` |
| 检查 | 等待 `/healthz` 响应，然后打印访问地址和凭据，并保存到 `/root/fleetpilot-credentials.txt` |

再次运行安装程序会**更新**现有安装，并保留您的数据和设置。

### 选项

| 变量 | 默认值 | 含义 |
|---|---|---|
| `FP_NONINTERACTIVE` | `0` | `1` 表示从不提问 |
| `FP_HTTPS` | `yes` | `no` 表示不经 nginx 直接提供 `http://<ip>:5000`（仅限可信网络） |
| `FP_ADMIN_PASSWORD` | 随机生成 | 第一个管理员账户的密码（至少 12 个字符） |
| `FP_EXTRAS` | 在 Pi 上为 `yes`，其他平台为 `no` | 风扇、IPMI 和 USB-HID 工具 |
| `FP_BRANCH` | `main` | 要安装的分支或标签 |
| `FP_REPO` | GitHub URL | 安装所用的仓库（用于 fork 或镜像） |

示例：

```bash
curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/install.sh | FP_NONINTERACTIVE=1 FP_EXTRAS=yes bash
```

### Raspberry Pi 附加功能

在 Raspberry Pi 上，安装程序还可以把这台 Pi 配置为 **Proxmox QDevice**（双节点集群的裁决投票）。被询问时回答 *yes*，然后在某个 Proxmox 节点上运行 `pvecm qdevice setup <pi-ip>`。

### 端口

| 端口 | 监听地址 | 用途 |
|---|---|---|
| 443 | 所有地址 | 通过 nginx 提供 FleetPilot 的 HTTPS |
| 5000 | 127.0.0.1 | FleetPilot 本身（gunicorn）；开启 HTTPS 时无法从网络访问 |
| 8080 | 127.0.0.1 | 供本地 HAProxy（代理服务）使用的纯 HTTP；无法从网络访问 |

80 端口保持空闲，以便可选的 HAProxy 入口使用。请直接访问 `https://<ip>`。

---

## 4. 首次登录

1. 打开安装程序显示的地址，例如 `https://192.168.1.62`。
2. 浏览器会针对自签名证书警告一次。接受它，或者[安装您自己的证书](#6-https-and-your-own-certificate)。
3. 用 `admin` 和生成的密码登录。
4. 建议立即完成以下设置：
   - **账户 → 我的资料**：修改密码。
   - **账户 → 登录与安全**：按链接设置两步验证，可以使用身份验证器应用或安全密钥（YubiKey、通行密钥）。管理员可以在 **系统 → 安全中心** 强制要求所有管理员使用两步验证。
   - **系统 → 安全中心**：阅读各项检查；全新安装后，除依赖您所选配置的项（例如受信任的证书）之外，其余应全部为绿色。
   - **账户 → 用户**：为其他人创建各自的账户，不要共用 `admin`。角色：*管理员*（全部权限）、*运维员*（执行操作）、*只读*（只能查看）。

忘了管理员密码？在 FleetPilot 服务器或容器上执行：

```bash
sudo bash /opt/fleetpilot/reset-password.sh
```

用 `--generate` 生成并打印一个随机密码，用 `--list` 列出用户，或传入另一个用户名。该用户已打开的会话会被登出。

---

## 5. 授予 FleetPilot 访问服务器的权限

FleetPilot 用自己的密钥通过 SSH 访问您的服务器。查看公钥：

```bash
cat /opt/fleetpilot/.ssh/id_ed25519.pub
```

然后对每台服务器，选择以下任一方式：

- **在 Web 界面中**：*主机管理 → 添加主机*，然后在主机上点击*安装密钥*（只需输入一次该服务器的密码，不会保存任何内容）；或者
- **手动操作**：把公钥追加到该服务器上供 FleetPilot 使用的用户的 `~/.ssh/authorized_keys`。

为了执行更新、磁盘工具和 SMART 相关操作，该用户需要 root 权限，或针对包管理器和 `smartctl` 的 sudo 规则。Windows 主机需要启用 OpenSSH 服务器功能。

首次连接时 FleetPilot 会保存服务器的主机密钥（*首次使用即信任*），如果以后发生变化就会拒绝连接。不允许「首次使用即信任」的场所可以启用[严格主机密钥](#10-high-security-sites)。

---

## 6. HTTPS 与自有证书

安装程序会为机器的 hostname 和 IP 地址创建自签名证书（ECDSA P-256，有效期 825 天）。HSTS 保持关闭，因为浏览器无法信任自签名证书。

要使用自有 CA 或 Let's Encrypt 签发的证书，请替换下面两个文件（证书链和私钥，PEM 格式）并重新加载 nginx：

```bash
sudo cp fullchain.pem /etc/fleetpilot/tls/fullchain.pem
```

```bash
sudo install -m 0600 privkey.pem /etc/fleetpilot/tls/privkey.pem
```

```bash
sudo nginx -t
```

```bash
sudo systemctl reload nginx
```

使用受信任的证书后可以开启 HSTS：在 `/opt/fleetpilot/.env` 中设置 `FLEETPILOT_HSTS=true`，然后重启 FleetPilot（`sudo systemctl restart fleetpilot`）。完整的加固 TLS 配置见 `deploy/nginx-fleetpilot-tls.conf`。

在自有反向代理（Traefik、Caddy、nginx Proxy Manager）之后：如果代理与 FleetPilot 同机运行，保持 `GUNICORN_BIND=127.0.0.1:5000`；设置 `FLEETPILOT_TRUST_PROXY=true`；并确保代理会设置 `X-Forwarded-For` 和 `X-Forwarded-Proto`。只有确实有代理在前面时才启用 `FLEETPILOT_TRUST_PROXY`，否则客户端可以伪造自己的地址。

---

## 7. 更新

以下任一方式都可以；数据和设置始终保留：

- **Web 界面**：在 *系统 → FleetPilot 更新*（管理员）中检查并应用新版本。
- **安装程序**：再次运行同一条 `install.sh` 命令。
- **Proxmox**：用 `-- update <容器 ID>` 运行辅助脚本。

大版本更新前，先在 *系统 → 备份* 中下载一份备份。更新后请刷新一次浏览器页面。

---

## 8. 备份与恢复

*系统 → 备份* 会创建一份一致的备份，包含用户、主机、控制器设置、SMART 历史和密钥。每日自动备份在 03:00 运行，保留最近 7 份（`FLEETPILOT_AUTO_BACKUP`、`FLEETPILOT_BACKUP_HOUR`、`FLEETPILOT_BACKUP_KEEP`）。备份存放在 `/opt/fleetpilot/data/backups`。

- **下载**（Download）备份到别处保留一份副本。备份内含密码哈希和加密凭据，请妥善保管。
- **恢复**（Restore）：上传备份并选择*暂存恢复*。FleetPilot 会校验它，并在下次重启时应用，同时保留原有的文件。

如果需要整机备份，请备份 `/opt/fleetpilot/data` 和 `/opt/fleetpilot/.env`，或用 Proxmox Backup Server 备份整个容器。

---

## 9. 设置参考（`.env`）

设置保存在 `/opt/fleetpilot/.env` 中。修改后重启：`sudo systemctl restart fleetpilot`。

| 设置项 | 默认值 | 含义 |
|---|---|---|
| `SECRET_KEY` | 随机生成 | 用于签名会话并加密保存的凭据。绝不要在运行中的安装上更改它：已保存的密码将无法解密 |
| `DASHBOARD_USERNAME` | `admin` | 第一个管理员账户的名称 |
| `DASHBOARD_PASSWORD` | 随机生成 | 第一个管理员的密码；仅在首次启动时读取，之后由安装程序删除 |
| `FLEETPILOT_DATA_DIR` | `/opt/fleetpilot/data` | 所有数据的存放位置 |
| `GUNICORN_BIND` | `127.0.0.1:5000` | 应用服务器的地址和端口 |
| `GUNICORN_THREADS` | `4` | 请求线程数 |
| `FLEETPILOT_PRODUCTION` | 启用 HTTPS 时为 `true` | 生产环境默认值（安全 Cookie、严格检查） |
| `FLEETPILOT_COOKIE_SECURE` | 启用 HTTPS 时为 `true` | 仅通过 HTTPS 发送 Cookie |
| `FLEETPILOT_TRUST_PROXY` | 启用 HTTPS 时为 `true` | 信任本地代理传来的 `X-Forwarded-*` 请求头 |
| `FLEETPILOT_HSTS` | `false` | 发送 HSTS；仅在证书受信任时使用 |
| `FLEETPILOT_SESSION_MINUTES` | `480` | 会话有效期（15–1440） |
| `FLEETPILOT_AUTO_BACKUP` / `_BACKUP_HOUR` / `_BACKUP_KEEP` | `true` / `3` / `7` | 每日数据备份 |
| `FLEETPILOT_ROUTER_POLL_MINUTES` | `5` | 路由器检查频率；设为 `0` 可关闭 |
| `FLEETPILOT_VERIFY_SSL` | `false` | 校验虚拟机、存储和备份 API 的 TLS 证书。这些 API 使用受信任证书时请开启 |
| `FLEETPILOT_WEBAUTHN_RP_ID` / `_ORIGIN` | 取自访问地址 | 当 FleetPilot 以其他名字运行时，安全密钥所用的域名和来源 |
| `FLEETPILOT_FIPS` | 关闭 | 见[高安全环境](#10-high-security-sites) |
| `FLEETPILOT_SSH_STRICT_HOST_KEYS` | 关闭 | 见[高安全环境](#10-high-security-sites) |
| `FLEETPILOT_OFFLINE` | 关闭 | 见[高安全环境](#10-high-security-sites) |
| `SYNC_TOKEN` | 无 | 两个 FleetPilot 实例复制数据时共用的密钥 |
| `YUBICO_CLIENT_ID` / `YUBICO_SECRET_KEY` | 无 | 仅用于旧式 YubiKey OTP |

---

## 10. 高安全环境

对于受监管或物理隔离的环境，请在 `.env` 中添加：

```ini
FLEETPILOT_FIPS=true
FLEETPILOT_SSH_STRICT_HOST_KEYS=true
FLEETPILOT_OFFLINE=true
```

- **FIPS**：密码只用 PBKDF2-HMAC-SHA256 存储；已有的哈希会在下次登录时升级。
- **严格主机密钥**：FleetPilot 只连接主机密钥已存在于 `/opt/fleetpilot/data/known_hosts` 中的服务器。
- **离线**：不检查更新，也没有在线插件目录。

如需更严格的 systemd 沙箱，请安装严格配置：

```bash
sudo install -D -m 0644 /opt/fleetpilot/deploy/fleetpilot-strict.conf /etc/systemd/system/fleetpilot.service.d/strict.conf
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl restart fleetpilot
```

严格配置会禁止在 FleetPilot 所在机器上使用本地磁盘工具和风扇控制；通过 SSH 管理其他机器不受影响。详情见 [SECURITY.md](../SECURITY.md) 和 [production_profile.md](production_profile.md)。

---

## 11. 卸载

**Proxmox 容器**：在 Proxmox 界面中停止并移除容器，或执行：

```bash
pct stop 114
```

```bash
pct destroy 114
```

**Debian/Ubuntu/Raspberry Pi**：如果想保留数据，请先做一份备份，然后执行：

```bash
sudo systemctl disable --now fleetpilot
```

```bash
sudo rm -rf /opt/fleetpilot /etc/fleetpilot /usr/local/lib/fleetpilot /etc/sudoers.d/fleetpilot /etc/systemd/system/fleetpilot.service /etc/systemd/system/fleetpilot.service.d /etc/nginx/sites-enabled/fleetpilot* /etc/nginx/sites-available/fleetpilot* /root/fleetpilot-credentials.txt
```

```bash
sudo userdel fleetpilot
```

```bash
sudo systemctl reload nginx
```

从您服务器的 `authorized_keys` 文件中删除 FleetPilot 的公钥。

---

## 12. 故障排查

| 问题 | 处理方法 |
|---|---|
| 页面打不开 | 执行 `systemctl status fleetpilot nginx`，然后执行 `journalctl -u fleetpilot -n 50` |
| `http://<ip>` 没有响应 | 请改用 `https://<ip>`。80 端口留给 HAProxy |
| 提示「Security token expired or missing」（安全令牌已过期或缺失） | 页面打开时间过长，或 Cookie 被拦截。刷新页面后重试。在自有代理后面时，检查它是否传递了 `X-Forwarded-Proto: https` |
| 登录失败次数过多被锁定 | 等待锁定结束（默认 10 分钟，可在 *安全中心 → 登录规则* 中设置），或用 `reset-password.sh` 重置密码 |
| 某台服务器显示离线 | FleetPilot 检查的是 SSH 端口。检查地址、端口和防火墙；用 `sudo -u fleetpilot ssh -i /opt/fleetpilot/.ssh/id_ed25519 user@server` 测试 |
| 提示「Host key changed」（主机密钥已变更） | 服务器被重装，或其地址现在属于另一台机器。如果确实如此，从 `/opt/fleetpilot/data/known_hosts` 中删除对应行 |
| 安装程序在 Proxmox 容器中中断 | 再运行一次 Proxmox 更新命令，安装程序会继续执行。完整日志在容器内：`journalctl -u fleetpilot` |
| 在较旧的 LXC 中服务无法启动 | 安装程序会自动添加兼容的沙箱配置片段（`/etc/systemd/system/fleetpilot.service.d/lxc.conf`） |
| 安装插件时提示文件夹只读 | 这是有意设计的。以 root 身份把插件文件复制到 `/opt/fleetpilot/addons`，然后重启 FleetPilot |

仍然卡住？提交 issue 并附上 `journalctl -u fleetpilot -n 100` 的输出（请去掉您认为属于隐私的地址和名称）：<https://github.com/ChristianHandy/FleetPilot/issues>
