"""Preview-only isolation of malformed scalar records, without inventing facts.

All root-level, condition and series errors remain fatal. Invalid records are
retained verbatim in the quarantine report; valid siblings are not rewritten.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError
from schema.polymer_schema import PropertyStageResponse


def isolate_invalid_scalar_records(payload: dict[str, Any]):
    try:
        PropertyStageResponse.model_validate(payload)
        return payload, []
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        indices: dict[str, set[int]] = {}
        for error in errors:
            loc = error['loc']
            if (len(loc) < 2 or loc[0] not in {'properties', 'unresolved_properties'}
                    or not isinstance(loc[1], int)):
                raise
            indices.setdefault(loc[0], set()).add(loc[1])
        cleaned = deepcopy(payload)
        quarantine = []
        for collection, bad in indices.items():
            quarantine.extend({
                'collection': collection, 'original_index': index,
                'record': deepcopy(payload[collection][index]),
                'errors': [e for e in errors if e['loc'][:2] == (collection, index)],
                'decision': 'quarantined_not_published',
            } for index in sorted(bad))
            cleaned[collection] = [v for i, v in enumerate(cleaned[collection]) if i not in bad]
        if not any(cleaned.get(k) for k in ('properties', 'unresolved_properties', 'property_series')):
            raise  # No valid fact survived; retain the explicit degraded status.
        # Do not silently discard cross-reference or whole-response failures.
        PropertyStageResponse.model_validate(cleaned)
        return cleaned, quarantine


def is_degraded_empty_shell(document: Any) -> bool:
    return any(w.get('code') == 'preview_degraded_empty_shell'
               for w in document.warnings if isinstance(w, dict))
