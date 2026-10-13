"""The demo homelab: which machines, appliances and gadgets exist (RFC 5737 addresses only)."""
from .machines import Device, Disk, Machine
from .net import lab
from .services import BackupServer, Fritz, Guest, OpenWrt, OpnSense, ProxmoxCluster, ProxmoxNode, TrueNas

DEBIAN_UPDATES = [("openssl", "3.5.1-1", "3.5.4-1~deb13u2"), ("curl", "8.14.1-2", "8.14.1-2+deb13u2"),
                  ("docker-ce", "5:28.4.0-1~debian.13~trixie", "5:28.5.1-1~debian.13~trixie"),
                  ("containerd.io", "1.7.27-1", "1.7.28-1"), ("tzdata", "2025b-4", "2025c-1")]
UBUNTU_UPDATES = [("nginx", "1.24.0-2ubuntu7.1", "1.24.0-2ubuntu7.5"),
                  ("openssl", "3.0.13-0ubuntu3.4", "3.0.13-0ubuntu3.6"),
                  ("linux-image-6.8.0-85-generic", "6.8.0-85.85", "6.8.0-87.88")]
WINGET_UPDATES = [("Mozilla Firefox", "143.0.4", "144.0"), ("7-Zip", "24.09", "25.01"),
                  ("Microsoft PowerToys", "0.94.2", "0.95.0")]

CLIENTS = [("phone-anna", 101, "Wi-Fi", ()), ("laptop", 102, "Wi-Fi", (22,)), ("tv", 103, "LAN", (8008,)),
           ("printer", 104, "Wi-Fi", (80, 631)), ("tablet", 106, "Wi-Fi", ()), ("smart-plug", 107, "Wi-Fi", (80,))]


