from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Iterator, Self

from pydantic import BaseModel, BeforeValidator, RootModel, computed_field, field_validator, model_validator

from cli import config
from services.browser import capture_dashboard_snapshot
from services.grafana import GrafanaApi, Snapshot

MAX_PANELS_IN_ERROR = 8


def _resolve_directory(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


DirectoryPath = Annotated[Path, BeforeValidator(_resolve_directory)]


class ExportParams(BaseModel):
    name: str
    directory: DirectoryPath
    time_from: str
    time_to: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dashboard_url(self) -> str:
        return (
            f"{config.GRAFANA_URL}/d/{config.DASHBOARD_UID}/"
            f"?from={self.time_from}&to={self.time_to}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def output_file_path(self) -> Path:
        return self.directory / f"{self.name}.json"

    def write_dashboard(self, dashboard: dict[str, Any]) -> Path:
        dashboard["title"] = self.name
        path = self.output_file_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


class ExportResult(BaseModel):
    url: str
    key: str
    file: str
    name: str
    skipped: bool = False

    @classmethod
    def from_grafana_snapshot(
        cls,
        name: str,
        output_file: Path,
        snapshot: Snapshot,
        skipped: bool = False,
    ) -> ExportResult:
        return cls(
            url=snapshot.url,
            key=snapshot.key,
            file=str(output_file),
            name=name,
            skipped=skipped,
        )


class ExportDashboard(RootModel[dict[str, Any]]):
    def ensure_metrics(self) -> dict[str, Any]:
        missing = _export_panel_titles_missing_metrics(self.root)
        if missing:
            shown = ", ".join(missing[:MAX_PANELS_IN_ERROR])
            rest = (
                f" (+{len(missing) - MAX_PANELS_IN_ERROR} more)"
                if len(missing) > MAX_PANELS_IN_ERROR
                else ""
            )
            raise RuntimeError(f"snapshot missing metric data for panels: {shown}{rest}")
        return self.root


def _export_panel_titles_missing_metrics(dashboard: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for panel in _export_iterate_panels(dashboard.get("panels") or []):
        if not panel.get("targets"):
            continue
        title = str(panel.get("title") or panel.get("id") or "unknown")
        for target in panel.get("targets") or []:
            if target.get("hide"):
                continue
            if _export_target_has_metric_data(target):
                continue
            if _export_target_expects_metric_data(target):
                missing.append(title)
                break
    return missing


def _export_iterate_panels(panels: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for panel in panels:
        if panel.get("type") == "row":
            yield from _export_iterate_panels(panel.get("panels") or [])
        else:
            yield panel


def _export_target_has_metric_data(target: dict[str, Any]) -> bool:
    frames = target.get("snapshot")
    if not isinstance(frames, list):
        return False
    for frame in frames:
        values = (frame.get("data") or {}).get("values") or []
        if any(isinstance(column, list) and column for column in values):
            return True
    return False


def _export_target_expects_metric_data(target: dict[str, Any]) -> bool:
    return bool(
        target.get("queryType") == "snapshot"
        or target.get("expr")
        or target.get("datasource")
    )


class ImportParams(BaseModel):
    directory: DirectoryPath

    @field_validator("directory", mode="after")
    @classmethod
    def directory_must_exist(cls, value: Path) -> Path:
        if not value.is_dir():
            raise ValueError(f"not a directory: {value}")
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def json_file_paths(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    @model_validator(mode="after")
    def must_have_json_files(self) -> Self:
        if not self.json_file_paths:
            raise RuntimeError(f"no json files in {self.directory}")
        return self


class ImportDashboard(BaseModel):
    path: Path
    name: str
    body: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def load_json(cls, value: object) -> object:
        if not isinstance(value, (str, Path)):
            return value
        path = Path(value)
        body = json.loads(path.read_text(encoding="utf-8"))
        return {"path": path, "name": body.get("title") or path.stem, "body": body}


class ImportEntry(BaseModel):
    file: str
    name: str
    key: str
    url: str

    @classmethod
    def from_grafana_snapshot(
        cls, path: Path, name: str, snapshot: Snapshot
    ) -> ImportEntry:
        return ImportEntry(
            file=str(path),
            name=name,
            key=snapshot.key,
            url=snapshot.url,
        )


class ImportResult(BaseModel):
    imported: int
    skipped: int
    snapshots: list[ImportEntry]
    skipped_names: list[str]


class SnapshotService:
    def __init__(self) -> None:
        self.grafana_api = GrafanaApi()

    def snapshot_export(self, params: ExportParams) -> ExportResult:
        draft_snapshot_key, dashboard = self._export_capture_draft_snapshot(params)
        output_file = params.write_dashboard(dashboard)
        self.grafana_api.delete_snapshot(draft_snapshot_key)
        return self._export_register_snapshot(params, dashboard, output_file)

    def snapshot_import(self, params: ImportParams) -> ImportResult:
        imported: list[ImportEntry] = []
        skipped_names: list[str] = []
        for json_file_path in params.json_file_paths:
            dashboard_file = ImportDashboard.model_validate(json_file_path)
            if self.grafana_api.get_snapshot(dashboard_file.name):
                skipped_names.append(dashboard_file.name)
                continue
            created_snapshot = self.grafana_api.create_snapshot(
                dashboard_file.body, dashboard_file.name
            )
            imported.append(
                ImportEntry.from_grafana_snapshot(
                    dashboard_file.path, dashboard_file.name, created_snapshot
                )
            )
        return ImportResult(
            imported=len(imported),
            skipped=len(skipped_names),
            snapshots=imported,
            skipped_names=skipped_names,
        )

    def _export_capture_draft_snapshot(
        self, params: ExportParams
    ) -> tuple[str, dict[str, Any]]:
        published_snapshot = capture_dashboard_snapshot(params.dashboard_url)
        dashboard_json = self.grafana_api.get_dashboard(published_snapshot.key)
        try:
            dashboard = ExportDashboard(dashboard_json).ensure_metrics()
        except RuntimeError:
            self.grafana_api.delete_snapshot(published_snapshot.key)
            raise
        return published_snapshot.key, dashboard

    def _export_register_snapshot(
        self,
        params: ExportParams,
        dashboard: dict[str, Any],
        output_file: Path,
    ) -> ExportResult:
        existing_snapshot = self.grafana_api.get_snapshot(params.name)
        if existing_snapshot:
            return ExportResult.from_grafana_snapshot(
                params.name, output_file, existing_snapshot, skipped=True
            )
        created_snapshot = self.grafana_api.create_snapshot(dashboard, params.name)
        return ExportResult.from_grafana_snapshot(
            params.name, output_file, created_snapshot
        )
