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
