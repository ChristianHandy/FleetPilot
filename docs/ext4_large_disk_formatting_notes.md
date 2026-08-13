# Ext4 formatting on large USB disks

## Observed behavior

On 2026-08-13, FleetPilot's first quick-format test on the authorized 16 TB USB drive `/dev/sdb` successfully cleared signatures but failed during raw-device ext4 creation with:

```text
Creating journal (262144 blocks): mkfs.ext4: Invalid argument
while trying to create journal
```

The drive reports 512-byte logical sectors, 4096-byte physical sectors, and 16.0 TB capacity. It is connected through USB and has no active mounts.

## Implementation decision

FleetPilot's local Disk Tools helper will create a GPT partition table, create one data partition covering the disk, wait for the kernel to expose the partition, and format that partition rather than formatting the raw disk device.

This follows standard Linux disk management practice: create the filesystem on a partition for a whole disk rather than using the raw disk directly. The resulting ext4 command will force the `64bit` ext4 feature for the large volume.

## References

1. Unix & Linux Stack Exchange, “mkfs.ext4: Invalid argument on raspberry pi” — https://unix.stackexchange.com/questions/710745/mkfs-ext4-invalid-argument-on-raspberry-pi
2. `mke2fs(8)` manual — https://man7.org/linux/man-pages/man8/mke2fs.8.html

The mke2fs manual documents `-O 64bit` as an ext4 feature selection mechanism and explains that filesystems are normally created on devices or partitions.
