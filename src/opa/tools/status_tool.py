"""opa_status - kernel, children, goal and harness on one page.

After the host loses context (compaction, restart) this single call has to
restore "how far did I get, and who is still working".
"""

DESCRIPTION = """\
One-page state of the open-primeagent session: kernel liveness, persistent
sub-agents (name / adapter / status / last turn), active goal and budget,
harness entry counts, and unread mailbox messages.
Call this after a context compaction or when resuming work.
"""
