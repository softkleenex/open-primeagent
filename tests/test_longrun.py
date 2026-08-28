"""L4 - goal, schedule and the autonomous gate loop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from opa.longrun.autonomous import AutonomousRunner, run_gate, worktree_fingerprint
from opa.longrun.goal import GoalStore
from opa.longrun.schedule import ScheduleStore

# ---------- goal ----------

@pytest.fixture
def goals(tmp_path):
    return GoalStore(tmp_path / "goal.json")


def test_goal_survives_a_fresh_store(goals, tmp_path):
    """The point of a goal is that it outlives the context that created it."""
    goals.create("ship the release", token_budget=1000)
    revived = GoalStore(tmp_path / "goal.json")
    assert revived.goal.objective == "ship the release"
    assert revived.goal.token_budget == 1000


def test_a_second_goal_is_refused_while_one_is_active(goals):
    goals.create("first")
    with pytest.raises(ValueError, match="still active"):
        goals.create("second")


def test_completing_reports_the_budget(goals):
    goals.create("ship it", token_budget=500)
    goals.spend(120)
    report = goals.complete()["budget_report"]
    assert report == {"token_budget": 500, "tokens_used": 120, "remaining_tokens": 380}


def test_completing_twice_is_refused(goals):
    goals.create("x")
    goals.complete()
    with pytest.raises(ValueError, match="already completed"):
        goals.complete()


def test_exhausting_the_budget_does_not_count_as_completion(goals):
    """Running out of budget is not the same as achieving the objective."""
    goals.create("big job", token_budget=100)
    goals.spend(150)
    assert goals.goal.status == "budget_exhausted"
    assert goals.goal.completed_at is None
    assert goals.get()["budget_exhausted"] is True


def test_abandon_does_not_claim_success(goals):
    goals.create("x")
    goals.abandon("changed direction")
    assert goals.goal.status == "abandoned"
    assert goals.goal.note == "changed direction"


def test_corrupt_goal_file_does_not_block_the_session(tmp_path):
    (tmp_path / "goal.json").write_text("{not json", encoding="utf-8")
    assert GoalStore(tmp_path / "goal.json").goal is None


# ---------- schedule ----------

@pytest.fixture
def schedule(tmp_path):
    return ScheduleStore(tmp_path / "schedule.jsonl")


def test_only_due_entries_come_back(schedule):
    schedule.create("later", in_seconds=3600)
    schedule.create("now", in_seconds=0)
    assert [e.prompt for e in schedule.due()] == ["now"]


def test_a_one_off_fires_once(schedule):
    schedule.create("now", in_seconds=0)
    assert len(schedule.due()) == 1
    assert schedule.due() == []


def test_an_interval_reschedules_itself(schedule):
    entry = schedule.create("heartbeat", every_seconds=30)
    assert len(schedule.due(collect=False)) == 0        # not due yet
    entry.due_at = datetime.now(UTC).isoformat()
    fired = schedule.due()
    assert len(fired) == 1
    assert fired[0].fires == 1
    assert fired[0].active is True                       # still scheduled
    assert datetime.fromisoformat(fired[0].due_at) > datetime.now(UTC)


def test_collect_false_does_not_consume(schedule):
    schedule.create("now", in_seconds=0)
    assert len(schedule.due(collect=False)) == 1
    assert len(schedule.due(collect=False)) == 1


def test_user_and_agent_entries_stay_distinguishable(schedule):
    """A user must be able to see what the agent scheduled on its own."""
    schedule.create("mine", in_seconds=60, source="user")
    schedule.create("its own", in_seconds=60, source="agent")
    assert [e.prompt for e in schedule.list(source="agent")] == ["its own"]


def test_entries_survive_a_fresh_store(schedule, tmp_path):
    schedule.create("later", in_seconds=3600, source="user")
    revived = ScheduleStore(tmp_path / "schedule.jsonl")
    assert [e.prompt for e in revived.list()] == ["later"]


def test_schedule_rejects_ambiguous_timing(schedule):
    with pytest.raises(ValueError, match="exactly one of"):
        schedule.create("x", in_seconds=1, every_seconds=60)
    with pytest.raises(ValueError, match="exactly one of"):
        schedule.create("x")


def test_interval_has_a_floor(schedule):
    with pytest.raises(ValueError, match="at least 30"):
        schedule.create("x", every_seconds=5)


def test_absolute_time_is_accepted(schedule):
    when = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert schedule.create("later", at=when).kind == "once"
    with pytest.raises(ValueError, match="ISO-8601"):
        schedule.create("bad", at="tomorrow-ish")


def test_delete_names_what_exists(schedule):
    entry = schedule.create("x", in_seconds=60)
    with pytest.raises(KeyError, match="known:"):
        schedule.delete("sch-nope")
    schedule.delete(entry.id)
    assert schedule.list() == []


# ---------- autonomous ----------

async def test_gate_passes_and_fails_on_exit_code(tmp_path):
    assert (await run_gate("exit 0", tmp_path)).passed is True
    failed = await run_gate("echo boom; exit 1", tmp_path)
    assert failed.passed is False
    assert "boom" in failed.output


async def test_gate_output_is_truncated(tmp_path):
    result = await run_gate("python3 -c \"print('x' * 50000)\"", tmp_path)
    assert len(result.output) < 5000
    assert "truncated" in result.output


async def test_the_gate_does_not_block_the_event_loop(tmp_path):
    """A gate is usually a test suite. Running it inline would freeze the bridge
    and every child callback for its whole duration."""
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.02)

    beat = asyncio.create_task(heartbeat())
    await run_gate("sleep 0.4", tmp_path)
    beat.cancel()
    assert ticks > 5, "the event loop was blocked while the gate ran"


class FakeRegistryRecord:
    def __init__(self) -> None:
        self.turns = 0
        self.tokens = 0
        self.cost_usd = 0.0
        self.status = "completed"
        self.last_error = None


class FakeRLM:
    """Records prompts and advances the child's turn counter, like the real one."""

    def __init__(self, config) -> None:
        self.config = config
        self.prompts: list[str] = []
        self.record = FakeRegistryRecord()
        self.registry = self
        self._exists = False

    def get(self, name):
        return self.record if self._exists else None

    async def run(self, prompt, name, **kw):
        self._exists = True
        self._advance(prompt)

    async def send(self, prompt, *, receiver_name):
        self._advance(prompt)

    def _advance(self, prompt):
        self.prompts.append(prompt)
        self.record.turns += 1
        self.record.tokens += 100


