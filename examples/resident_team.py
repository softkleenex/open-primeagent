"""Example: a specialist team that lives in the project.

The point is not the fan-out. The point is that these are the *same* children,
called again days later.

Requires Phase 2 (shipped). Run inside `opa_python`.
"""

# --- day one: assemble the team ------------------------------------------
await rlm("map the backend architecture and the API contracts", name="backend")
await rlm("map the frontend state management",                  name="frontend")
await rlm("find the gaps in our test strategy",                 name="test", adapter="codex")
await rlm("list the risks on the auth and permission paths",    name="security")

# --- days later, after several kernel restarts ----------------------------
team = await rlm.list_subagents()      # all four are still here
print([c.name for c in team])

# Re-task the agent that already has the context instead of making a new one
await agent_message.send(
    "review again, now including the payments module we just merged",
    receiver_role="child", receiver_name="security",
)

# --- intermediate data stays here, not in the model's context -------------
inbox = await agent_message.poll()
issues = [m for m in inbox if m["sender"] == "security"]
issues[:3]        # the model only ever sees these three
