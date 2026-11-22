# Disk usage high on a Windows server
Platform: windows
Alarm Match: Disk-High-Windows, LogicalDisk free space low, disk space high on a Windows server
Issue Type: Disk space high
Escalation Team: L2 Support
Diagnosis Steps: Run health_check and disk_usage and confirm which drive is above the threshold.
Remediation Steps: The agent has no automatic cleanup for Windows disks. Escalate to L2 with the drive, the current usage and the threshold, so a person can decide what to remove.
Approval Required: Not applicable. This runbook always hands over to L2.
