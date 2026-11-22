# Server unreachable, status check failed or hardware problem
Platform: linux
Alarm Match: StatusCheckFailed, instance unreachable, host down, no heartbeat, network unreachable, hardware failure
Issue Type: Server unreachable
Escalation Team: L2 Support
Diagnosis Steps: Run check_alarms and cmdb_lookup. If the agent cannot reach the server through Systems Manager, record that.
Remediation Steps: None of the agent's fixes (restart_service, clear_old_logs, kill_process) applies when the server is unreachable or the problem is hardware or network. Escalate to L2 at once with the alarm name, the time and what could not be reached.
Approval Required: Not applicable. This runbook always hands over to L2.
