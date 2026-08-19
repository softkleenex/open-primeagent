"""opa_kernel — restart | interrupt | info.

restart clears user variables. The child registry, harness and goal live on disk
and survive.
"""

DESCRIPTION = """\
Control the persistent kernel: "restart" (clears Python variables; sub-agents,
harness and goal survive), "interrupt" (stop a hung cell), "info".
"""
