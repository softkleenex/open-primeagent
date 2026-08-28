"""opa_status - kernel, children, goal and harness on one page.

After the host loses context (compaction, restart) this single call has to
restore "how far did I get, and who is still working".
"""

DESCRIPTION = """\
One-page state of the open-primeagent session, starting with "attention": what
is waiting for you and what looks worth promoting to the harness, so you do not
have to know which question to ask.

Then the details: kernel liveness, persistent sub-agents (name / adapter /
status / turns / tokens), active goal and budget, scheduled prompts, harness
entry counts, and unread mailbox messages.

Call this whenever you have lost context or are picking work back up. Reading it
does not consume anything: due schedule items stay due and mail stays unread.
"""