def build():
    """Create every device of the lab and return the FleetPilot machine."""
    fleetpilot = lab.add(Machine("fleetpilot", "192.0.2.5", "bc:24:11:5e:00:05", os="debian", cores=2, ram_mb=2048,
                                 base_load=6, fans=0, virt="lxc", label="FleetPilot (this demo)",
                                 kernel="6.14.11-3-pve", board=("Proxmox", "LXC container")))
    lab.self_machine = fleetpilot

    pve1 = lab.add(ProxmoxNode("pve-01", "192.0.2.10", "a8:a1:59:10:00:10", cores=12, ram_mb=65536, base_load=22,
                               cpu="AMD Ryzen 9 5900X 12-Core Processor", board=("ASRock Rack", "X570D4U"),
                               disks=[Disk("nvme0n1", "Samsung SSD 980 PRO 2TB", "S69ENF0R100201", 2000, temp=38,
                                           poh=9120, nvme=True),
                                      Disk("sda", "WDC WD40EFZX-68AWUN0", "WD-WX12A3456701", 4000, temp=37, poh=21544),
                                      Disk("sdb", "WDC WD40EFZX-68AWUN0", "WD-WX12A3456702", 4000, temp=38, poh=21540)],
                               updates=[("pve-manager", "9.0.10", "9.0.11"), ("proxmox-kernel-6.14", "6.14.11-3",
                                                                              "6.14.11-4")]))
    pve2 = lab.add(ProxmoxNode("pve-02", "192.0.2.11", "a8:a1:59:10:00:11", cores=8, ram_mb=32768, base_load=14,
                               cpu="Intel(R) Core(TM) i5-12500", board=("Fujitsu", "D3644-B1"),
                               disks=[Disk("nvme0n1", "WD Red SN700 1000GB", "22471E801234", 1000, temp=41,
                                           poh=12001, nvme=True),
                                      Disk("sda", "ST8000VN004-3CP101", "WRQ0A1B2", 8000, temp=41, poh=30211,
                                           realloc=24)]))
    guests = [Guest(100, "docker-01", "qemu", "pve-01", 4, 8, 64, load=18, tags="services"),
              Guest(101, "home-assistant", "qemu", "pve-01", 2, 4, 32, load=6, tags="smart-home"),
              Guest(102, "fleetpilot", "lxc", "pve-01", 2, 2, 8, load=4, tags="monitoring"),
              Guest(103, "win11-test", "qemu", "pve-01", 4, 8, 80, running=False, tags="lab"),
              Guest(105, "nextcloud", "lxc", "pve-02", 2, 4, 40, load=9, tags="services"),
              Guest(106, "jellyfin", "lxc", "pve-02", 4, 4, 24, load=25, tags="media"),
              Guest(107, "gitea", "lxc", "pve-02", 1, 2, 16, load=3, tags="dev"),
              Guest(108, "k3s-node", "qemu", "pve-02", 4, 8, 64, running=False, tags="lab")]
    ProxmoxCluster([pve1, pve2], guests)

    lab.add(TrueNas("nas", "192.0.2.20", "3c:ec:ef:20:00:20", os="debian", cores=8, ram_mb=65536, base_load=9,
                    cpu="Intel(R) Atom(TM) CPU C3758 @ 2.20GHz", board=("iXsystems", "TrueNAS Mini X+"),
                    disks=[Disk("sda", "TOSHIBA MG08ACA16TE", "Z1F0A001", 16000, temp=35, poh=14290),
                           Disk("sdb", "TOSHIBA MG08ACA16TE", "Z1F0A002", 16000, temp=36, poh=14288),
                           Disk("sdc", "TOSHIBA MG08ACA16TE", "Z1F0A003", 16000, temp=36, poh=14291),
                           Disk("sdd", "TOSHIBA MG08ACA16TE", "Z1F0A004", 16000, temp=35, poh=14287),
                           Disk("nvme0n1", "KINGSTON SNV2S250G", "50026B7686A1", 250, temp=39, poh=14300,
                                nvme=True)]))
    docker = lab.add(Machine("docker-01", "192.0.2.30", "bc:24:11:30:00:30", os="debian", cores=4, ram_mb=8192,
                             base_load=18, virt="kvm", board=("QEMU", "Standard PC (Q35 + ICH9, 2009)"),
                             disks=[], updates=DEBIAN_UPDATES, label="docker-01"))
    docker.containers = [("reverse-proxy", "nginx:1.27.0"), ("nextcloud", "nextcloud:29.0.4-apache")]
    docker.trivy = True
    lab.add(Machine("web-01", "192.0.2.31", "52:54:00:31:00:31", os="ubuntu", cores=2, ram_mb=4096, base_load=8,
                    virt="kvm", kernel="6.8.0-85-generic", board=("Hetzner", "vServer"), fans=0,
                    updates=UBUNTU_UPDATES))
    lab.add(Machine("pihole", "192.0.2.53", "d8:3a:dd:53:00:53", os="raspbian", cores=4, ram_mb=8192, base_load=4,
                    cpu="Cortex-A76", kernel="6.12.34+rpt-rpi-2712", board=("Raspberry Pi", "Pi 5 Model B Rev 1.0"),
                    fans=1, disks=[Disk("nvme0n1", "Samsung SSD 990 EVO 1TB", "S7GCNU0X50053", 1000, temp=42,
                                        poh=3021, nvme=True)],
                    updates=[("pihole-ftl", "6.2.3", "6.3"), ("openssh", "1:9.2p1-2+deb12u3",
                                                              "1:9.2p1-2+deb12u7")], ports=(22, 80, 53)))
    lab.add(BackupServer("backup", "192.0.2.40", "a8:a1:59:40:00:40", cores=4, ram_mb=16384, base_load=5,
                         cpu="Intel(R) Xeon(R) E-2224 CPU @ 3.40GHz",
                         clients=[("vm", "100"), ("vm", "101"), ("ct", "102"), ("ct", "105"), ("ct", "106"),
                                  ("ct", "107")],
                         disks=[Disk("sda", "ST8000VN004-3CP101", "WRQ0B771", 8000, temp=34, poh=16010),
                                Disk("sdb", "ST8000VN004-3CP101", "WRQ0B772", 8000, temp=35, poh=16008)]))
    lab_box = lab.add(Machine("lab-01", "192.0.2.60", "1c:69:7a:60:00:60", os="fedora", cores=8, ram_mb=16384,
                              base_load=10, kernel="6.16.10-200.fc42.x86_64", cpu="Intel(R) Core(TM) i7-8700",
                              board=("Dell Inc.", "OptiPlex 7070"),
                              disks=[Disk("sda", "Samsung SSD 870 EVO 500GB", "S6PNNM0T6001", 500, temp=31, poh=6120)],
                              updates=[("kernel", "6.16.10-200.fc42", "6.17.1-200.fc42"),
                                       ("firefox", "143.0.4-1.fc42", "144.0-1.fc42")]))
    lab_box.power_off("is switched off (wake it with Wake-on-LAN)")
    lab.add(Machine("win-desk", "192.0.2.70", "18:c0:4d:70:00:70", os="windows", pretty="Windows 11 Pro 24H2",
                    cores=8, ram_mb=32768, base_load=7, fans=0, cpu="AMD Ryzen 7 7700", updates=WINGET_UPDATES,
                    board=("ASUSTeK", "TUF GAMING B650-PLUS")))

    spare = lab.add(Machine("media-01", "192.0.2.32", "bc:24:11:32:00:32", os="ubuntu", cores=4, ram_mb=8192,
                            base_load=11, virt="kvm", kernel="6.8.0-85-generic", fans=0,
                            updates=UBUNTU_UPDATES[:2], label="media-01 (not in FleetPilot yet)"))
    spare.hint = "Find it with Network Scanner and add it"

    clients = [{"ip": f"192.0.2.{n}", "mac": f"aa:bb:cc:00:00:{n:02x}", "hostname": name, "connection": conn}
               for name, n, conn, _ in CLIENTS]
    for name, n, conn, ports in CLIENTS:
        gadget = lab.add(Device(name, f"192.0.2.{n}", f"aa:bb:cc:00:00:{n:02x}", ports=ports))
        gadget.kind, gadget.icon, gadget.listed = "client", "phone", False
    repeater = Fritz("Repeater upstairs", "192.0.2.2", "2c:91:ab:02:00:02", "FRITZ!Repeater 3000 AX",
                     repeater=True, clients=clients[:2], wan=False)
    repeater.dns_name = "fritz.repeater"
    box = Fritz("FRITZ!Box", "192.0.2.1", "2c:91:ab:01:00:01", "FRITZ!Box 7590 AX", clients=clients,
                mesh=[repeater], dns_name="fritz.box")
    lab.add(box)
    lab.add(repeater)
    lab.add(OpenWrt("GL.iNet travel router", "192.0.2.3", "94:83:c4:03:00:03", "GL.iNet GL-MT6000",
                    clients=clients[2:5], dns_name="openwrt"))
    lab.add(OpnSense("OPNsense", "192.0.2.254", "00:0d:b9:fe:00:fe", clients=clients, dns_name="opnsense"))
    return fleetpilot
