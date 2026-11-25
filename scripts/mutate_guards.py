"""Break each safety guard in turn and check the suite notices.

A guard with no failing test is a comment. Coverage does not answer this: a line
can be executed by every test in the file and still have nothing asserting what
it decides. So this edits the source, runs the suite, and restores the file
whatever happens.

Not wired into CI - it takes minutes and rewrites source files, which is a poor
fit for a hook. Run it after touching anything on this list.

    uv run python scripts/mutate_guards.py [--list]

Each entry is (label, file, exact source, replacement). An ANCHOR MISSING result
means the code moved out from under the mutation, which needs the entry updated
rather than ignored - an unanchored mutation silently tests nothing.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "projection refuses writes outside its directory",
        "src/opa/harness/projection.py",
        "    if root not in candidate.parents:",
        "    if False:",
    ),
    (
        "projection only prunes directories it created",
        "src/opa/harness/projection.py",
        '            managed = directory.is_dir() and (directory / ".opa-managed").exists()',
        "            managed = directory.is_dir()",
    ),
    (
        "a child's cwd cannot leave the workspace",
        "src/opa/rlm/spawn.py",
        "        if candidate != workspace and workspace not in candidate.parents:",
        "        if False:",
    ),
    (
        "the bridge rejects a token it did not issue",
        "src/opa/bridge.py",
        "        return self._tokens.get(token) if isinstance(token, str) else None",
        '        return Caller(role="parent", name="")',
    ),
    (
        "an unknown token is not silently downgraded to a child",
        "src/opa/bridge.py",
        "        return self._tokens.get(token) if isinstance(token, str) else None",
        '        return self._tokens.get(token) or Caller(role="child", name="")',
    ),
    (
        "harness ids must be safe as a path component",
        "src/opa/harness/state.py",
        "def validate_id(raw: str) -> str:",
        "def validate_id(raw: str) -> str:\n    return str(raw)",
    ),
    (
        "durable writes go through a temp file and a rename",
        "src/opa/fsutil.py",
        "        _write_tmp(tmp, text, encoding)",
        "        target.write_text(text, encoding=encoding)\n        return",
    ),
    (
        "an unreadable state file is never written over",
        "src/opa/harness/state.py",
        # Unique on purpose: a bare `if self.unreadable:` also matches the
        # more deeply indented merge guard, which is a different guard.
        '        if self.unreadable:\n            raise RuntimeError(\n                f"refusing to write {self.file_path}: it could not be read "',
        '        if False:\n            raise RuntimeError(\n                f"refusing to write {self.file_path}: it could not be read "',
    ),
    (
        "a turn interrupted by a restart is reconciled",
        "src/opa/rlm/registry.py",
        '            if record.status == "running":',
        "            if False:",
    ),
    (
        "a shared store merges instead of clobbering",
        "src/opa/harness/state.py",
        "        if self._file_stamp() != self._stamp:",
        "        if False:",
    ),
    (
        "a merge replays changes rather than unioning them",
        "src/opa/harness/state.py",
        "            if entry is None:\n                self.entries[kind].pop(entry_id, None)",
        "            if False:\n                self.entries[kind].pop(entry_id, None)",
    ),
    (
        "projection markers count only as whole lines",
        "src/opa/harness/projection.py",
        '    begins = [i for i, ln in enumerate(lines) if _BEGIN_LINE.fullmatch(ln.rstrip("\\r\\n"))]',
        '    begins = [i for i, ln in enumerate(lines) if _BEGIN_LINE.search(ln)]',
    ),
    (
        "ambiguous projection markers are refused",
        "src/opa/harness/projection.py",
        "    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:",
        "    if not begins or not ends:",
    ),
    (
        "a prompt can never be parsed as a CLI option",
        "src/opa/rlm/adapters/claude_code.py",
        '        return [*cmd, "--", request.prompt]',
        '        return [cmd[0], request.prompt, *cmd[1:]]',
    ),
    (
        "a cancelled child turn kills the child process",
        "src/opa/rlm/adapters/base.py",
        "    except BaseException:\n        _kill_group(proc)",
        "    except BaseException:\n        pass",
    ),
    (
        "the shared store locks across check and write",
        "src/opa/harness/state.py",
        "            fcntl.flock(fh, fcntl.LOCK_EX)",
        "            pass",
    ),
    (
        "a merge that cannot read the file does not write",
        "src/opa/harness/state.py",
        "            return  # save() refuses; replaying onto nothing would wipe the store",
        "            self.unreadable = None",
    ),
    (
        "kernel cells never run concurrently",
        "src/opa/kernel/manager.py",
        "        async with self._exec_lock:\n            return await self._execute_locked(",
        "        if True:\n            return await self._execute_locked(",
    ),
    (
        "a finished goal cannot be reopened",
        "src/opa/longrun/goal.py",
        '        if self.goal.status == "abandoned":\n            raise ValueError(\n                "this goal was abandoned; completing it',
        '        if False:\n            raise ValueError(\n                "this goal was abandoned; completing it',
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="show the guards and exit")
    args = parser.parse_args()

    if args.list:
        for label, rel, _, _ in MUTATIONS:
            print(f"  {label}  ({rel})")
        return 0

    survivors: list[str] = []
    unanchored: list[str] = []

    for label, rel, old, new in MUTATIONS:
        path = REPO / rel
        original = path.read_text()
        if old not in original:
            unanchored.append(label)
            print(f"  {label:<52} ANCHOR MISSING")
            continue
        path.write_text(original.replace(old, new, 1))
        try:
            proc = subprocess.run(
                ["uv", "run", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        finally:
            path.write_text(original)
        if proc.returncode == 0:
            survivors.append(label)
            print(f"  {label:<52} NOT CAUGHT")
        else:
            print(f"  {label:<52} caught")

    print()
    if unanchored:
        print(f"  {len(unanchored)} mutation(s) could not be applied; update them.")
    if survivors:
        print(f"  {len(survivors)} guard(s) no test defends:")
        for s in survivors:
            print(f"    - {s}")
    if not survivors and not unanchored:
        print(f"  all {len(MUTATIONS)} guards are defended by a failing test")
    return 1 if (survivors or unanchored) else 0


if __name__ == "__main__":
    sys.exit(main())
