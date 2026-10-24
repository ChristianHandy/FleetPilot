# FleetPilot 用户指南

**版本 1.7** · 面向管理员、运维员与只读用户

FleetPilot 用一个网页界面，管起家庭实验室或小公司里的服务器、PC、路由器、磁盘、虚拟机、存储和备份。它通过 SSH，以及 Proxmox、TrueNAS、Unraid 和各备份系统提供的 API 访问您的机器。被管的机器上什么都不用装。

FleetPilot 的安装请见 **[安装指南](installation.md)**。*德语版：[de/benutzerhandbuch.md](de/benutzerhandbuch.md)*

**目录**

- [1. 基础](#1-basics)：登录、界面、角色、语言、无障碍
- [2. 首页](#2-home)
- [3. 服务器](#3-servers)：[主机管理](#manage-hosts) · [网络扫描](#network-scanner) · [路由器](#routers) · [更新仪表盘](#update-dashboard) · [服务器更新](#server-update)
- [4. 硬件](#4-hardware)：[硬件概览](#hardware-overview) · [硬件监控](#hw-monitor) · [SMART 健康](#smart-health) · [存储与磁盘](#storage--disks) · [风扇与散热](#fans--cooling)
- [5. 虚拟化与存储](#5-virtualisation-and-storage)：[虚拟机控制器](#vm-controllers) · [存储控制器](#storage-controllers) · [备份服务器](#backup-servers)
- [6. 运维](#6-operations)：[定时关机](#scheduled-shutdown) · [CheckMK](#checkmk) · [系统监控](#system-monitor) · [FleetPilot 更新](#fleetpilot-update)
- [7. 系统](#7-system)：[更新设置](#update-settings) · [邮件配置](#email-config) · [代理服务](#proxy-services) · [生产状态](#production-status) · [安全中心](#security-center) · [通知](#notifications) · [审计日志](#audit-trail) · [备份](#backups) · [插件](#plugins)
- [8. 账户](#8-account)：[我的资料](#my-profile) · [登录与安全](#sign-in--security) · [两步验证](#two-factor-sign-in) · [无障碍](#accessibility) · [用户管理](#user-management)
- [9. 集成](#9-integrations)：API 令牌与 REST API · 安卓应用 · Prometheus · Home Assistant · 公开状态页
- [10. 安全须知](#10-security-notes)
- [11. 常见问题](#11-frequently-asked-questions)

---

## 1. 基础

### 登录

在浏览器中打开 FleetPilot（例如 `https://192.168.1.62`），用用户名和密码登录。如果您的账户已开启两步验证，FleetPilot 随后会要求输入身份验证器应用生成的验证码、安全密钥或备用码。

登录后，页面会显示一条简短提示，说明上次登录的时间和来源，以及此后登录失败的次数。如果这些记录不是您本人的操作，请修改密码，并检查 **账户 → 登录与安全**（Account → Sign-in & security）。

密码输错次数过多，账户会被暂时锁定（默认 10 次、10 分钟）。会话在闲置 2 小时后或累计 12 小时后结束；这两项管理员都可以在安全中心修改。

### 界面

- **侧边栏**（左侧）：所有功能区域，分为 *服务器*、*硬件*、*虚拟化*、*运维*、*系统* 和 *账户* 六组。分组可以折叠。在手机上，点菜单按钮即可打开侧边栏。
- **页眉**：页面标题、一行说明和该页的主要按钮。
- **右上角**：语言、浅色/深色主题、无障碍设置、个人资料和 *退出*。

### 角色

每个用户都有一个或多个角色：

| 角色 | 可执行的操作 |
|---|---|
| **viewer**（只读） | 查看除安全设置、用户和密钥之外的所有内容 |
| **operator**（运维员） | 另外可以执行操作：更新、SMART 巡检、备份、唤醒/关闭主机、启动/停止虚拟机、路由器备份 |
| **admin**（管理员） | 全部权限：添加和移除系统、用户、安全设置、恢复备份、更新 FleetPilot、重启路由器 |

修改与安全相关数据的操作（用户、令牌、安全规则、备份），如果距上次密码确认已超过 10 分钟，会再次要求您输入密码。

### 语言

English（英语）、Deutsch（德语）、Français（法语）、Español（西班牙语）、Nederlands（荷兰语）。在右上角选择语言，选择结果会保存在您的资料中。

参与翻译的贡献者可以在源码检出目录中运行 `python scripts/missing_translations.py`，列出尚未翻译的模板字符串及其按语言统计的数量。用 `--lang de` 只检查一种语言。该命令在全部翻译完成时以 `0` 退出，有缺失时以 `1` 退出，参数无效时以 `2` 退出；它不会启动 FleetPilot。

### 无障碍

**账户 → 无障碍**（Account → Accessibility）让 FleetPilot 更易读、更好用：更大的文字、高对比度、易读字体、更宽的间距、带下划线的链接、减少动效，以及「易读语言」——菜单名称更简单，每个页面都附一段简短的通俗说明（英语和德语 *Leichte Sprache*）。这些设置会跟随您的账户应用到每台设备。FleetPilot 支持纯键盘操作和屏幕阅读器。详情见 [accessibility.md](accessibility.md)。

---

## 2. 首页

起始页一眼看清所有内容的状态：服务和服务器地图、虚拟机与存储控制器、SMART 磁盘健康、环境、标签、最近的更新和快捷方式。

- **自定义**（Customize）可以让您显示、隐藏并重新排列卡片（拖动即可，也可以用键盘）。**保存布局**（Save Layout）按账户保存顺序；**恢复默认**（Reset to Default）可还原。
- 有新的 FleetPilot 版本可用时会出现横幅（管理员可以直接在那里安装）。

---

## 3. 服务器

### 主机管理

列出 FleetPilot 管理的所有服务器和 PC。

**添加主机**（Add a host，运维员和管理员）：填写

| 字段 | 含义 |
|---|---|
| 名称 | 简短且唯一的名称，例如 `nas` 或 `web-01` |
| 地址 | IP 地址或主机名 |
| 用户 / 端口 | SSH 用户和端口（22） |
| MAC 地址 | Wake-on-LAN 需要 |
| 分组、位置、环境、重要性、标签 | 用于排序和筛选（例如 *生产*、*实验室*、*高*） |
| 操作系统配置 | 机器上运行的系统：Linux 发行版、Windows、Proxmox 等。双系统 PC 可以有多个配置 |

然后在主机上点击 **安装密钥**（Install key）：FleetPilot 会向该机器索取一次密码，把自带的 SSH 密钥安装上去，但不保存这个密码。此后它都用该密钥登录。

**对单台主机**，您可以：

- 查看它是否在线（只在 SSH 端口上探测，不登录），
- **唤醒**（Wake）它（向 MAC 地址发送 Wake-on-LAN 魔术包），
- **关机**（Shut down）（Linux 和 Windows），
- 执行更新（见更新仪表盘），
- 为卡片上传图片，
- 编辑或删除它。

列表很长时，可以使用搜索框以及标签、分组和环境筛选器。顶部的两个按钮用于在卡片视图和紧凑表格视图之间切换。

**检测 IP 变化**（Detect IP changes）：如果机器通过 DHCP 获取地址，FleetPilot 可以把 MAC 地址与 ARP 表比对，并更新已变化的地址。

### 网络扫描

在网络范围（例如 `192.168.1.0/24`）中查找设备。输入范围后点击 **开始扫描**（Start Scan）。FleetPilot 会逐个地址发送 ping，并检查 SSH 端口是否开放，然后列出找到的设备。**添加主机**（Add Host）可以把某个结果直接变成受管主机，各项信息自动填好。只扫描您负责的网络。

### 路由器

路由器、中继器和接入点：FRITZ!Box 和 FRITZ!Repeater、OpenWrt（含 GL.iNet、Turris）、OPNsense、pfSense、VyOS、DD-WRT/FreshTomato、MikroTik RouterOS、IPFire 及其他 Linux 路由器，另外还可以对其他中继器或接入点做可用性检查。

- **添加设备**（Add device，管理员）：选择系统和角色（路由器、中继器、接入点），输入地址和凭据。OPNsense 使用 API 密钥和密钥值；FRITZ! 设备使用拥有 *FRITZ!Box 设置* 权限的 FRITZ! 用户；其他设备走 SSH。
- 详情页显示型号、固件、运行时长、负载、内存、接口、已连接设备、Wi-Fi 网络，以及（FRITZ!）互联网线路和 Mesh 信息。
- **检查更新**（Check for updates）显示是否有新固件。FleetPilot 从不安装路由器固件，因为升级失败可能让整个网络瘫痪。
- **配置备份**（Configuration backups，运维员）以加密方式保存；管理员可以下载。每台路由器保留最近 10 份。
- **重启路由器**（Restart router，管理员）必须输入路由器名称确认后才能执行。

凭据以加密方式保存。更多细节和各系统所需的权限：[routers.md](routers.md)。

### 更新仪表盘

集中查看所有受管主机的更新：

| 包管理器 | 发行版 |
|---|---|
| `apt` | Debian、Ubuntu、Linux Mint、Pop!_OS、Raspberry Pi OS、Kali、Zorin、Devuan 及其他 Debian/Ubuntu 衍生版、Proxmox VE |
| `dnf`（CentOS 7 和 Amazon Linux 2 上是 `yum`） | Fedora、RHEL、Rocky Linux、AlmaLinux、Oracle Linux、CentOS Stream、Amazon Linux |
| `zypper` | openSUSE Leap、SLES；Tumbleweed 和 Slowroll 使用 `zypper dup` |
| `pacman` | Arch、Manjaro、EndeavourOS、Garuda、Artix、CachyOS（会先刷新 keyring） |
| `apk`、`xbps`、`eopkg`、`swupd` | Alpine、Void、Solus、Clear Linux |
| Windows Update | Windows，完整更新时还会用 `winget` 更新应用程序 |

FleetPilot 根据 `/etc/os-release` 里的 `ID` 和 `ID_LIKE` 识别发行版，因此文档里没有列出的衍生版也能用。它以 root 身份登录，或使用不需要密码提示的 `sudo`（在 Alpine 上是 `doas`），遇到另一个正在运行的包管理器（unattended-upgrades、cloud-init）时会等待它结束，而不是直接失败。NixOS、Fedora Atomic/CoreOS、openSUSE MicroOS 等镜像型系统自行更新，FleetPilot 会直接说明这一点，而不去调用包管理器。

- 选中一台或多台主机后开始更新。**更新进度**（Update Progress）显示每台主机的实时输出。
- **更新历史**（Update History）列出每次运行的结果和耗时。
- **自动更新**（Automatic Updates）按计划执行更新（见[更新设置](#update-settings)）。

### 漏洞

您机器上软件中已知的安全漏洞（CVE），按严重程度排序，并给出修复每个漏洞的版本。

- **检查范围：**
  - **Linux 服务器：** FleetPilot 通过 SSH 读取已安装的软件包（`dpkg`、`apk` 或 `rpm`），再到发行版的安全数据中查询，数据来自 [OSV.dev](https://osv.dev)。覆盖 Debian、Ubuntu、Raspberry Pi OS、Proxmox VE 和 Backup Server、TrueNAS SCALE、Alpine、Rocky Linux 和 AlmaLinux。
  - **这些服务器上的 Docker 容器：** 如果服务器上装了 Trivy，FleetPilot 会用 [Trivy](https://trivy.dev) 扫描容器镜像。
  - **pfSense 和 OPNsense：** 使用它们自带的 `pkg audit`。
  - **FleetPilot 自身：** 它的 Python 软件包以及它所在的机器。
  - **未覆盖：** Windows、FRITZ!OS 和 OpenWrt 不公开软件包级数据。它们会被标为「未覆盖」，并说明可以改用哪些做法。
- **解读结果：**
  - **立即扫描**（Scan now，运维员和管理员）在后台扫描全部目标；**重新扫描**（Rescan）扫描单个目标。
  - 列表默认显示已有修复方案的高危和严重问题。调整筛选条件可以看到全部问题，包括发行版尚未修复的漏洞。
  - 大多数问题在更新后会消失。可以在「主机」或[更新仪表盘](#update-dashboard)中执行更新，然后重新扫描。
  - **每日扫描与告警：** 管理员可以开启每日扫描。当扫描发现新的、已有修复方案的高危或严重漏洞时，FleetPilot 会通知所有订阅了「新漏洞」的渠道（见[通知](#notifications)）。对某个目标的首次扫描作为基线，不发送告警。
  - **隐私：** 只把软件包名称和版本发送给 OSV.dev，绝不发送地址、主机名或其他数据。在离线模式（`FLEETPILOT_OFFLINE=true`）下不发送任何内容。`FLEETPILOT_OSV_URL` 可以让 FleetPilot 改用您自己的 OSV API 镜像。
  - **其他入口：** 结果也可以通过 `GET /api/vulnerabilities` 获取，或以 `fleetpilot_vulnerabilities*` 指标的形式出现在 `/metrics` 上；[安全中心](#security-center)会标出已有修复方案等待处理的严重漏洞。

### 服务器更新

（管理员）更新 FleetPilot 所在机器的操作系统软件包。**仅检查更新**（Check for Updates Only）列出待安装的软件包；**开始更新**（Start Update）安装它们并显示实时输出；**重启服务器**（Reboot Server）重启该机器。

---

## 4. 硬件

### 硬件概览

每台主机的硬件详情：CPU、内存、主板、磁盘、网卡、GPU 和传感器。**收集硬件信息**（Collect hardware info）通过 SSH 读取数据；**全部刷新**（Refresh all）更新所有主机。点击某台主机可查看完整报告。

### 硬件监控

实时查看每台服务器的温度、负载、内存、网络、磁盘 I/O 和风扇转速，并带历史图表。

- 用名称、地址和 SSH 用户**添加服务器**（Add server）。
- **安装配置**（Setup）检查每台服务器所需的工具（`lm-sensors`、`smartmontools`、`stress-ng`、`fio`），并安装缺少的工具。
- **压力测试**（CPU、内存、磁盘）有助于检验新硬件的散热和稳定性：**开始**（Start）、**停止**（Stop）或**开始全部测试**（Start all tests）。测试中发现的错误必须**确认**（acknowledged）后才能清除。
- **任务**（Tasks）列出正在运行和已完成的任务及其日志。

有人查看该页面时刷新会更快，无人查看时则放慢。

### SMART 健康

FleetPilot 已知的所有磁盘的健康状态：健康状态、温度、通电时长、重分配扇区和待定扇区。

- **活动磁盘告警**（Active Disk Alerts）列出需要关注的磁盘。**确认**（Ack）表示已知悉，该告警不再作为新告警显示。
- **立即巡检**（Poll Now）/ **巡检本地磁盘**（Poll Local Disks）读取最新的 SMART 数据；**从数据源导入磁盘**（Import Disks from Sources）从所有 SSH 主机、Proxmox 节点和 NAS 系统收集磁盘。
- **巡检配置**（Polling Configuration）设置自动读取 SMART 数据的频率。
- 点击某块磁盘可查看它的历史记录和属性趋势。

出现新问题时可以触发邮件和推送通知（见[邮件配置](#email-config)和[通知](#notifications)）。

### 存储与磁盘

磁盘工作区：每块磁盘及其 SMART 状态、正在运行的存储任务和远程系统。

- **磁盘概览**（Disk Overview）列出本地磁盘及其分区。
- **校验**（Validate）在整个磁盘上抽样读取数据块（不写入任何内容），并显示结果分布图，便于快速发现即将损坏或容量虚标的磁盘。
- **格式化**（Format，管理员）会擦除磁盘并创建 ext4、xfs 或 FAT32 文件系统。选择 *快速擦除*（移除分区和签名）或 *全零擦除*（覆盖每一个数据块，可能耗时数小时），然后输入 `ERASE /dev/<disk>` 解锁按钮。**这会销毁磁盘上的全部数据。** 系统盘和处于挂载状态的磁盘会被阻止。
- **远程管理**（Remote Management）可通过 SSH 对其他机器中的磁盘做同样的操作。
- **历史**（History）显示以往的操作和 SMART 导入记录；**SMART 导入**（SMART Import）可以接收 `smartctl -a` 报告文件。

对 FleetPilot 所在机器的磁盘操作，由一个精简的 root 辅助程序执行，它只接受这些特定操作。

### 风扇与散热

控制服务器和 PC 上的风扇。

| 控制器 | 用途 |
|---|---|
| lm-sensors（Linux PWM） | 主板风扇接口 |
| IPMI / ipmitool | 服务器 BMC（Supermicro、Dell iDRAC、HPE iLO 等） |
| nbfc-linux | 笔记本电脑 |
| liquidctl | NZXT、Aquacomputer、Corsair 等 USB 控制器 |
| Arctic Fan Controller | Arctic USB 风扇集线器 |
| PWM sysfs | 直接由内核控制 |
| Raspberry Pi PWM fan | GPIO 引脚上的三线风扇 |

**添加风扇控制器**（Add Fan Controller）：**自动检测控制器**（Auto-Detect Controllers）在主机上查找受支持的硬件；**使用此项**（Use This）采用某个检测结果。在设备页面上可以设置**固定转速**、使用**自动模式**，或套用**温度曲线**（按温度调转速）。**安装软件包**（Install Packages）安装控制器所需的工具。

**Commander Pro**（位于「风扇与散热」下）通过 SSH 和 liquidctl 控制一台远程 PC 上以 USB 连接的 Corsair Commander Pro。

---

## 5. 虚拟化与存储

### 虚拟机控制器

显示并控制 **Proxmox VE** 的虚拟机和容器，以及 **Veeam Backup & Replication 12** 的作业。

- **添加端点**（Add endpoint，管理员）：Proxmox 使用 8006 端口和 `root@pam`，或具有 *PVEAdmin* 角色的 API 用户（数据中心 → 权限 → 用户）；Veeam 使用 9419 端口，需启用 REST API。
- 详情页列出所有虚拟机和容器及其状态、CPU、内存和磁盘。运维员可以**启动**、**停止**、**重启**、**挂起**、**恢复**和**强制关闭**。
- **磁盘**（Disks）显示每个 Proxmox 节点的物理磁盘及其 SMART 状态。
- 对于 Veeam，显示备份作业及其最近的结果。

### 存储控制器

显示 **TrueNAS SCALE/CORE** 和 **Unraid 6.12+** 的存储池、卷、共享和磁盘。

- 用 API 密钥**添加端点**（Add endpoint）：TrueNAS 在 *系统 → API 密钥* 下，Unraid 在 *设置 → 管理访问 → API 密钥* 下。
- 详情页显示磁盘、ZFS 存储池、SMB/NFS/Unraid 共享和告警。**巡检磁盘**（Poll Disks）读取最新的磁盘数据。

### 备份服务器

监控 **Proxmox Backup Server**、**Duplicati**、**Restic REST server**、**BorgWarehouse**、**UrBackup**、**Bacula**（通过 SSH 调用 `bconsole`）以及任意**通用 SSH 备份**（由 FleetPilot 读取命令输出的方式）上的备份。

- 用类型、地址和凭据**添加服务器**（Add Server）；**测试**（Test）检查连接。
- 详情页显示数据存储、作业、快照和历史。**立即巡检**（Poll Now）刷新；在系统支持的情况下，运维员可以触发作业。
- 失败或缺失的备份会显示在首页，也可以作为通知发送。

---

## 6. 运维

### 定时关机

按计划关闭和启动主机，例如夜间关闭实验室服务器。

**添加计划**（Add Schedule）：选择主机、操作（*关机*、*重启*或*挂起*）、星期和时间。**立即执行**（Now）可马上运行一次计划。**最近活动**（Recent Activity）显示运行了哪些计划以及是否成功。要重新开机，请使用主机上的**唤醒**（Wake）（需在其 BIOS/UEFI 中启用 Wake-on-LAN）。

### CheckMK

把 FleetPilot 的数据送入 CheckMK（以及其他监控系统）。

- **API 令牌**（API Token）：监控系统使用的令牌。**重新生成**（Regenerate）会替换它，旧令牌随即失效。
- **配置说明**（Setup Instructions）提供四种方式：本地检查脚本、piggyback 脚本、数据源程序或 REST API。每种都附带可直接复制的脚本。
- **实时监控输出预览**（Live Agent Output Preview）显示 CheckMK 将收到的确切内容；**故障/严重磁盘**和**主机状态总览**显示当前状态。

同一个令牌也用于 [Prometheus](#9-integrations) 的身份验证。

### 系统监控

（管理员）FleetPilot 所在机器自身的 CPU、内存、磁盘、网络和温度，每 60 秒更新一次，历史最长 24 小时。

### FleetPilot 更新

（管理员）**仅检查更新**（Check for Updates Only）显示是否有新的 FleetPilot 版本以及有哪些变化；**拉取并更新 FleetPilot**（Pull & Update FleetPilot）安装更新并显示实时输出，然后重启 FleetPilot。您的数据和设置会保留。请先下载一份备份（见[备份](#backups)）。

---

## 7. 系统

### 更新设置

主机自动更新的规则：开关、频率（每天、每周、每月），以及是否发送通知和在仪表盘上显示更新提示。

### 邮件配置

SMTP 服务器、端口、加密方式、发件人和收件人。**发送测试邮件**（Send Test Email）检查设置是否可用。**报告配置**（Report Configuration）选择发送哪些报告（更新结果、SMART 告警、每日摘要）。SMTP 密码以加密方式保存。

### 代理服务

（管理员；带 HAProxy 的 Raspberry Pi）把内部 Web 服务发布在同一个地址下，例如 `/proxmox/` 或 `/unraid/`。添加一条路由分四步：唯一的公开路径、内部目标地址、健康检查路径，然后由 FleetPilot 应用。每次变更都会先校验，通过后 HAProxy 才重新加载；无效配置会自动回滚。**添加 Proxmox 路由**（Add Proxmox route(s)）可一步为 Proxmox 控制台创建路由。

### 生产状态

以就绪状态视角查看本次安装：运行模式、会话保护、反向代理信任、CSRF 防护、密钥、审计记录和身份就绪情况。它是一份运维检查清单，不是认证。

### 安全中心

（管理员）

- **检查项**：HTTPS、未开启两步验证的管理员、首次运行时遗留的密码文件、密钥文件权限、CSRF、调试模式、登录失败、备份新旧程度、永不过期的令牌和长期未使用的账户。每一项检查都会说明该怎么处理。
- **登录规则**：强制管理员使用两步验证、闲置超时、会话最长有效期、密码确认的有效时长、API 令牌最长有效期、账户锁定、审计保留期、允许登录的网络（只允许这些地址登录），以及用户在登录前必须接受的告知。
- 所有用户的**活动会话**和 **API 令牌**，每一项都可以*退出*或*吊销*。
- **最近的失败登录**。

### 通知

把磁盘告警、安全事件（锁定、新增管理员、设置变更、新增写入令牌）、路由器和备份事件推送到手机或团队聊天：**ntfy**、**Gotify**、**Discord**、**Slack/Mattermost** 以及通用的 **JSON webhook**。

**添加渠道**（Add a channel）：类型、URL（加密保存）、接收哪些类型的事件以及最低级别（info、warning、critical）。**测试**（Test）会发送一条测试消息。邮件在 *邮件配置* 中单独设置。

### 审计日志

只可追加的记录，涵盖登录和每一次变更：谁在什么时候、从哪个地址、以什么结果做了什么。密码、令牌、密钥、请求体和命令输出从不记录。

可以按事件、用户、结果、时间段或文本筛选，并导出为 CSV。记录用 HMAC 串成链，因此被修改或删除的条目可以被发现；安全中心会显示完整性检查的结果。事件还会以 JSON 形式写入系统日志，便于转发到 SIEM。

### 备份

（管理员）备份 FleetPilot 自身的数据：用户、主机、控制器设置、SMART 历史和密钥。

- **立即创建备份**（Create backup now）马上生成一份；每日备份会自动运行，保留最近 7 份。
- **下载**（Download）备份到别处保存。备份内含密码哈希和加密凭据，请妥善保管。
- **暂存恢复**（Stage restore）用于上传备份。FleetPilot 会校验其校验和，并在下次重启时应用，同时保留原有文件。

### 插件

用于扩展 FleetPilot。**已安装插件**（Installed plugins）列出已启用的插件及其使用的钩子点；**插件仓库**（Plugin Repository）列出可用插件；**编写自己的插件**（Write Your Own Plugin）打开开发者文档。

出于安全考虑，正常安装下的程序目录对 FleetPilot 是只读的。要添加插件，管理员需把插件文件复制到服务器上的 `/opt/fleetpilot/addons`，然后重启 FleetPilot。只安装您信任的插件：插件会以 FleetPilot 的权限运行。

---

## 8. 账户

### 我的资料

您的姓名、电子邮件地址和密码。新密码至少需要 12 个字符。

### 登录与安全

- **活动会话**：您登录过的每个浏览器和设备。**退出**（Sign out）结束其中一个；**退出其他所有会话**（Sign out all other sessions）结束除当前之外的全部会话。
- **最近登录**，含时间、地址和结果。
- 供脚本和集成使用的 **API 令牌**（见[集成](#9-integrations)）。
- 如果尚未设置两步验证，这里会有设置链接。

### 两步验证

即使密码被盗，也能保护您的账户。可选择一种或多种：

- **身份验证器应用**（TOTP）：用 Aegis、Google Authenticator 或 1Password 等应用扫描二维码，输入验证码，然后**验证并启用**（Verify & Enable）。
- **安全密钥或通行密钥**（WebAuthn）：YubiKey、Windows Hello、Touch ID 或手机。点击**注册安全密钥**（Register security key），然后触碰密钥。
- **备用码**：没有设备时使用的一次性验证码。**打印**（Print）或把它们保存到安全的地方；**重新生成备用码**（Regenerate Codes）会使旧码失效。

管理员可以在安全中心强制所有管理员使用两步验证。

### 无障碍

见「基础」中的[无障碍](#accessibility)。

### 用户管理

（管理员）**添加用户**（Add User）：填写姓名、电子邮件、密码和角色；编辑用户可修改角色或停用账户；**删除**（Delete）会移除该账户。请给每个人各自的账户：这样审计日志才能显示是谁做了什么。至少保留两个管理员账户，或者知道如何在服务器上[重置密码](installation.md#4-first-sign-in)。

---

## 9. 集成

### API 令牌与 REST API

在 **账户 → 登录与安全 → API 令牌**（Account → Sign-in & security → API tokens）下创建令牌：给它起个名字，选择 *只读* 或 *读写*，并设置到期日期。令牌只显示一次；FleetPilot 只保存它的哈希值。把它当作 bearer 令牌使用：

```bash
curl -H "Authorization: Bearer fp_..." https://fleetpilot.example/api/me
```

常用端点（均为 JSON）：`/api/me`、`/api/hosts`、`/api/vms`、`/api/smart/summary`、`/api/smart/disks`、`/api/routers`、`/api/backup/servers`、`/api/hw/live`、`/api/fans/devices`、`/api/vulnerabilities`、`/api/monitor/latest`、`/api/registry/servers`。使用读写令牌时还可以调用：`POST /api/hosts/<name>/wol` 和 `/shutdown`（运维员）、`/api/vms/<id>/action`（管理员）、`/api/fans/<id>/set_fan`（运维员）。令牌只对 `/api/` 地址有效，对网页一律无效；只读令牌用于读以外的任何操作都会被拒绝。

### 安卓应用（测试版）

适用于 Android 8.0 及更新版本的 FleetPilot 应用可以查看仪表盘、服务器、虚拟机、硬件监控和风扇，并能唤醒和关闭服务器、启动和停止虚拟机、设置风扇转速。从 [releases](https://github.com/ChristianHandy/FleetPilot/releases) 下载 APK（找 *Android app*）并安装；Android 会询问是否允许从浏览器或文件管理器安装应用。

1. 按上面的说明创建 API 令牌。*只读* 令牌只能查看；*读写* 令牌还会允许执行您角色许可的操作（运维员：唤醒、关机、风扇；管理员：还包括虚拟机）。
2. 打开应用，输入您的 FleetPilot 地址（例如 `https://192.168.1.62`）和令牌。
3. FleetPilot 使用自签名证书，Android 并不认识它。应用会显示证书的 SHA-256 指纹：把它与浏览器中显示的 FleetPilot 证书指纹对比，或在服务器上执行 `sudo openssl x509 -in /etc/fleetpilot/tls/fullchain.pem -noout -fingerprint -sha256` 后对比，然后点击**信任并登录**（Trust and sign in）。此后应用只接受这一张证书。

该应用需要 FleetPilot 1.7.1 或更高版本。要退出，点击右上角的箭头；如果手机丢失，请在 FleetPilot 中吊销令牌。

### Prometheus

`/metrics` 提供主机、SMART 健康、温度和通电时长、未关闭的告警、磁盘任务、路由器状态，以及 FleetPilot 所在机器的 CPU 和内存。用 CheckMK 页面上的令牌进行身份验证：

```yaml
scrape_configs:
  - job_name: fleetpilot
    scheme: https
    authorization:
      credentials: "<token from the CheckMK page>"
    static_configs:
      - targets: ["fleetpilot.example"]
```

### Home Assistant

用 Home Assistant 内置的 RESTful sensor 和只读 API 令牌读取 FleetPilot 的数据：

```yaml
rest:
  - resource: https://fleetpilot.example/api/smart/summary
    headers:
      Authorization: !secret fleetpilot_token   # "Bearer fp_..."
    sensor:
      - name: FleetPilot open disk alerts
        value_template: "{{ value_json.active_alerts }}"
```

仓库里还包含一个独立的自定义集成 `integrations/home-assistant/custom_components/smart_monitor`，它直接通过 SSH 从您的机器读取 SMART 数据。

### 公开状态页

`/status` 无需登录即可显示已发布的服务和受管主机的名称及其状态，适合挂在墙上展示或提供给普通用户。它不显示地址或其他细节；如果主机名属于机密信息，请不要对外暴露此页面。

---

## 10. 安全须知

- 如果 FleetPilot 的访问者不止您一个人，请使用带受信任证书的 HTTPS；见[安装指南](installation.md#6-https-and-your-own-certificate)。
- 开启两步验证，至少对管理员开启。
- 给每个人分配各自的账户，并只授予其所需的最小角色。
- 不要把 FleetPilot 直接暴露在公网上。请使用 VPN（WireGuard、Tailscale），或在安全中心限制 *允许的网络*。
- FleetPilot 用 `.env` 中的密钥加密保存设备密码和 API 凭据。请像保护密码一样保护备份和 `.env` 文件。
- 受监管环境或物理隔离网络：见[高安全环境](installation.md#10-high-security-sites)和 [SECURITY.md](../SECURITY.md)。
- 如需私下报告安全问题，请按 [SECURITY.md](../SECURITY.md) 中的说明操作。

---

## 11. 常见问题

**FleetPilot 需要在服务器上装代理程序吗？** 不需要。它使用 SSH 和各系统自带的 API。

**FleetPilot 在我的服务器上应该用哪个用户？** 最稳妥的做法是使用一个专用用户，配置好您的 SSH 密钥，并给它包管理器和 `smartctl` 的 sudo 权限。用 `root` 也可以。

**主机显示离线，但其实能用。** FleetPilot 检查的是 SSH 端口。请检查主机设置中的端口，以及 FleetPilot 与主机之间的防火墙。

**可以管理 Windows PC 和服务器吗？** 可以，涵盖微软仍在支持的所有版本：
- Windows 10 和 11，包括 LTSC 2019、2021、2024 以及 IoT 版本
- Windows Server 2016 至 2025，包括 Server Core

启用 OpenSSH 服务器，用管理员账户添加主机，然后点击**检测系统**（Detect OS）。FleetPilot 随后会显示版本及其支持终止日期。它会安装 Windows 更新（不重启），并在已安装的情况下通过 winget 更新应用程序。关机、Wake-on-LAN、硬件概览和 SMART（配合 smartmontools）同样可用。各版本的配置说明：[WINDOWS_SUPPORT.md](../WINDOWS_SUPPORT.md)。

**两个 FleetPilot 实例可以互相备份吗？** 可以：数据同步会把主实例的全部数据复制到从实例。在两边设置相同的 `SYNC_TOKEN`。

**我的数据在哪里？** 在 FleetPilot 所在机器的 `/opt/fleetpilot/data` 中。不会向任何其他地方发送数据；检查更新会访问 GitHub，设置 `FLEETPILOT_OFFLINE=true` 可将其关闭。

**我忘了管理员密码。** 在 FleetPilot 机器上运行 `sudo bash /opt/fleetpilot/reset-password.sh`。
  
