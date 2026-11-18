"""CHANGE_MODE switch. For a ServiceNow instance that has no Change module (for example a developer instance).

  CHANGE_MODE=change    (default) planned work needs a CHG number that is approved and scheduled
  CHANGE_MODE=incident  planned work is tracked on an INC instead: MATRIX creates the incident, and the gates accept an open INC.
                        The engineer pressing Confirm in the console stays the approval for every change.
"""
import os


def incident_mode():
    return os.environ.get('CHANGE_MODE', 'change').strip().lower() == 'incident'


def number_regex():
    return r'(CHG|INC)\d{7,}' if incident_mode() else r'CHG\d{7,}'
