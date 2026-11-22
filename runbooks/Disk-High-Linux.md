# Disk usage high on a Linux server
Platform: linux
Alarm Match: Disk-High-matrix-linux-01, Disk-High-matrix-linux-02, Disk-High, disk_used_percent, disk space high on a Linux server
Issue Type: Disk space high
Escalation Team: L2 Support
Diagnosis Steps: Run health_check, then disk_usage and check_alarms. Confirm the root filesystem is above the alarm threshold and that CPU and memory are normal.
Remediation Steps: Use clear_old_logs (deletes rotated logs older than 7 days under /var/log). Run disk_usage again. If usage is back under the alarm threshold, resolve the incident. If usage is still above the threshold, or the disk is growing quickly, escalate to L2 and say what is using the space.
Approval Required: Yes in test and production. clear_old_logs runs without approval only in dev.
