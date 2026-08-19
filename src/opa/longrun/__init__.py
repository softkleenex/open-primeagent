"""L4 - long-running autonomous work: goal / heartbeat / schedule / autonomous.

A stated limit: we do not own the host's turn loop. "Waking the agent" is
therefore a pull (the mailbox is collected on the next turn), not a push. Real
push requires the autonomous mode where opa drives the adapters itself.
"""
