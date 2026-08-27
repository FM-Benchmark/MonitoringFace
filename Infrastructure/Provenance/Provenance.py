"""Input provenance for tool runs.

Every monitor receives its trace/policy after an automatic conversion into the
nearest format it supports; those converted files live in the per-setting
scratch folder and are deleted after the setting finishes. With provenance
enabled (the default), the exact final inputs of every tool run are copied,
under honest names, into the run's results folder together with a manifest
(provenance.json) recording the canonical sources, the conversion chain with
the exact commands, and sha256 hashes of both endpoints, so a critical user
can audit or reproduce each conversion.

Guarantees (stricter than --debug):
  - captured after conversion and BEFORE the tool runs (crashes keep it)
  - per-tool: only the files named by the conversion records, never a scratch
    snapshot, so build artifacts and other tools' leftovers are excluded
  - provenance.json is written last into an atomically renamed directory, so
    it can never point at files that are not there
  - repeat runs re-convert; capture verifies the hashes match (a
    nondeterministic converter is surfaced as an error, not papered over)
  - a capture failure raises ProvenanceError: the run must not produce a
    result row without its provenance
  - after the run, the inputs are re-hashed and input_unchanged_after_run is
    recorded (the setting folder is mounted read-write in the container)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
PROVENANCE_DIR_NAME = "provenance"
MANIFEST_NAME = "provenance.json"
# params keys that hold per-run DERIVED state, not configuration; the
# stratification map in particular is stale from the previous setting at
# capture time (it is rebuilt only after capture)
_DERIVED_PARAM_KEYS = ("stratified_map",)


class ProvenanceError(Exception):
    pass


@dataclass(frozen=True)
class ConversionStep:
    converter: str                     # converter class name
    source_format: str                 # e.g. "csv"
    target_format: str                 # e.g. "dejavu-encoded"
    command: Optional[List[str]]       # exact argv, None for in-process converters
    cmd_params: Optional[List[str]]    # params["cmd_params"] override, if any


@dataclass(frozen=True)
class ConversionRecord:
    kind: str                          # "trace" | "policy" | "signature"
    source_file: str                   # relative to the setting folder
    source_format: str
    steps: List[ConversionStep]        # empty list == identity (distance 0)
    as_seen_by_tool: str               # path the tool command references,
    #                                    relative to the setting folder
    custom: bool = False               # produced by a bespoke preprocessing_*

    @property
    def converted(self) -> bool:
        return bool(self.steps) or self.custom

    def stored_name(self) -> str:
        """Honest filename for the stored copy (e.g. trace.dejavu-encoded)."""
        if self.custom:
            return f"{self.kind}.custom"
        ext = self.steps[-1].target_format if self.steps else self.source_format
        return f"{self.kind}.{ext}"


@dataclass
class PreprocessingResult:
    elapsed_s: float
    records: List[ConversionRecord] = field(default_factory=list)


def _sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _safe(name: str) -> str:
    return name.replace("/", "_").replace(" ", "_").replace(":", "_").replace(">", "")


def _jsonable(obj: Any) -> Any:
    """Recursive JSON normalizer. json.dumps alone raises on dicts with
    non-primitive or mixed-type keys (params can carry anything)."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v)
                for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _scrub_paths(obj: Any, project_root: Optional[str]) -> Any:
    """Provenance manifests may be published; absolute local paths would leak
    the machine's username. Rewrite anything under the project root."""
    if not project_root:
        return obj
    if isinstance(obj, str):
        return obj.replace(project_root.rstrip("/"), "<project>")
    if isinstance(obj, list):
        return [_scrub_paths(v, project_root) for v in obj]
    if isinstance(obj, dict):
        return {k: _scrub_paths(v, project_root) for k, v in obj.items()}
    return obj


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".provenance-", dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=1)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def framework_commit(path_to_project: str) -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", "-C", path_to_project, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        return res.stdout.strip() if res.returncode == 0 else None
    except Exception:
        return None