@pytest.fixture
def runner(config):
    return AutonomousRunner(FakeRLM(config))


async def test_stops_as_soon_as_the_gate_passes(runner):
    result = await runner.start("fix it", child_name="worker", gate="exit 0", max_turns=5)
    assert result["outcome"] == "gate_passed"
    assert result["turn_count"] == 1


async def test_a_failing_gate_feeds_its_output_back_in(runner):
    """This is the difference between an autonomous run and a cron job."""
    await runner.start(
        "fix it", child_name="worker", gate="echo 'AssertionError: nope'; exit 1", max_turns=3
    )
    prompts = runner.rlm.prompts
    assert len(prompts) == 3
    assert prompts[0] == "fix it"
    assert "AssertionError: nope" in prompts[1]


async def test_max_turns_stops_the_loop(runner):
    result = await runner.start("fix it", child_name="w", gate="exit 1", max_turns=2)
    assert result["outcome"] == "max_turns"
    assert result["turn_count"] == 2


async def test_token_budget_stops_the_loop(runner):
    result = await runner.start(
        "fix it", child_name="w", gate="exit 1", max_turns=10, token_budget=250
    )
    assert result["outcome"] == "token_budget"
    assert result["turn_count"] == 3      # 100 tokens per turn; stops once 250 is passed


async def test_a_goal_is_charged_for_autonomous_work(config, tmp_path):
    goals = GoalStore(tmp_path / "goal.json")
    goals.create("keep the tests green", token_budget=1000)
    runner = AutonomousRunner(FakeRLM(config), goals)
    await runner.start("fix it", child_name="w", gate="exit 1", max_turns=3)
    assert goals.goal.tokens_used == 300


