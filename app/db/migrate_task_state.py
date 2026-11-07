"""Migração controlada, idempotente e não-destrutiva de system/task-state.json
para PostgreSQL (TaskRepository).

Uso:
    python -m app.db.migrate_task_state --target test
    python -m app.db.migrate_task_state --target test --dry-run
    python -m app.db.migrate_task_state --target production   # exige
        confirmação explícita e um banco operacional Jarvis já configurado

O JSON de origem NUNCA é escrito/apagado. Regras:
- lê o JSON, valida TODOS os registros antes de gravar qualquer coisa;
- se qualquer registro for inválido, nada é gravado (rollback total);
- status legado `timeout` -> Task.status=failed, failure_code="timeout";
- rerun é idempotente: registros já existentes (mesmo id) são contados e
  pulados, nunca duplicados;
- roda dentro de uma única transação quando o repository suporta isso
  (ver PostgresTaskRepository via app.db.uow.unit_of_work) — uma falha
  inesperada no meio do lote desfaz o lote inteiro.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, get_setting
from app.db.models import TaskStatus
from app.db.repositories import TaskRepository

DEFAULT_JSON_PATH = PROJECT_ROOT / "system" / "task-state.json"

# status legado -> (TaskStatus novo, failure_code)
_STATUS_MAP: dict[str, tuple[TaskStatus, str | None]] = {
    "pending": (TaskStatus.PENDING, None),
    "running": (TaskStatus.FAILED, "interrupted_by_migration"),
    "completed": (TaskStatus.COMPLETED, None),
    "failed": (TaskStatus.FAILED, None),
    "cancelled": (TaskStatus.CANCELLED, None),
    "timeout": (TaskStatus.FAILED, "timeout"),
    # sinônimos legados que só existiriam se o JSON nunca tivesse sido
    # re-persistido após um restart (TaskManager normalmente já normaliza
    # isso em memória via _load_and_reconcile, mas o migrador lê o arquivo
    # bruto diretamente, então trata os mesmos casos por segurança).
    "queued": (TaskStatus.PENDING, None),
    "interrupted": (TaskStatus.FAILED, "interrupted_by_restart"),
}


class MigrationValidationError(ValueError):
    """Um registro do JSON legado não pôde ser validado/mapeado."""


@dataclass(frozen=True)
class MigrationReport:
    source_path: str
    source_checksum_sha256: str
    total_read: int
    total_inserted: int
    total_already_existing: int
    total_timeouts_mapped: int
    total_failures: int
    failures: tuple[str, ...]
    dry_run: bool
    started_at: str
    finished_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_checksum_sha256": self.source_checksum_sha256,
            "total_read": self.total_read,
            "total_inserted": self.total_inserted,
            "total_already_existing": self.total_already_existing,
            "total_timeouts_mapped": self.total_timeouts_mapped,
            "total_failures": self.total_failures,
            "failures": list(self.failures),
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_datetime(value: Any, *, field_name: str, task_id: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MigrationValidationError(f"{task_id}: campo {field_name} não é string ISO.")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise MigrationValidationError(
            f"{task_id}: campo {field_name} não é ISO 8601 válido: {value!r}."
        ) from error


def _validate_and_map(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise MigrationValidationError(f"registro não é um objeto: {item!r}")

    task_id = item.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise MigrationValidationError(f"registro sem task_id válido: {item!r}")
    try:
        record_id = uuid.UUID(task_id)
    except ValueError as error:
        raise MigrationValidationError(f"{task_id}: task_id não é um UUID válido.") from error

    task_type = item.get("type")
    if not isinstance(task_type, str) or not task_type:
        raise MigrationValidationError(f"{task_id}: campo type ausente/inválido.")

    legacy_status = item.get("status")
    if legacy_status not in _STATUS_MAP:
        raise MigrationValidationError(
            f"{task_id}: status legado desconhecido: {legacy_status!r}."
        )
    status, failure_code = _STATUS_MAP[legacy_status]

    created_at = _parse_datetime(item.get("created_at"), field_name="created_at", task_id=task_id)
    if created_at is None:
        raise MigrationValidationError(f"{task_id}: created_at é obrigatório.")

    result = item.get("result")
    if result is not None and not isinstance(result, dict):
        raise MigrationValidationError(f"{task_id}: campo result não é objeto/null.")

    error_text = item.get("error")
    if error_text is not None and not isinstance(error_text, str):
        raise MigrationValidationError(f"{task_id}: campo error não é string/null.")

    return {
        "id": record_id,
        "type": task_type,
        "description": item.get("description"),
        "executor": item.get("executor"),
        "display_name": item.get("display_name"),
        "agent_id": item.get("agent_id"),
        "status": status,
        "failure_code": failure_code,
        "created_at": created_at,
        "started_at": _parse_datetime(
            item.get("started_at"), field_name="started_at", task_id=task_id
        ),
        "finished_at": _parse_datetime(
            item.get("finished_at"), field_name="finished_at", task_id=task_id
        ),
        "result_json": result,
        "error_text": error_text,
        "was_timeout": legacy_status == "timeout",
    }


def migrate(
    json_path: Path,
    *,
    task_repository: TaskRepository,
    dry_run: bool = False,
) -> MigrationReport:
    started_at = datetime.now(timezone.utc).isoformat()
    checksum = _checksum(json_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    items = payload.get("tasks", []) if isinstance(payload, dict) else []

    failures: list[str] = []
    mapped: list[dict[str, Any]] = []
    for item in items:
        try:
            mapped.append(_validate_and_map(item))
        except MigrationValidationError as error:
            failures.append(str(error))

    total_inserted = 0
    total_already_existing = 0
    total_timeouts_mapped = 0

    # Qualquer registro inválido aborta o lote inteiro: nada é gravado.
    if not failures:
        for record in mapped:
            already_exists = task_repository.get(record["id"]) is not None
            if already_exists:
                total_already_existing += 1
                continue
            if not dry_run:
                task_repository.create(
                    type=record["type"],
                    status=record["status"],
                    description=record["description"],
                    executor=record["executor"],
                    display_name=record["display_name"],
                    agent_id=record["agent_id"],
                    id=record["id"],
                    created_at=record["created_at"],
                    started_at=record["started_at"],
                    finished_at=record["finished_at"],
                    result_json=record["result_json"],
                    error_text=record["error_text"],
                    failure_code=record["failure_code"],
                )
                total_inserted += 1
            if record["was_timeout"]:
                total_timeouts_mapped += 1

    finished_at = datetime.now(timezone.utc).isoformat()

    return MigrationReport(
        source_path=str(json_path),
        source_checksum_sha256=checksum,
        total_read=len(items),
        total_inserted=total_inserted,
        total_already_existing=total_already_existing,
        total_timeouts_mapped=total_timeouts_mapped,
        total_failures=len(failures),
        failures=tuple(failures),
        dry_run=dry_run,
        started_at=started_at,
        finished_at=finished_at,
    )


def _resolve_database_url(target: str) -> str:
    key = "JARVIS_DATABASE_URL" if target == "production" else "JARVIS_TEST_DATABASE_URL"
    url = get_setting(key)
    if not url:
        raise SystemExit(f"{key} não configurada; nada foi migrado.")
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("test", "production"),
        required=True,
        help="test -> JARVIS_TEST_DATABASE_URL; production -> JARVIS_DATABASE_URL "
        "(nunca usa jarvis_test como produção).",
    )
    parser.add_argument(
        "--json-path",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help="Caminho do system/task-state.json de origem.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida e reporta sem gravar nada no banco.",
    )
    args = parser.parse_args(argv)

    if args.target == "production" and not args.dry_run:
        confirmation = input(
            "Isso vai migrar dados para o banco OPERACIONAL do Jarvis "
            "(JARVIS_DATABASE_URL). Digite 'migrar producao' para confirmar: "
        )
        if confirmation.strip() != "migrar producao":
            print("Cancelado.", file=sys.stderr)
            return 1

    database_url = _resolve_database_url(args.target)

    from app.db.engine import create_database_engine, create_session_factory
    from app.db.repositories_postgres import PostgresTaskRepository
    from app.db.uow import unit_of_work

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)

    if args.dry_run:
        repository = PostgresTaskRepository(session_factory=session_factory)
        report = migrate(args.json_path, task_repository=repository, dry_run=True)
    else:
        with unit_of_work(session_factory) as session:
            repository = PostgresTaskRepository(session=session)
            report = migrate(args.json_path, task_repository=repository, dry_run=False)

    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.total_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
