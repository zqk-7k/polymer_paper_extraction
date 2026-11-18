"""Persist application-level LLM requests without client configuration or headers."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4


def content_hash(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


class RequestTrace:
    def __init__(self, directory: Path, *, document_id: str, inputs: dict, mode: str = "live"):
        self.directory = directory
        self.trace_id = uuid4().hex
        self.data = {
            "schema_version": "stage4_request_trace.v1", "trace_id": self.trace_id,
            "document_id": document_id, "mode": mode, "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Application call_json attempts; transport retries are not separately captured.",
            "input_model_hashes": {name: content_hash(value) for name, value in inputs.items()},
            "attempts": [],
        }
        self.save()

    def save(self):
        archive = self.directory / "stage4_request_traces" / f"{self.trace_id}.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        for path in (archive, self.directory / "stage4_request_trace.json"):
            temp = path.with_suffix(f".{self.trace_id}.tmp")
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            temp.replace(path)

    def call_json(self, client, system_prompt: str, user_message: str, *, max_tokens: int):
        request = {"system_prompt": system_prompt, "user_message": user_message, "max_tokens": max_tokens}
        attempt = {"attempt": len(self.data["attempts"]) + 1, "status": "request_prepared",
                   "started_at": datetime.now(timezone.utc).isoformat(),
                   "request": request, "request_sha256": content_hash(request)}
        self.data["attempts"].append(attempt)
        self.save()  # A terminated process must still leave the submitted input.
        previous_raw = getattr(client, "last_raw_response", None)
        try:
            response = client.call_json(system_prompt, user_message, max_tokens=max_tokens)
            attempt.update(status="response_received", parsed_response=deepcopy(response.data),
                           parsed_response_sha256=content_hash(response.data))
            return response
        except Exception as exc:
            # Exception text may contain URLs, headers or credentials.
            attempt.update(status="call_failed", error_type=type(exc).__name__)
            raise
        finally:
            attempt["finished_at"] = datetime.now(timezone.utc).isoformat()
            raw = getattr(client, "last_raw_response", None)
            if raw is not None and raw is not previous_raw:
                attempt["raw_response"] = {"provider": raw.provider, "model": raw.model,
                                           "finish_reason": raw.finish_reason, "content": raw.content}
                attempt["raw_response_sha256"] = content_hash(attempt["raw_response"])
            self.save()

    def finish(self, *, output: dict | None = None, error_type: str | None = None):
        self.data["finished_at"] = datetime.now(timezone.utc).isoformat()
        if output is not None:
            self.data.update(status="completed", output_sha256=content_hash(output),
                             stage_status=output.get("provenance", {}).get("status"))
        else:
            self.data.update(status="failed", error_type=error_type)
        self.save()
