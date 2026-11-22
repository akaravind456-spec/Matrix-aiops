# CPU usage high on a Windows server
Platform: windows
Alarm Match: CPU-High-Windows, Cpu-hig windows, CPUUtilization high on a Windows server
Issue Type: CPU high
Escalation Team: L2 Support
Diagnosis Steps: Run health_check and top_cpu_processes. Find one process that uses most of the CPU and check that it is not a protected system process (lsass, csrss, services, winlogon, System).
Remediation Steps: If one runaway process is the cause, use kill_process with the exact PID and name from top_cpu_processes. Run top_cpu_processes again. If CPU is normal, resolve. If CPU stays high or the process is protected, escalate to L2.
Approval Required: Yes. kill_process always needs approval.
