"""Revalidate traced Stage4 objects without accepting unrelated failed objects."""
from collections import Counter
from typing import get_args, get_origin

from pydantic import BaseModel

from schema.polymer_schema import (
    MeasurementConditionCandidate, PropertyObservationCandidate, PropertySeriesCandidate,
    UnresolvedPropertyCandidate,
)
from stages.request_trace import content_hash


def object_key(series, item):
    return content_hash({"series": {k: v for k, v in series.items() if k != "points"}, "item": item})


def _project(value, annotation):
    """Remove materialized metadata (bbox/page etc.), preserving candidate fields."""
    origin, args = get_origin(annotation), get_args(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel) and isinstance(value, dict):
        return {k: _project(v, annotation.model_fields[k].annotation)
                for k, v in value.items() if k in annotation.model_fields}
    if origin is list and isinstance(value, list):
        return [_project(v, args[0]) for v in value]
    if origin is dict and isinstance(value, dict):
        return {k: _project(v, args[1]) for k, v in value.items()}
    if args and value is not None:
        for arg in args:
            if isinstance(arg, type) and issubclass(arg, BaseModel) and isinstance(value, dict):
                return _project(value, arg)
    return value


def validate_objects(stage4, source, entities, process):
    from stages.stage4_property import (
        _normalize_property, _normalize_unresolved, _normalize_series, _normalize_condition,
        load_property_vocabulary, DEFAULT_VOCABULARY_PATH,
    )
    vocabulary, _ = load_property_vocabulary(DEFAULT_VOCABULARY_PATH)
    block_map = {b.block_id: b for b in source.elements}
    sample_ids = {s.sample_id for s in process.samples}
    entity_ids = {e.entity_id for e in entities.polymer_entities}
    accepted, rejected = [], []
    conditions = stage4.get("measurement_conditions", [])

    def unchanged(before, after):
        def meaning(value):
            if isinstance(value, dict):
                return {k: meaning(v) for k, v in value.items() if v is not None
                        and k not in {"evidence", "confidence", "coverage", "other_condition_evidence"}}
            if isinstance(value, list):
                return [meaning(v) for v in value]
            return value
        if meaning(before.model_dump(mode="json")) != meaning(after.model_dump(mode="json")):
            raise ValueError("semantic_normalization_changed_record_requires_replay")

    def validate(series, item, collection, oid):
        key = object_key(series, item)
        try:
            for value in (series, item):
                if value.get("sample_id") and value["sample_id"] not in sample_ids:
                    raise ValueError("unknown_sample_reference")
                if value.get("entity_id") and value["entity_id"] not in entity_ids:
                    raise ValueError("unknown_entity_reference")
            if series:
                if item.get("coverage_status") != "covered":
                    raise ValueError("point_not_covered")
                # Keep every series-level dependency. Only sibling points are independent.
                data = {**series, "points": [item], "coverage": None}
                # A multi-subject container may omit its own subject. The temporary
                # one-point validation view uses only that point's explicit IDs;
                # it never writes an inferred parent identity back to the output.
                if not data.get("sample_id") and not data.get("entity_id"):
                    data.update(sample_id=item.get("sample_id"), entity_id=item.get("entity_id"),
                                sample_resolution_status=item.get("sample_resolution_status", "unresolved"))
                candidate = PropertySeriesCandidate.model_validate(_project(data, PropertySeriesCandidate))
                normalized = _normalize_series(candidate, block_map, vocabulary, allow_incomplete_coverage=True)
                unchanged(candidate, normalized)
            elif collection == "properties":
                if item.get("observation_role") == "aggregate":
                    raise ValueError("aggregate_requires_series_proof")
                candidate = PropertyObservationCandidate.model_validate(_project(item, PropertyObservationCandidate))
                matching = [c for c in conditions if c.get("condition_id") == candidate.measurement_condition_id]
                if len(matching) != 1:
                    raise ValueError("condition_reference_not_unique")
                condition = MeasurementConditionCandidate.model_validate(_project(matching[0], MeasurementConditionCandidate))
                unchanged(condition, _normalize_condition(condition, block_map, [candidate])[0])
                unchanged(candidate, _normalize_property(candidate, block_map, vocabulary)[0])
            elif collection == "unresolved_properties":
                if item.get("observation_role") == "aggregate":
                    raise ValueError("aggregate_requires_series_proof")
                candidate = UnresolvedPropertyCandidate.model_validate(_project(item, UnresolvedPropertyCandidate))
                unchanged(candidate, _normalize_unresolved(candidate, block_map)[0])
            else:
                raise ValueError("specialized_object_requires_separate_semantic_proof")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            rejected.append({"collection": collection, "object_id": oid, "object_sha256": key,
                             "reason": str(exc)[:800], "error_type": type(exc).__name__})
        else:
            accepted.append(key)

    for collection, id_field in (("properties", "property_id"), ("unresolved_properties", "unresolved_id"),
                                 ("specialized_property_observations", "specialized_id")):
        counts = Counter(v.get(id_field) for v in stage4.get(collection, []))
        for item in stage4.get(collection, []):
            if counts[item.get(id_field)] != 1:
                rejected.append({"collection": collection, "object_id": item.get(id_field), "reason": "duplicate_object_id"})
            else:
                validate({}, item, collection, item.get(id_field))
    series_counts = Counter(s.get("series_id") for s in stage4.get("property_series", []))
    for series in stage4.get("property_series", []):
        point_counts = Counter(p.get("point_id") for p in series.get("points", []))
        for point in series.get("points", []):
            oid = f"{series.get('series_id')}:{point.get('point_id')}"
            if series_counts[series.get("series_id")] != 1 or point_counts[point.get("point_id")] != 1:
                rejected.append({"collection": "property_series", "object_id": oid, "reason": "duplicate_object_id"})
            else:
                validate(series, point, "property_series", oid)
    return {"schema_version": "stage4_object_semantics.v1", "accepted_object_hashes": sorted(set(accepted)),
            "accepted_count": len(accepted), "rejected_count": len(rejected), "rejected": rejected}