async def test_two_runs_cannot_overlap(runner):
    first = asyncio.create_task(
        runner.start("x", child_name="w", gate="sleep 0.5; exit 0", max_turns=1)
    )
    while runner.active is None:          # wait until the first run is really in flight
        await asyncio.sleep(0.01)
    with pytest.raises(RuntimeError, match="already in progress"):
        await runner.start("y", child_name="w2", gate="exit 0")
    assert (await first)["outcome"] == "gate_passed"


def test_an_active_goal_carries_the_rules_with_it(goals):
    """A host that lost context should re-read the rules alongside the objective,
    not have to remember them."""
    goals.create("ship the release", token_budget=1000)
    state = goals.get()
    assert state["objective"] == "<objective>\nship the release\n</objective>"
    assert "Only `await goal.complete()` ends it" in state["guidance"]
    assert "audit the work" in state["guidance"]


def test_an_exhausted_budget_gets_the_opposite_instruction(goals):
    goals.create("big job", token_budget=100)
    goals.spend(150)
    state = goals.get()
    assert state["budget_exhausted"] is True
    assert "do not call" in state["guidance"]
    assert "Start no new work" in state["guidance"]


def test_completing_an_exhausted_goal_is_refused(goals):
    """Running out of budget is not achieving the objective."""
    goals.create("big job", token_budget=100)
    goals.spend(150)
    with pytest.raises(ValueError, match="not completion"):
        goals.complete()
    goals.abandon("budget ran out")
    assert goals.goal.status == "abandoned"


# ---------- not burning a turn on an unchanged tree ----------

def git_repo(tmp_path):
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=root, check=True
    )
    return root


def test_fingerprint_is_none_outside_a_git_repo(tmp_path):
    assert worktree_fingerprint(tmp_path) is None


def test_fingerprint_notices_edits_and_new_files(tmp_path):
    root = git_repo(tmp_path)
    base = worktree_fingerprint(root)

    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert worktree_fingerprint(root) != base

    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert worktree_fingerprint(root) == base, "a reverted edit should look unchanged"

    (root / "new.txt").write_text("hello\n", encoding="utf-8")
    assert worktree_fingerprint(root) != base, "an untracked file is still a change"


class EditingFake(FakeRLM):
    """A child that edits a file on some turns and does nothing on others."""

    def __init__(self, config, edits_on: set[int]) -> None:
        super().__init__(config)
        self.edits_on = edits_on
        self.turn = 0

    def _advance(self, prompt):
        self.turn += 1
        if self.turn in self.edits_on:
            target = self.config.workspace / "a.py"
            target.write_text(f"x = {self.turn + 100}\n", encoding="utf-8")
        super()._advance(prompt)


async def test_an_unchanged_tree_gets_told_so_instead_of_the_same_failure(config, tmp_path):
    """Re-running a gate against an identical tree cannot give a different
    answer, so repeating the failure just invites the same no-op again."""
    root = git_repo(tmp_path)
    workspace_config = config.__class__(**{**config.__dict__, "workspace": root})
    runner = AutonomousRunner(EditingFake(workspace_config, edits_on={1}))

    await runner.start("fix it", child_name="w", gate="exit 1", max_turns=3)

    prompts = runner.rlm.prompts
    assert "did not change any file" not in prompts[1], "turn 1 edited; do not scold it"
    assert "did not change any file" in prompts[2], "turn 2 changed nothing"
    assert "edit something" in prompts[2]


async def test_change_detection_is_recorded_per_turn(config, tmp_path):
    root = git_repo(tmp_path)
    workspace_config = config.__class__(**{**config.__dict__, "workspace": root})
    runner = AutonomousRunner(EditingFake(workspace_config, edits_on={1}))

    result = await runner.start("fix it", child_name="w", gate="exit 1", max_turns=2)
    assert [t["changed_files"] for t in result["turns"]] == [True, False]


async def test_suppression_stays_out_of_the_way_outside_git(config):
    """No repository, no fingerprint, no scolding."""
    runner = AutonomousRunner(FakeRLM(config))
    result = await runner.start("fix it", child_name="w", gate="exit 1", max_turns=2)
    assert all(t["changed_files"] is None for t in result["turns"])
    assert "did not change any file" not in "".join(runner.rlm.prompts)
