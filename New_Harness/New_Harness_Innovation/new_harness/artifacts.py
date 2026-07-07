from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import time
from typing import Any

from .schemas import SCHEMA_VERSION


@dataclass(frozen=True)
class ArtifactValidationResult:
    path: Path
    valid: bool
    reason: str | None = None


class RunArtifacts:
    """Filesystem-backed JSON artifact store for a single run."""

    def __init__(self, root: Path, run_id: str) -> None:
        self.root = Path(root)
        self.run_id = run_id
        self.run_dir = self.root / "runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.run_dir / "config.json"
        self.events_path = self.run_dir / "events.jsonl"

    def artifact_path(self, relative: str) -> Path:
        return self.run_dir / relative

    def write_json(self, relative: str, payload: dict[str, Any]) -> Path:
        path = self.artifact_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = dict(payload)
        normalized["schema_version"] = SCHEMA_VERSION
        path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def read_json(self, relative: str) -> dict[str, Any]:
        path = self.artifact_path(relative)
        return json.loads(path.read_text(encoding="utf-8"))

    def write_text(self, relative: str, content: str) -> Path:
        path = self.artifact_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_text(self, relative: str) -> str:
        return self.artifact_path(relative).read_text(encoding="utf-8")

    def append_event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        event = {
            "event_type": event_type,
            "run_id": self.run_id,
            "timestamp_ns": time.time_ns(),
            **fields,
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def validate_json_artifact(
        self, relative: str, required_fields: tuple[str, ...] = ()
    ) -> ArtifactValidationResult:
        path = self.artifact_path(relative)
        if not path.exists():
            return ArtifactValidationResult(path=path, valid=False, reason="missing")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return ArtifactValidationResult(path=path, valid=False, reason="invalid_json")

        if not isinstance(payload, dict):
            return ArtifactValidationResult(path=path, valid=False, reason="not_object")

        if payload.get("schema_version") != SCHEMA_VERSION:
            return ArtifactValidationResult(
                path=path,
                valid=False,
                reason="schema_version_mismatch",
            )

        missing_fields = [field for field in required_fields if field not in payload]
        if missing_fields:
            return ArtifactValidationResult(
                path=path,
                valid=False,
                reason=f"missing_fields:{','.join(missing_fields)}",
            )

        return ArtifactValidationResult(path=path, valid=True)

    def validate_artifact(
        self, relative: str, required_fields: tuple[str, ...] = ()
    ) -> ArtifactValidationResult:
        """Validate JSON artifacts by schema and plain artifacts by existence."""

        if Path(relative).suffix == ".json":
            return self.validate_json_artifact(relative, required_fields)

        path = self.artifact_path(relative)
        if not path.exists():
            return ArtifactValidationResult(path=path, valid=False, reason="missing")
        if not path.is_file():
            return ArtifactValidationResult(path=path, valid=False, reason="not_file")
        if required_fields:
            return ArtifactValidationResult(
                path=path,
                valid=False,
                reason="required_fields_not_supported",
            )
        return ArtifactValidationResult(path=path, valid=True)

    def preserve_failed_partials(
        self,
        stage_name: str,
        artifact_relatives: tuple[str, ...],
        *,
        error: str | None = None,
    ) -> Path:
        failed_root = self.run_dir / "failed-partials" / stage_name / str(time.time_ns())
        preserved_any = False

        for relative in artifact_relatives:
            source = self.artifact_path(relative)
            if not source.exists():
                continue
            destination = failed_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            preserved_any = True

        marker = failed_root / "error.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "stage_name": stage_name,
                    "run_id": self.run_id,
                    "error": error,
                    "preserved_any": preserved_any,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return failed_root
