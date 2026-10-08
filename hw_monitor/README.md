# HW Monitor stress-test script

The hardware monitor itself is built into FleetPilot (**Hardware → System monitor / HW Monitor**,
code in `hw_monitor.py`). This folder only holds `hw_stress_test.py`, the script FleetPilot
starts on a monitored server when you run a stress test.

The earlier standalone HW Monitor dashboard that lived here had no login and has been removed;
use the FleetPilot pages instead.

## Deploy the script to a monitored server

```bash
# As root on each server
mkdir -p /root/hw_stress_test
scp hw_stress_test.py root@<server>:/root/hw_stress_test.py
```

FleetPilot expects it at `/root/hw_stress_test.py` and writes the log to
`/root/hw_stress_test/stress_test.log` (both can be changed per server).

## Run it by hand

```bash
nohup python3 /root/hw_stress_test.py > /root/hw_stress_test/stress_test.log 2>&1 &
python3 /root/hw_stress_test.py --report   # summary after a run
```

## Packages on monitored servers

| Package | Purpose | Required |
|---|---|---|
| `stress-ng` | CPU/RAM/I/O stress tests | Yes (for tests) |
| `fio` | Disk I/O benchmarks | Yes (for tests) |
| `lm-sensors` | Temperature sensors | Recommended |
| `fancontrol` | PWM fan control | Optional |
| `i2c-tools` | I2C hardware sensors | Optional |
| `nvidia-smi` | NVIDIA GPU monitoring | Optional |

The **Setup** page in FleetPilot can check for and install these packages.
