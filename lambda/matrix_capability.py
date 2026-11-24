"""Fixed, complete answer for "what can you do / what tools do you have" so the model cannot give a thin or wrong one."""
import re

CAPABILITY_REPLY = (
    "I am MATRIX, your L1 engineer for AWS servers and ServiceNow. Here is what I can do.\n\n"
    "**Look and diagnose (runs straight away)**\n"
    "- Server health: CPU, memory, disk, services, top processes, alarms\n"
    "- Read your AWS estate: servers, volumes, snapshots, S3, costs, activity\n"
    "- Search runbooks and past incidents, and read ServiceNow tickets, changes and the CMDB\n\n"
    "**Fix and change (you press Confirm first)**\n"
    "- Restart, start or stop a service, kill a process, clear old logs\n"
    "- Reboot, start or stop a server\n"
    "- Raise, assign, approve, reject or resolve incidents; open changes and add work notes\n\n"
    "**Planned work (step by step, with a change ticket)**\n"
    "- Patching: scan for missing patches, then install\n"
    "- Deploy a new server from a plan\n"
    "- Migrate a server: image, clone, validate, cut over, roll back\n"
    "- Decommission: assess, final backup, stop with a 7-day hold (terminate needs a human tag)\n\n"
    "**How I stay safe**\n"
    "- I only touch servers tagged `matrix-managed=true` in the right environment\n"
    "- Anything that changes something needs your Confirm; production also needs approval\n"
    "- I never invent results: I run the tool first, and a failed action never closes a ticket\n"
    "- Protected processes are off limits, and there is a kill switch to stop me at once\n\n"
    "Tell me a server name and what you need, for example: *check disk on matrix-linux-01*."
)
_CAP_RX = re.compile(r"(what\s+(all\s+)?(are\s+)?(the\s+)?(tools|features|functionalit\w*|capabilit\w*)|what\s+(all\s+)?(can|do)\s+(you|u)\s+(do|have)|what\s+you\s+can\s+do|what\s+are\s+you\s+able|how\s+can\s+you\s+help|guard\s?rails?)", re.I)


def capability_question(text):
    t = str(text or '').strip()
    return bool(t) and len(t) <= 400 and not re.search(r'\b(INC|CHG)\d+|matrix-|\bi-[0-9a-f]{6,}', t, re.I) and bool(_CAP_RX.search(t))


