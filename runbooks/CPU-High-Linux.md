# CPU usage high on a Linux server
Platform: linux
Alarm Match: CPU-High, Cpu-hig, CPU-HIGH, MATRIX-LNX01-CPU-HIGH, CPUUtilization high on a Linux server
Issue Type: CPU high
Escalation Team: L2 Support
Diagnosis Steps: Run health_check and top_cpu_processes. Find one process that uses most of the CPU. Check that it is not a protected system process (systemd, sshd, the SSM agent, cron, the CloudWatch agent).
Remediation Steps: If a single runaway process (for example a stuck "yes" or a loop) uses most of the CPU, use kill_process with the exact PID and name from top_cpu_processes. If the busy process is a managed service (nginx, httpd), use restart_service instead. Run top_cpu_processes again. If CPU is normal, resolve. If CPU stays high, or the process is a protected one, escalate to L2.
Approval Required: Yes. kill_process always needs approval. restart_service runs without approval only in dev.
