# Web errors (404 or 5xx) on a server running nginx or httpd
Platform: linux
Alarm Match: 404, 5xx, HTTP 404 error, HTTP 500 error, web error, endpoint not found, nginx error
Issue Type: Web error
Escalation Team: L2 Support
Diagnosis Steps: Run service_status for nginx (or httpd), health_check, and check_alarms. A 404 or 5xx is usually an application or configuration problem and not a server fault.
Remediation Steps: If the web service is inactive or failed, use restart_service and check service_status again. If the service is running and healthy, do not change anything: escalate to L2 and state that the server is healthy and the error is in the application or web configuration.
Approval Required: Yes in test and production for restart_service. Escalation needs no approval.
