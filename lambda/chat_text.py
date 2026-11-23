"""Plain-language text the chat shows when it has to stop. Kept in its own file so it can be tested without the whole Lambda."""
import re


def step_limit_reply(tried, has_pending):
    """Say what happened when the step limit is reached, instead of a vague message. tried = [(tool_name, result_text), ...]."""
    names = list(dict.fromkeys(n.replace('_', ' ') for n, _ in tried))
    fails = [(n, o) for n, o in tried if str(o).lstrip().lower().startswith(('error', 'failed', 'not created', 'refused', 'ticket_', 'servicenow_'))]
    text = 'I ran out of steps before I could finish this request. '
    if names:
        text += 'I tried: %s. ' % ', '.join(names[:6])
    if fails:
        n, o = fails[-1]
        text += 'The last problem was in %s: %s. ' % (n.replace('_', ' '), re.sub(r'\s+', ' ', str(o))[:160])
    text += ('Check the confirmation buttons below, then tell me what to do next.' if has_pending
             else 'Tell me which part to continue with, for example "just create the ticket" or "just deploy it".')
    return text


import re as _re

_WAIT_RX = _re.compile(r'(waiting|wait|need|needs|press|click|awaiting)[^.\n]{0,60}confirm|confirm(ation)?[^.\n]{0,40}(button|console|waiting|pending)', _re.I)


def claims_waiting_for_confirm(text):
    """True when the reply says an action is waiting for the Confirm button."""
    return bool(_WAIT_RX.search(str(text or '')))


NUDGE = ('SYSTEM CHECK: your reply says an action is waiting for the engineer to press Confirm, but nothing was queued in this turn, '
         'so no Confirm button exists. Answer ONLY the latest message from the engineer. If the latest message asks for a change, call the tool now '
         'so the button appears. If it asks about something else, answer that and do not mention any earlier action. '
         'An older Confirm button from an earlier turn may still be on screen; never repeat that action unless the latest message asks for it.')

NO_BUTTON = ('There is no Confirm button open right now, so nothing is waiting. Tell me which step to do next '
             '(for example "launch the clone" or "close the ticket") and I will queue it.')
