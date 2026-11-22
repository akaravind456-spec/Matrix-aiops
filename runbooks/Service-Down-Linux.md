# Service stopped or not responding on a Linux server
Platform: linux
Alarm Match: Service-Down, Service-Failed, nginx down, httpd down, crond down, amazon-cloudwatch-agent stopped, service not running
Issue Type: Service down
Escalation Team: L2 Support
Diagnosis Steps: Run service_status for the service named in the alarm, then health_check. Note whether the service is inactive or failed, and read the last lines of its status.
Remediation Steps: Only for the managed services nginx, httpd, crond and amazon-cloudwatch-agent: use restart_service. Run service_status again. If it is active, resolve. If it fails to start again, or the error points at configuration (for example a bad nginx config), escalate to L2 with the error text. Do not change configuration files.
Approval Required: Yes in test and production. restart_service runs without approval only in dev.
