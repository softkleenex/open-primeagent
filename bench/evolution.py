"""Evolution benchmark: does a learned harness entry actually pay for itself?

The setup is a project with a rule you cannot infer from the code you are asked
to touch: editing the schema requires re-running a generator, or the tests fail
against a stale generated module.

    round A  no harness      -> the agent must discover the rule by failing
    (refine) record the rule as a harness prompt entry
    round B  harness applied -> a fresh session starts already knowing it

Both rounds run the same task in an identical, freshly generated workspace, so
the only difference is the projected harness. That is the whole claim behind
"self-improving": not better weights, a better operating procedure.

Two variants, because the first run showed the answer depends entirely on how
expensive the knowledge is to rediscover:

    easy  generate.py sits in the project root next to schema.py
    hard  the generator is one of 16 scripts under tools/, the failure message
          does not name it, and several decoys look equally plausible

`easy` is the honest control: when a competent model can rediscover the rule in
one glance, a harness entry only adds tokens.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TASK = (
    "Add a required 'phone' field (a string) to the User schema in schema.py, "
    "then make `python -m pytest -q` pass. Reply with only DONE when the tests pass."
)

LESSONS = {
    "easy": (
        "After editing `schema.py`, always run `python generate.py` before running "
        "the tests. `models_gen.py` is generated from the schema and pytest checks "
        "the two against each other, so a stale generated file fails the suite."
    ),
    "hard": (
        "After editing `schema.py`, always run `python tools/sync_models.py` before "
        "running the tests. It is the only script that regenerates `models_gen.py`; "
        "the other scripts under tools/ do not, despite their names."
    ),
}

DECOYS = [
    "build_assets", "check_style", "codegen_docs", "compile_protos", "gen_fixtures",
    "make_models", "migrate_db", "regen_types", "render_templates", "seed_data",
    "sync_schema", "update_index", "validate_schema", "warm_cache", "write_manifest",
]


def projection(variant: str) -> str:
    return (
        "<!-- opa:begin — generated. Nothing outside this block is touched. -->\n"
        "## open-primeagent\n\n"
        "### Rules for this project\n\n"
        f"- **regenerate after schema edits** — {LESSONS[variant]}\n"
        "<!-- opa:end -->\n"
    )


GENERATOR_SRC = (
    "import sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
    "import schema\n"
    "root = Path(__file__).resolve().parent.parent\n"
    "(root / 'models_gen.py').write_text(\n"
    '    "GENERATED_FIELDS = " + repr(schema.FIELDS) + "\\n", encoding="utf-8"\n'
    ")\n"
    "print('regenerated models_gen.py')\n"
)


def build_project(root: Path, variant: str = "easy") -> None:
    """A tiny project whose test suite depends on a generated file."""
    if root.exists():
        shutil.rmtree(root)
    (root / "tests").mkdir(parents=True)

    (root / "schema.py").write_text(
        'FIELDS = ["id", "email"]\n', encoding="utf-8"
    )
    if variant == "easy":
        (root / "generate.py").write_text(
            "from pathlib import Path\n"
            "import schema\n"
            "Path('models_gen.py').write_text(\n"
            '    "GENERATED_FIELDS = " + repr(schema.FIELDS) + "\\n", encoding="utf-8"\n'
            ")\n"
            'print("regenerated models_gen.py")\n',
            encoding="utf-8",
        )
    else:
        tools = root / "tools"
        tools.mkdir()
        (tools / "sync_models.py").write_text(GENERATOR_SRC, encoding="utf-8")
        for name in DECOYS:
            (tools / f"{name}.py").write_text(
                f'"""{name.replace("_", " ").title()} helper."""\n'
                f'print("{name}: nothing to do")\n',
                encoding="utf-8",
            )
    (root / "models_gen.py").write_text(
        'GENERATED_FIELDS = ["id", "email"]\n', encoding="utf-8"
    )
    (root / "tests" / "test_schema.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "import schema\n"
        "import models_gen\n"
        "\n"
        "def test_generated_matches_schema():\n"
        "    assert models_gen.GENERATED_FIELDS == schema.FIELDS, (\n"
        '        "models_gen.py is stale"\n'
        "    )\n"
        "\n"
        "def test_phone_field_present():\n"
        '    assert "phone" in schema.FIELDS\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# demo service\n\nA tiny schema-driven service.\n", encoding="utf-8"
    )


@dataclass
class RoundResult:
    round: str
    variant: str
    answer: str
    input_tokens: int
    output_tokens: int
    cache_write: int
    cache_read: int
    billed_tokens: int
    cost_usd: float
    agent_turns: int
    duration_ms: int
    tests_pass: bool


def tests_pass(root: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=root, capture_output=True, check=False, timeout=120,
    )
    return proc.returncode == 0


def run_round(
    name: str, model: str, with_harness: bool, timeout: float, variant: str
) -> RoundResult:
    root = Path(tempfile.mkdtemp(prefix=f"opa-evo-{name}-"))
    build_project(root, variant)
    if with_harness:
        (root / "CLAUDE.md").write_text(projection(variant), encoding="utf-8")

    cmd = [
        "claude", "-p", TASK, "--output-format", "json", "--model", model,
        "--allowedTools", "Bash,Read,Edit,Write,Grep,Glob",
        "--permission-mode", "acceptEdits",
    ]
    started = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=root, capture_output=True, timeout=timeout,
        stdin=subprocess.DEVNULL, check=False,
    )
    elapsed = int((time.monotonic() - started) * 1000)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"result": f"<parse error: {proc.stderr.decode()[:200]}>", "usage": {}}

    usage = payload.get("usage") or {}
    inp = int(usage.get("input_tokens", 0))
    out = int(usage.get("output_tokens", 0))
    cw = int(usage.get("cache_creation_input_tokens", 0))
    return RoundResult(
        round=name,
        variant=variant,
        answer=(payload.get("result") or "").strip()[:120],
        input_tokens=inp,
        output_tokens=out,
        cache_write=cw,
        cache_read=int(usage.get("cache_read_input_tokens", 0)),
        billed_tokens=inp + out + cw,
        cost_usd=round(float(payload.get("total_cost_usd") or 0.0), 6),
        agent_turns=int(payload.get("num_turns") or 0),
        duration_ms=elapsed,
        tests_pass=tests_pass(root),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--variant", default="hard", choices=["easy", "hard"])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    args = parser.parse_args()

    rows: list[RoundResult] = []
    for attempt in range(args.repeat):
        for name, with_harness in (("A-no-harness", False), ("B-with-harness", True)):
            print(f"[{name}] attempt {attempt + 1}/{args.repeat} …")
            row = run_round(name, args.model, with_harness, args.timeout, args.variant)
            print(
                f"    turns={row.agent_turns} billed={row.billed_tokens} "
                f"cost=${row.cost_usd} pass={row.tests_pass} ({row.duration_ms}ms)"
            )
            rows.append(row)

    out = Path(args.out) / f"evolution-{args.variant}-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Append, so sample size grows across invocations instead of being replaced.
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    out.write_text(
        json.dumps(previous + [asdict(r) for r in rows], indent=2), encoding="utf-8"
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