def read_fingerprint(fingerprint_file: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if os.path.isfile(fingerprint_file):
        with open(fingerprint_file, "r") as f:
            for line in f:
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    return out


class ProvenanceFactory:
    """Run-scoped context shared by all sessions of one benchmark run."""

    def __init__(self, result_folder: str, experiment_root: str,
                 fingerprint: Dict[str, str], commit: Optional[str],
                 project_root: Optional[str] = None):
        self.result_folder = result_folder
        self.experiment_root = experiment_root
        self.fingerprint = fingerprint
        self.commit = commit
        self.project_root = project_root

    def session(self, setting_key: str, setting_folder: str, tool) -> "ProvenanceSession":
        return ProvenanceSession(
            root=os.path.join(self.result_folder, PROVENANCE_DIR_NAME),
            setting_key=setting_key, setting_folder=setting_folder,
            tool_name=tool.name, tool_identifier=tool.__class__.__name__,
            tool_params=tool.params, experiment_root=self.experiment_root,
            fingerprint=self.fingerprint, commit=self.commit,
            project_root=self.project_root,
        )


class ProvenanceSession:
    """Provenance of ONE tool in ONE setting (shared across repeat runs)."""

    def __init__(self, root: str, setting_key: str, setting_folder: str,
                 tool_name: str, tool_identifier: str, tool_params: Dict[str, Any],
                 experiment_root: str, fingerprint: Dict[str, str],
                 commit: Optional[str], project_root: Optional[str] = None):
        self.setting_folder = setting_folder
        self.tool_name = tool_name
        self.tool_identifier = tool_identifier
        self.tool_params = tool_params
        self.experiment_root = experiment_root
        self.fingerprint = fingerprint
        self.commit = commit
        self.project_root = project_root
        self.setting_key = setting_key
        self.entry_dir = os.path.join(root, _safe(setting_key), _safe(tool_name))
        self.manifest_path = os.path.join(self.entry_dir, MANIFEST_NAME)

    # -- capture ------------------------------------------------------------

    def capture(self, records: List[ConversionRecord]) -> None:
        """Store the final inputs + manifest; on a repeat, verify identity."""
        try:
            kinds = [r.kind for r in records]
            if len(kinds) != len(set(kinds)):
                raise ProvenanceError(f"duplicate record kinds {kinds} for {self.tool_name}")
            if os.path.isdir(self.entry_dir):
                self._verify_repeat(records)
            else:
                self._write_entry(records)
        except ProvenanceError:
            raise
        except Exception as e:
            raise ProvenanceError(
                f"provenance capture failed for {self.tool_name} @ {self.setting_key}: {e}"
            ) from e

    def _source_abs(self, record: ConversionRecord) -> str:
        return os.path.join(self.setting_folder, record.source_file)

    def _tool_input_abs(self, record: ConversionRecord) -> str:
        return os.path.join(self.setting_folder, record.as_seen_by_tool)

    def _write_entry(self, records: List[ConversionRecord]) -> None:
        parent = os.path.dirname(self.entry_dir)
        tmp = os.path.join(parent, f".{os.path.basename(self.entry_dir)}.tmp-{os.getpid()}")
        # sweep litter from crashed earlier processes (any pid)
        if os.path.isdir(parent):
            for stale in os.listdir(parent):
                if stale.startswith(f".{os.path.basename(self.entry_dir)}.tmp-"):
                    shutil.rmtree(os.path.join(parent, stale), ignore_errors=True)
        os.makedirs(tmp)

        entries = []
        for rec in records:
            source_abs = self._source_abs(rec)
            # custom preprocessing may hand over container-relative paths the
            # host cannot resolve; record what is resolvable, never abort a
            # custom route on it (the auto route stays strict)
            source_sha = None
            if os.path.isfile(source_abs):
                source_sha = _sha256(source_abs)
            elif not rec.custom:
                raise ProvenanceError(f"canonical {rec.kind} file missing: {source_abs}")
            stored = None
            if rec.converted:
                converted_abs = self._tool_input_abs(rec)
                if os.path.isfile(converted_abs):
                    stored_name = rec.stored_name()
                    shutil.copy2(converted_abs, os.path.join(tmp, stored_name))
                    stored = {
                        "file": stored_name,
                        "sha256": _sha256(os.path.join(tmp, stored_name)),
                    }
                elif not rec.custom:
                    raise ProvenanceError(f"converted {rec.kind} file missing: {converted_abs}")
            entries.append({
                "kind": rec.kind,
                "source": {
                    "file": os.path.relpath(source_abs, self.experiment_root),
                    "format": rec.source_format,
                    "sha256": source_sha,
                },
                "steps": [
                    {
                        "converter": s.converter,
                        "source_format": s.source_format,
                        "target_format": s.target_format,
                        "command": s.command,
                        "cmd_params": s.cmd_params,
                    }
                    for s in rec.steps
                ] if not rec.custom else "custom",
                "stored": stored,
                "as_seen_by_tool": rec.as_seen_by_tool,
            })

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "experiment_fingerprint": self.fingerprint,
            "framework_commit": self.commit,
            "tool": {
                "name": self.tool_name,
                "identifier": self.tool_identifier,
                "params": _scrub_paths(_jsonable(
                    {k: v for k, v in self.tool_params.items() if k not in _DERIVED_PARAM_KEYS}
                ), self.project_root),
            },
            "setting_key": self.setting_key,
            "captures": 1,
            "tool_invocation": None,
            "input_unchanged_after_run": None,
            "entries": entries,
        }
        # written last: the manifest never exists without the files it names
        with open(os.path.join(tmp, MANIFEST_NAME), "w") as f:
            json.dump(manifest, f, indent=1)
        os.makedirs(os.path.dirname(self.entry_dir), exist_ok=True)
        os.rename(tmp, self.entry_dir)

    def _verify_repeat(self, records: List[ConversionRecord]) -> None:
        """A repeat run re-converted the same inputs; hashes must match."""
        manifest = self._read_manifest()
        # _safe() is not injective ("Tool 1" and "Tool_1" share a directory):
        # never verify against another tool's or setting's manifest
        stored_tool = manifest.get("tool", {})
        if (manifest.get("setting_key") != self.setting_key
                or stored_tool.get("name") != self.tool_name
                or stored_tool.get("identifier") != self.tool_identifier):
            raise ProvenanceError(
                f"provenance directory collision: {self.entry_dir} already holds the "
                f"provenance of {stored_tool.get('name')!r} @ {manifest.get('setting_key')!r}, "
                f"but this run is {self.tool_name!r} @ {self.setting_key!r}; tool names and "
                f"setting keys must not collide after sanitization"
            )
        by_kind = {e["kind"]: e for e in manifest["entries"]}
        for rec in records:
            entry = by_kind.get(rec.kind)
            if entry is None:
                raise ProvenanceError(
                    f"repeat run of {self.tool_name} @ {self.setting_key} produced a "
                    f"new input kind '{rec.kind}' absent from the stored provenance"
                )
            # source first: a mutated canonical file must be reported as such,
            # not misdiagnosed as a nondeterministic converter
            source_abs = self._source_abs(rec)
            expected_source = (entry.get("source") or {}).get("sha256")
            if expected_source is not None:
                current_source = _sha256(source_abs) if os.path.isfile(source_abs) else None
                if current_source != expected_source:
                    raise ProvenanceError(
                        f"canonical {rec.kind} of {self.tool_name} @ {self.setting_key} "
                        f"changed between repeats (a run modified its own input?): "
                        f"{str(current_source)[:12]}… now vs {expected_source[:12]}… stored"
                    )
            if rec.converted and entry.get("stored"):
                current = _sha256(self._tool_input_abs(rec))
                expected = entry["stored"]["sha256"]
                if current != expected:
                    raise ProvenanceError(
                        f"nondeterministic conversion detected: converted {rec.kind} of "
                        f"{self.tool_name} @ {self.setting_key} hashes {current[:12]}… on "
                        f"this repeat but {expected[:12]}… was stored"
                    )
        manifest["captures"] = int(manifest.get("captures", 1)) + 1
        _atomic_write_json(self.manifest_path, manifest)

    # -- after preprocessing ------------------------------------------------

    def record_invocation(self, command: List[str]) -> None:
        """Record the tool command line (best effort, never fatal)."""
        try:
            manifest = self._read_manifest()
            cmd = [str(c) for c in command]
            if manifest.get("tool_invocation") is None:
                manifest["tool_invocation"] = cmd
                _atomic_write_json(self.manifest_path, manifest)
        except Exception as e:
            print(f"provenance: could not record invocation for {self.tool_name}: {e}")

    def verify_after_run(self, records: List[ConversionRecord]) -> None:
        """Re-hash the inputs after the run; the container mounts the setting
        folder read-write, so a tool could in principle mutate its own input.
        Records a flag, never aborts (the run already happened)."""
        try:
            manifest = self._read_manifest()
            by_kind = {e["kind"]: e for e in manifest["entries"]}
            unchanged = True
            for rec in records:
                entry = by_kind.get(rec.kind)
                if entry is None:
                    unchanged = False
                    continue
                # both endpoints: the file the tool read AND the canonical
                # source next to it (the whole setting folder is mounted rw)
                checks = []
                if entry.get("stored"):
                    checks.append((self._tool_input_abs(rec), entry["stored"]["sha256"]))
                expected_source = (entry.get("source") or {}).get("sha256")
                if expected_source is not None:
                    checks.append((self._source_abs(rec), expected_source))
                for path, expected in checks:
                    if not os.path.isfile(path) or _sha256(path) != expected:
                        unchanged = False
            previous = manifest.get("input_unchanged_after_run")
            manifest["input_unchanged_after_run"] = (
                unchanged if previous is None else (previous and unchanged)
            )
            _atomic_write_json(self.manifest_path, manifest)
            if not unchanged:
                print(f"provenance WARNING: {self.tool_name} @ {self.setting_key} "
                      f"modified or removed its own input during the run")
        except Exception as e:
            print(f"provenance: post-run verification failed for {self.tool_name}: {e}")

    def _read_manifest(self) -> Dict[str, Any]:
        with open(self.manifest_path, "r") as f:
            return json.load(f)
