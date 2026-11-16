"""Entry point. console_api.py is your original console file, unchanged. The add-ons extend it in place."""
import console_api as base
import gateway, aiops, autonomy, rag, awsops, metrics, learning
import matrix_sre_install
import matrix_cost_action

g = vars(base)
gateway.install(g)      # first, so tracing records the model that really answered
aiops.install(g)
autonomy.install(g)
rag.install(g)
awsops.install(g)
metrics.install(g)
g['ACTIONS']['gateway'] = gateway.a_gateway   # shows every standby slot, including ones on the same provider
matrix_sre_install.install(g)
matrix_cost_action.install(g)
learning.install(g)     # last: it wraps the agent run and the dashboard

_console = base.handler


def handler(event, context):
    # EventBridge schedule: {"matrix_task": "learn_scan"} starts the automatic learning scan
    if isinstance(event, dict) and event.get('matrix_task') == 'learn_scan':
        return learning.scan_event()
    return _console(event, context)
