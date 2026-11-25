"""Harness state store.

The file schema stays compatible with upstream
(`_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py`) so sessions can move
between the two and upstream docs still apply:

    {"schema": 1,
     "entries": {"prompt": {id: {...}}, "memory": {...}, "skill": {...},
                 "subagent": {...}},
     "refinements": [{id, trigger, changes, evidence, outcome, created_at, ...}]}

One deliberate addition: RefinementEvent carries a `before` snapshot. Upstream
records changes as a list of strings, which **cannot be reverted precisely**.
It is an extra field that upstream's loader ignores, so compatibility holds both
ways.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..fsutil import atomic_write

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows: no advisory locks, merge only
    fcntl = None

HarnessKind = Literal["prompt", "memory", "skill", "subagent"]
HarnessScope = Literal["local", "global"]

KINDS: tuple[HarnessKind, ...] = ("prompt", "memory", "skill", "subagent")
SCHEMA_VERSION = 1
STATE_FILE_NAME = "harness_state.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def validate_id(raw: str) -> str:
    """Reject ids that are not safe as a single path component.

    Entry ids become file and directory names during projection
    (`.opa/memory/<id>.md`, `.claude/skills/<id>/`). A caller-supplied id like
    `../../CLAUDE` would therefore write outside the target directory, so ids
    must survive slugging unchanged.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("id must be a non-empty string")
    cleaned = slug(raw)
    if cleaned != raw:
        raise ValueError(
            f"unsafe harness id {raw!r}; ids must match their slug, e.g. {cleaned!r}"
        )
    return cleaned


def slug(raw: str, fallback: str = "entry") -> str:
    """Make a stable id from a title.

    Keeps Unicode word characters. Stripping non-ASCII would collapse every
    Korean/Japanese/Chinese title onto the same fallback id, so ids would
    collide and mean nothing.
    """
    normalized = re.sub(r"[^\w]+", "-", raw.strip().lower(), flags=re.UNICODE).strip("-_")
    return (normalized or fallback)[:60]


@dataclass
class HarnessEntry:
    """A reusable prompt, memory, skill, or subagent record."""

    id: str
    kind: HarnessKind
    title: str
    content: str
    path: str = "general"
    scope: HarnessScope = "local"
    reference: dict[str, Any] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "agent"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    version: int = 1


@dataclass
class RefinementEvent:
    """One harness refinement. Exact rollback requires the `before` snapshot.

    `rationale` and `expected_outcome` are what make a refinement reviewable
    later. Nothing checks an expected outcome mechanically — we have no gate that
    could — but it is fed back to whoever decides the *next* refinement, so a
    change that did not pay off can be recognised and rolled back instead of
    quietly accumulating. That is how the loop closes without an evaluator.
    """

    id: str
    trigger: str
    changes: list[str]
    evidence: str = ""
    outcome: str = ""
    rationale: str = ""
    expected_outcome: str = ""
    created_at: str = field(default_factory=_now)
    before: list[dict[str, Any]] = field(default_factory=list)
    reverted_at: str | None = None
    rollback_of: str | None = None


_ENTRY_FIELDS = {f.name for f in fields(HarnessEntry)}
_EVENT_FIELDS = {f.name for f in fields(RefinementEvent)}


