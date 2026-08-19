"""opa_kernel — restart | interrupt | info.

restart는 사용자 변수를 날린다. child registry·harness·goal은 디스크에 있으므로 남는다.
"""

DESCRIPTION = """\
Control the persistent kernel: "restart" (clears Python variables; sub-agents,
harness and goal survive), "interrupt" (stop a hung cell), "info".
"""
