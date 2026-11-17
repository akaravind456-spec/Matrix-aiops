# MATRIX AIOps

Autonomous SRE agent for AWS and ServiceNow: a Python Lambda (chat agent, L1 auto-remediation, learning loop) with an S3-hosted console.

```
lambda/     Lambda code. Entry point: lambda_function.py (handler: lambda_function.handler)
infra/      CloudFormation: DynamoDB tables, scoped executor role, SSM playbooks, S3 site
frontend/   matrix-ui.html (the console). old/ holds an earlier copy
docs/       deployment-guide.md, tool-catalog.md, env-template.md
tests/      offline unit tests (python -m unittest discover -s tests -v)
```

Operations tools: patching, migration, deployment, decommission and ServiceNow. See `docs/tool-catalog.md`.
Moving to a new AWS account: `docs/deployment-guide.md`. Settings: `docs/env-template.md`.

Never commit secrets (API keys, ServiceNow passwords, tokens). They live in the Lambda's environment variables.