class HarnessStore:
    """One scope, one file."""

    def __init__(self, file_path: Path, scope: HarnessScope = "local") -> None:
        self.file_path = Path(file_path)
        self.scope: HarnessScope = scope
        self.entries: dict[HarnessKind, dict[str, HarnessEntry]] = {k: {} for k in KINDS}
        self.refinements: list[RefinementEvent] = []
        self._deferred = 0
        self._dirty = False
        self.unreadable: str | None = None
        # (kind, id) -> entry, or None for a delete. What *this* process changed
        # since it last read the file, which is what has to survive a merge.
        self._touched: dict[tuple[str, str], object] = {}
        self._stamp: tuple[int, int, int] | None = None
        self._created: set[tuple[str, str]] = set()      # ids we generated, not chose
        self._touched_events: set[str] = set()           # refinements changed in place
        self.load()

    # ---------- persistence ----------

    def load(self) -> HarnessStore:
        self.entries = {k: {} for k in KINDS}
        self.refinements = []
        self._touched = {}
        self._stamp = None
        if not self.file_path.exists():
            return self
        self._stamp = self._file_stamp()
        try:
            raw = self.file_path.read_text(encoding="utf-8")
        except OSError as exc:
            # The file is there and we cannot read it - permissions, a locked
            # file, a transient I/O error. Starting empty would be harmless
            # except that the next save() overwrites it, and an unreadable file
            # is not a damaged one. Measured on the old code: five accumulated
            # memories destroyed by one chmod.
            #
            # So the session continues with an empty harness in memory, but this
            # store refuses to write until someone has looked.
            self.unreadable = str(exc)
            return self
        try:
            data = json.loads(raw)
        except ValueError:
            # Genuinely corrupt. Keep the damaged file rather than overwriting
            # it - whatever is left in there may still be recoverable by hand,
            # and it is the only copy.
            self._quarantine()
            return self
        if not isinstance(data, dict):
            return self

        raw_entries = data.get("entries")
        if isinstance(raw_entries, dict):
            for kind in KINDS:
                for entry_id, raw in (raw_entries.get(kind) or {}).items():
                    entry = self._coerce_entry(entry_id, kind, raw)
                    if entry is not None:
                        self.entries[kind][entry.id] = entry

        for raw in data.get("refinements") or []:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                payload = {k: v for k, v in raw.items() if k in _EVENT_FIELDS}
                payload.setdefault("trigger", "")
                payload.setdefault("changes", [])
                try:
                    self.refinements.append(RefinementEvent(**payload))
                except TypeError:
                    continue
        return self

    def _coerce_entry(self, entry_id: Any, kind: HarnessKind, raw: Any) -> HarnessEntry | None:
        if not isinstance(raw, dict):
            return None
        data = {k: v for k, v in raw.items() if k in _ENTRY_FIELDS}
        data["id"] = str(entry_id)
        data["kind"] = kind
        if not isinstance(data.get("title"), str) or not isinstance(data.get("content"), str):
            return None
        if not isinstance(data.get("path"), str):
            data["path"] = "general"
        if data.get("scope") not in ("local", "global"):
            data["scope"] = self.scope
        if not isinstance(data.get("source"), str):
            data["source"] = "agent"
        for key in ("reference", "arguments", "metadata"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        try:
            data["version"] = int(data.get("version", 1))
        except (TypeError, ValueError):
            data["version"] = 1
        try:
            return HarnessEntry(**data)
        except TypeError:
            return None

    @contextmanager
    def batched(self):
        """Hold writes until the block ends, then make exactly one.

        Every CRUD call saves, so a multi-change `apply` wrote the state file
        once per change. Each write is atomic on its own, but the sequence is
        not: a crash between them leaves the harness half-changed *and* with no
        refinement recorded, because the record is only written once the whole
        delta succeeds. Nothing is left to roll back - the outcome `apply`'s own
        docstring calls the worst possible one.

        Batching makes the delta a single `os.replace`, so the file on disk is
        either all of it or none of it.
        """
        self._deferred += 1
        try:
            yield self
        finally:
            self._deferred -= 1
            if self._deferred == 0 and self._dirty:
                self._dirty = False
                self.save()

    def _file_stamp(self) -> tuple[int, int, int] | None:
        """Cheap identity for the file as we last saw it.

        The inode is part of it: every save is a rename, so a new inode, while
        mtime and size can both repeat on a filesystem with coarse timestamps.
        """
        try:
            info = self.file_path.stat()
        except OSError:
            return None
        return (info.st_ino, info.st_mtime_ns, info.st_size)

    @contextlib.contextmanager
    def _locked(self):
        """Hold the store's lock across check, merge and write.

        Without it, a second server saving between our stamp check and our
        rename had its entry silently erased - the lost update the merge exists
        to prevent, one window later.
        """
        if fcntl is None:
            yield
            return
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.file_path.with_name(self.file_path.name + ".lock")
        with lock_path.open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _merge_onto_disk(self) -> None:
        """Re-read, then replay only what this process changed.

        The global store exists to be shared between projects, so two servers
        holding it open is the normal case, not an edge one. Each had loaded the
        whole file and each wrote the whole file back, so whichever saved second
        silently erased anything the other had added since. Measured: three
        entries created, two on disk.

        Merging by change-set rather than by union is what makes deletes work -
        a union would resurrect every entry either side had removed.
        """
        mine = dict(self._touched)
        created = set(self._created)
        my_refinements = list(self.refinements)
        changed_events = set(self._touched_events)
        self.load()
        if self.unreadable:
            return  # save() refuses; replaying onto nothing would wipe the store
        for (kind, entry_id), entry in list(mine.items()):
            if entry is None:
                self.entries[kind].pop(entry_id, None)
                continue
            theirs = self.entries[kind].get(entry_id)
            if (
                (kind, entry_id) in created
                and theirs is not None
                and theirs.created_at != entry.created_at
            ):
                # Another server generated the same id from the same title. Ours
                # moves aside instead of overwriting theirs.
                del mine[(kind, entry_id)]
                entry.id = f"{entry_id}-{uuid.uuid4().hex[:4]}"
                mine[(kind, entry.id)] = entry
            self.entries[kind][entry.id] = entry
        ours = {event.id: event for event in my_refinements}
        known = {event.id for event in self.refinements}
        self.refinements = [
            ours[event.id] if event.id in changed_events and event.id in ours else event
            for event in self.refinements
        ]
        for event in my_refinements:
            if event.id not in known:
                self.refinements.append(event)
        self._touched = mine

    def _quarantine(self) -> None:
        """Move a corrupt state file aside, keeping the newest few."""
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        spoiled = self.file_path.with_name(f"{self.file_path.name}.corrupt-{stamp}")
        try:
            os.replace(self.file_path, spoiled)
        except OSError:
            self.unreadable = "the state file is corrupt and could not be set aside"

    def save(self) -> HarnessStore:
        if self.unreadable:
            raise RuntimeError(
                f"refusing to write {self.file_path}: it could not be read "
                f"({self.unreadable}). Writing now would replace a file that was "
                f"never damaged. Fix the read problem, or move the file aside "
                f"yourself, and start a new session."
            )
        if self._deferred:
            self._dirty = True
            return self
        with self._locked():
            # No `is not None` guard: a store that loaded before the file existed
            # has a stamp of None, and two servers starting fresh on a shared
            # global store is exactly that case - the one the first version of
            # this skipped.
            if self._file_stamp() != self._stamp:
                self._merge_onto_disk()
                if self.unreadable:
                    # The merge's own read failed. Writing now would replace the
                    # whole store with only what this process changed.
                    raise RuntimeError(
                        f"refusing to write {self.file_path}: re-reading it before "
                        f"the merge failed ({self.unreadable})."
                    )
            self._write()
        return self

    def _write(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema": SCHEMA_VERSION,
            "entries": {
                kind: {eid: asdict(e) for eid, e in records.items()}
                for kind, records in self.entries.items()
            },
            "refinements": [asdict(e) for e in self.refinements],
        }
        atomic_write(self.file_path, json.dumps(data, indent=2, ensure_ascii=False))
        self._stamp = self._file_stamp()
        self._touched = {}
        self._created = set()
        self._touched_events = set()

    def put(self, entry: HarnessEntry) -> None:
        """Store `entry` as given - the restore path of rollback and undo.

        Writing `entries[...]` directly skipped the change-set, so a merge
        replayed the stale object instead: a failed `apply` stayed applied and
        a rollback silently lost its restore whenever another server had saved.
        """
        self.entries[entry.kind][entry.id] = entry
        self._touched[(entry.kind, entry.id)] = entry
        self.save()

    def touch(self, entry: HarnessEntry) -> None:
        """Mark an entry changed in place (metadata) so a merge keeps the change."""
        if self.entries[entry.kind].get(entry.id) is entry:
            self._touched[(entry.kind, entry.id)] = entry

    def touch_refinement(self, event: RefinementEvent) -> None:
        self._touched_events.add(event.id)

    # ---------- CRUD ----------

    def create(self, kind: HarnessKind, title: str, content: str, **kw) -> HarnessEntry:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}. one of: {', '.join(KINDS)}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        supplied = kw.pop("id", None)
        entry_id = validate_id(supplied) if supplied else self._unique_id(kind, title)
        if not supplied:
            self._created.add((kind, entry_id))
        entry = HarnessEntry(
            id=entry_id, kind=kind, title=title.strip(), content=content, scope=self.scope, **kw
        )
        self.entries[kind][entry.id] = entry
        self._touched[(kind, entry.id)] = entry
        self.save()
        return entry

    def _unique_id(self, kind: HarnessKind, title: str) -> str:
        base = slug(title)
        if base not in self.entries[kind]:
            return base
        return f"{base}-{uuid.uuid4().hex[:4]}"

    def get(self, entry_id: str) -> HarnessEntry | None:
        for kind in KINDS:
            if entry_id in self.entries[kind]:
                return self.entries[kind][entry_id]
        return None

    def update(self, entry_id: str, **changes) -> HarnessEntry:
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(f"no harness entry {entry_id!r}. {self._known()}")
        for key, value in changes.items():
            if key in ("id", "kind"):
                raise ValueError(f"{key} cannot be changed")
            if key not in _ENTRY_FIELDS:
                raise ValueError(f"unknown field {key!r}")
            setattr(entry, key, value)
        entry.updated_at = _now()
        entry.version += 1
        self._touched[(entry.kind, entry.id)] = entry
        self.save()
        return entry

    def delete(self, entry_id: str) -> HarnessEntry:
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(f"no harness entry {entry_id!r}. {self._known()}")
        del self.entries[entry.kind][entry.id]
        self._touched[(entry.kind, entry.id)] = None
        self.save()
        return entry

    def list(self, kind: HarnessKind | None = None) -> list[HarnessEntry]:
        kinds = (kind,) if kind else KINDS
        out: list[HarnessEntry] = []
        for k in kinds:
            out.extend(self.entries[k].values())
        return sorted(out, key=lambda e: (e.kind, e.created_at))

    def _known(self) -> str:
        ids = [e.id for e in self.list()]
        return f"known ids: {', '.join(ids) if ids else '(none)'}"

    # ---------- refinement ----------

    def record_refinement(self, event: RefinementEvent) -> RefinementEvent:
        self.refinements.append(event)
        self.save()
        return event

    def find_refinement(self, event_id: str) -> RefinementEvent | None:
        return next((e for e in self.refinements if e.id == event_id), None)
