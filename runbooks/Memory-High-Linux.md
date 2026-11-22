# Memory usage high on a Linux server
Platform: linux
Alarm Match: Memory-High, Mem-High, mem_used_percent, memory high on a Linux server
Issue Type: Memory high
Escalation Team: L2 Support
Diagnosis Steps: Run health_check and top_cpu_processes (it also shows memory per process). Identify whether one process or one managed service uses most of the memory.
Remediation Steps: If a managed service (nginx, httpd, crond) is using the memory, use restart_service on that service. If one runaway process is using it, use kill_process with the PID and name shown. Run health_check again. If memory is normal, resolve. If memory stays high, or no single process explains it, escalate to L2.
Approval Required: Yes. kill_process always needs approval. restart_service runs without approval only in dev.
