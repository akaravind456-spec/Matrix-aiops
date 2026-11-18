# Lambda environment variables (names only, never commit real values)

If you deploy with `infra/matrix-app.yaml`, you type these as stack parameters and CloudFormation sets the variables for you
(`SnBase`=SN_BASE, `LlmApiKey`=OPENAI_API_KEY, `Fb1Key`=LLM_FALLBACK_KEY, and so on). This list is for reference, or for setting
them by hand in Lambda, Configuration, Environment variables. Copy real values from the source account's Lambda
into a private note, not into this repo.

## Core
`AWS_REGION` · `TOKEN_SECRET` (new random value) · `USERS` · `ALLOWED_ORIGIN` (the S3 website URL) · `LEAD_ROLES` · `SERVICES` · `INGEST_URL` · `KB_NAME` · `EVAL_HOST` · `CLOSE_CODE`

## LLM (OpenAI-compatible, Bearer auth)
| Slot | Variables |
|---|---|
| Primary (NVIDIA) | `OPENAI_URL=https://integrate.api.nvidia.com/v1/chat/completions` · `OPENAI_API_KEY` · `OPENAI_MODEL` (exact ID from the model page) |
| Small talk | `LLM_SMALL_MODEL` (same provider and key as primary) |
| Same-key backups | `LLM_EXTRA_MODELS` (comma list) |
| Standby 1 (Groq) | `LLM_FALLBACK_URL=https://api.groq.com/openai/v1/chat/completions` · `LLM_FALLBACK_KEY` · `LLM_FALLBACK_MODEL` |
| Standby 2 (Gemini) | `LLM_FALLBACK_URL_2=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` · `LLM_FALLBACK_KEY_2` · `LLM_FALLBACK_MODEL_2` |
| Standby 3 (OpenRouter) | `LLM_FALLBACK_URL_3=https://openrouter.ai/api/v1/chat/completions` · `LLM_FALLBACK_KEY_3` · `LLM_FALLBACK_MODEL_3` |
| Prices (optional) | `LLM_PRICE_IN_PER_M` · `LLM_PRICE_OUT_PER_M` |

All chosen models must support tool calling. A slot needs both a key and a model to count.
A rejected key (401/403) on one slot parks that slot for 10 minutes and the next slot is tried.

## Console features
`KB_NAME` (ServiceNow knowledge base that SOPs and runbooks uploaded in the console go to; it must already exist; default `AI SRE Runbooks`) ·
`LLM_PRICES` (optional JSON, US dollars per 1M tokens, for the Dashboard's LLM cost, for example `{"openai/gpt-oss-120b":{"in":0.15,"out":0.60}}`; a key ending in `*` matches a prefix).
Built-in defaults: NVIDIA models (`nvidia/*`) are free, and two Groq models have list prices. A model with no price shows "price not set", never $0.00.
The ServiceNow integration user needs a knowledge role (for example `knowledge_admin`, or a role that can create and publish in that knowledge base) for uploads and learning approvals to reach ServiceNow.

## ServiceNow
`SN_BASE` (https://devXXXXXX.service-now.com, no trailing slash) · `SN_USER` · `SN_PASS` · `SN_AI_USER` · `SN_AI_GROUP` · `SN_L2_GROUP` · `SN_L3_GROUP`
(`SNOW_URL/USER/PASS` are filled from the SN_ ones automatically.)
Change defaults: `CHANGE_GROUP` · `CHANGE_TYPE` · `CHANGE_HOURS`

## AWS operations
`EXECUTOR_ROLE_ARN` · `INSTANCE_PROFILE` · `SUBNET_ID` · `SECURITY_GROUP_ID` · `AUDIT_LOG_GROUP` · `ENVIRONMENT` (dev|test|prod) · `MAX_VCPU` · `OPS_BUCKET` · `TRACE_TABLE` · `TF_PROJECT` · `PLAYBOOKS` · `TF_MODULES` · `ALLOWED_TYPES` · `OPERATOR_ROLE_ARN` · `COST_TAG_KEY`

New: `DECOM_HOLD_DAYS` (default 7) · `DECOMMISSION_ROLE_ARN` (only if the optional role is enabled)

## Agent and learning
`AGENT_KEY` (new random value) · `L1_GROUP` · `L2_GROUP` · `AUTO_AFTER` · `FAMILIES` · `RAG_MIN` · `RAG_REQUIRED` · `LEARN_LOOKBACK_DAYS` · `LEARN_MAX_PER_RUN` · `LEARN_SELF_APPROVE`
