"""Read local metadata without accepting raw prompts, code, or outputs."""

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, List

from .schemas import Policy, TaskTrace, ValidationError
from .privacy import PrivacyError, ensure_safe


CSV_FIELDS = (
    "trace_id", "task_id", "timestamp", "task_type", "risk_tags",
    "selected_model", "model_tier", "input_tokens", "output_tokens",
    "cost_usd", "latency_ms", "tests_passed", "developer_override", "score",
    "is_baseline", "required_tools", "context_tokens",
)


def _unique_object(pairs: Any) -> Any:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("Duplicate JSON field.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValidationError("Non-finite JSON numbers are not accepted.")


def parse_json(value: str) -> Any:
    try:
        return json.loads(value, parse_float=Decimal, parse_constant=_invalid_constant,
                          object_pairs_hook=_unique_object)
    except json.JSONDecodeError:
        raise ValidationError("Invalid JSON.") from None


def load_policy(path: Path) -> Policy:
    ensure_safe(str(path))
    return Policy.from_dict(parse_json(path.read_text(encoding="utf-8")))


def _csv_boolean(value: str, nullable: bool = False) -> Any:
    if nullable and value == "":
        return None
    if value not in ("true", "false"):
        raise ValidationError("CSV booleans must be true or false; nullable values may be empty.")
    return value == "true"


def _csv_trace(row: Any) -> TaskTrace:
    if None in row or any(value is None for value in row.values()):
        raise ValidationError("CSV row has the wrong number of columns.")
    data = {key: row[key] for key in CSV_FIELDS[:11]}
    data["task_type"] = row["task_type"] or None
    data["risk_tags"] = parse_json(row["risk_tags"])
    data["required_tools"] = parse_json(row["required_tools"])
    for field in ("input_tokens", "output_tokens", "latency_ms"):
        try:
            data[field] = int(row[field])
        except ValueError:
            raise ValidationError(f"{field} must be an integer.") from None
    try:
        data["context_tokens"] = int(row["context_tokens"]) if row["context_tokens"] else None
    except ValueError:
        raise ValidationError("context_tokens must be an integer or empty.") from None
    data["is_baseline"] = _csv_boolean(row["is_baseline"])
    data["outcome"] = {
        "tests_passed": _csv_boolean(row["tests_passed"], nullable=True),
        "developer_override": _csv_boolean(row["developer_override"]),
        "score": row["score"] or None,
    }
    return TaskTrace.from_dict(data)


def validate_dataset(traces: List[TaskTrace], repeated: bool = False) -> List[TaskTrace]:
    if not traces:
        raise ValidationError("The dataset must contain at least one task.")
    trace_ids = set()
    task_models = set()
    tasks = {}
    task_metadata = {}
    for trace in traces:
        # Validate direct Python callers as well as file imports before any report is produced.
        TaskTrace.from_dict(trace.to_dict())
        if trace.trace_id in trace_ids:
            raise ValidationError("trace_id must be unique across the dataset.")
        trace_ids.add(trace.trace_id)
        pair = (trace.task_id, trace.sample_id if repeated else "single", trace.selected_model)
        if pair in task_models:
            raise ValidationError("Duplicate task/model outcome; repeated evaluation requires unique sample_id values.")
        task_models.add(pair)
        key = (trace.task_id, trace.sample_id) if repeated else trace.task_id
        tasks.setdefault(key, []).append(trace)
        task_metadata.setdefault(trace.task_id, trace.task_metadata())
        if trace.task_metadata() != task_metadata[trace.task_id]:
            raise ValidationError("All samples of a task must share the same task metadata.")
    for evaluations in tasks.values():
        if sum(trace.is_baseline for trace in evaluations) != 1:
            raise ValidationError("Each task must have exactly one baseline row.")
        if any(trace.task_metadata() != evaluations[0].task_metadata() for trace in evaluations):
            raise ValidationError("All model outcomes for a task must share the same task metadata.")
    return traces


def load_traces(path: Path, repeated: bool = False) -> List[TaskTrace]:
    ensure_safe(str(path))
    traces = []
    with path.open(encoding="utf-8", newline="") as stream:
        if path.suffix.lower() == ".jsonl":
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    traces.append(TaskTrace.from_dict(parse_json(line)))
                except (ValidationError, PrivacyError) as error:
                    raise type(error)(f"JSONL line {line_number}: {error}") from None
        elif path.suffix.lower() == ".csv":
            try:
                reader = csv.DictReader(stream, strict=True)
                if tuple(reader.fieldnames or ()) != CSV_FIELDS:
                    raise ValidationError("CSV columns must match the documented canonical order.")
                for line_number, row in enumerate(reader, start=2):
                    try:
                        traces.append(_csv_trace(row))
                    except (ValidationError, PrivacyError) as error:
                        raise type(error)(f"CSV row {line_number}: {error}") from None
            except csv.Error:
                raise ValidationError("Invalid CSV formatting or unsupported field size.") from None
        else:
            raise ValidationError("Trace input must be a .jsonl or .csv file.")
    return validate_dataset(traces, repeated=repeated)
