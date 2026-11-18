import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from llm_client import (
    DEFAULT_CONFIG_PATH,
    LLMCallRecord,
    LLMJSONResponse,
    LLMRawResponse,
    LLMTokenUsage,
    ResolvedLLMConfig,
    load_pipeline_config,
)
from prompt_loader import PromptLoader
from schema.polymer_schema import (
    CharacterizationStageResponse,
    SpecializedPropertyCandidate,
    Stage5PropertyCandidate,
    Stage0Document,
    Stage0Element,
    Stage2Document,
    Stage3Document,
    Stage4Document,
)
from tests.helpers import add_model_confidence
from stages.stage5_characterization import (
    DEFAULT_VOCABULARY_PATH,
    Stage5Error,
    _failure_replay_client,
    _method_names_for_raw,
    _normalize_stage5_property,
    _materialize_specialized,
    _preview_numeric_surface_match,
    _collect_unscoped_preview_candidates,
    _repair_candidate_response_payload,
    _repair_preview_table_locators,
    _resolve_vocabulary_path,
    _stage5_property_dedupe_key,
    extract_characterizations,
    load_characterization_vocabulary,
    plan_shards,
    run_stage5,
    select_context_blocks,
)
from stages.specialized_vocabulary import get_specialized_vocabulary
import stages.stage5_characterization as stage5_module


class VocabularyPathResolutionTests(unittest.TestCase):
    def test_directory_external_method_keeps_raw_name_and_parameters(self) -> None:
        from schema.polymer_schema import CharacterizationCandidate
        from stages.stage5_characterization import _normalize_characterization
        block = Stage0Element(block_id="P_1", type="text", page=1, source_block_index=0,
                              text="Data were obtained by a heat-pulse method below 120 K.")
        candidate = CharacterizationCandidate(characterization_id="char001", method_raw="heat-pulse method",
            method_normalized="unmapped", sample_resolution_status="unresolved", entity_id=None,
            parameters={"temperature":"below 120 K"}, derived_property_ids=[],
            evidence=[{"block_id":"P_1","source_sentence":block.text}], confidence={"score":0.8})
        result = _normalize_characterization(candidate, {"P_1":block}, {"DSC":("DSC",)})
        self.assertEqual(result.method_raw, "heat-pulse method")
        self.assertEqual(result.parameters, {"temperature":"below 120 K"})
        self.assertEqual(result.method_normalized, "unmapped")

    def test_dotted_nmr_abbreviation_matches_without_changing_raw(self) -> None:
        self.assertEqual(_method_names_for_raw("CP-MAS 13C n.m.r.", {"NMR":("NMR",)}), {"NMR"})

    def test_stage5_repository_relative_vocabulary_path_resolves(self) -> None:
        self.assertEqual(
            _resolve_vocabulary_path(
                "extraction/config/polymer_schema.yaml",
                config_path=DEFAULT_CONFIG_PATH.resolve(),
            ),
            DEFAULT_VOCABULARY_PATH.resolve(),
        )


METHOD_SENTENCE = (
    "FTIR spectra were recorded over 4000-400 cm-1, and DSC measurements "
    "were conducted."
)
FTIR_SENTENCE = (
    "The FTIR spectrum of dried PB film showed an absorption band at "
    "1650 cm-1 assigned to C=C stretching."
)
DSC_SENTENCE = (
    "The glass transition temperature of dried PB film was -85 °C by DSC."
)
# 第二次 FTIR：同一 sample/entity，不同制样方式与不同吸收峰。
# 对应 reference_no_0071569 的薄膜 IR 与 KBr 压片 IR。
SECOND_FTIR_SENTENCE = (
    "The FTIR spectrum of the same sample as a KBr disk showed bands at "
    "1760 cm-1 and 840 cm-1."
)


def stage0_document() -> Stage0Document:
    return Stage0Document.model_validate({
        "schema_version": "1.0",
        "source_document_schema_version": "1.0",
        "document_id": "reference_no_0000002",
        "paper": {
            "ref_no": "reference_no_0000002",
            "pdf_filename": "uuid_origin.pdf",
            "source_pdf_path": "mineru_output/reference_no_0000002/uuid_origin.pdf",
            "organized_pdf_path": "wenxian/reference_no_0000002/origin.pdf",
            "doi": None,
            "title": "Characterization demo",
            "authors": ["A. Author"],
            "journal": "Journal",
            "year": 2026,
            "metadata_status": "partial",
            "metadata_extraction": {"status": "success"},
        },
        "source_files": {},
        "ocr": {"status": "done"},
        "elements": [
            {
                "block_id": "P_1_0",
                "type": "text",
                "section": "Methods",
                "text": METHOD_SENTENCE,
                "page": 1,
                "bbox": [1, 2, 3, 4],
                "source_block_index": 0,
            },
            {
                "block_id": "P_2_0",
                "type": "text",
                "section": "Results",
                "text": FTIR_SENTENCE,
                "page": 2,
                "bbox": [5, 6, 7, 8],
                "source_block_index": 1,
            },
            {
                "block_id": "P_2_1",
                "type": "text",
                "section": "Results",
                "text": DSC_SENTENCE,
                "page": 2,
                "bbox": [9, 10, 11, 12],
                "source_block_index": 2,
            },
            {
                "block_id": "P_2_2",
                "type": "text",
                "section": "Results",
                "text": SECOND_FTIR_SENTENCE,
                "page": 2,
                "bbox": [13, 14, 15, 16],
                "source_block_index": 3,
            },
        ],
        "warnings": [],
    })


def stage2_document() -> Stage2Document:
    digest = "a" * 64
    return Stage2Document.model_validate({
        "schema_version": "1.0",
        "document_id": "reference_no_0000002",
        "polymer_entities": [{
            "entity_id": "pe001",
            "polymer_name": "polybutadiene",
            "polymer_type": None,
            "variant_of": None,
            "representation_status": "expert_review_required",
            "structural_features": [],
            "source_names": ["polybutadiene", "PB"],
            "resolved_from_mentions": ["m001"],
            "evidence": {
                "block_id": "P_2_0",
                "page": 2,
                "bbox": [5, 6, 7, 8],
                "source_type": "text",
                "source_sentence": FTIR_SENTENCE,
            },
            "source_image_refs": [],
        }],
        "unresolved_mention_ids": [],
        "provenance": {
            "provider": "test",
            "model": "fake",
            "models": ["fake"],
            "prompt_id": "polymer.stage2.polymer_entity",
            "prompt_version": "1.0.1",
            "prompt_sha256": digest,
            "input_hash": digest,
            "model_config_hash": digest,
            "cache_key": digest,
            "output_schema_version": "polymer_entity_schema.v1",
            "implementation_version": "1.1.0",
            "context_block_count": 1,
            "context_chars": 100,
            "call_count": 1,
        },
        "warnings": [],
    })


def stage3_document() -> Stage3Document:
    digest = "b" * 64
    return Stage3Document.model_validate({
        "schema_version": "1.0",
        "document_id": "reference_no_0000002",
        "samples": [{
            "sample_id": "s001",
            "sample_kind": "processed_material",
            "refers_to_entity": "pe001",
            "polymer_name": "polybutadiene",
            "sample_label_raw": "dried PB film",
            "state_description": None,
            "intended_use": [],
            "evidence": {
                "block_id": "P_2_0",
                "page": 2,
                "bbox": [5, 6, 7, 8],
                "source_type": "text",
                "source_sentence": FTIR_SENTENCE,
            },
        }],
        "process_steps": [],
        "unresolved_entity_ids": [],
        "provenance": {
            "provider": "test",
            "model": "fake",
            "models": ["fake"],
            "prompt_id": "polymer.stage3.sample_process",
            "prompt_version": "1.0.2",
            "prompt_sha256": digest,
            "input_hash": digest,
            "model_config_hash": digest,
            "cache_key": digest,
            "output_schema_version": "sample_process_schema.v1",
            "implementation_version": "1.0.0",
            "context_block_count": 1,
            "context_chars": 100,
            "call_count": 1,
        },
        "warnings": [],
    })


def stage4_document(
    *,
    determination_method_raw: str | None = "DSC",
) -> Stage4Document:
    digest = "c" * 64
    return Stage4Document.model_validate({
        "schema_version": "1.0",
        "document_id": "reference_no_0000002",
        "measurement_conditions": [{
            "condition_id": "mc001",
            "temperature": None,
            "frequency": None,
            "humidity": None,
            "pressure": None,
            "wavelength": None,
            "other_conditions": {},
            "condition_status": "not_reported",
            "evidence": {
                "block_id": "P_2_1",
                "page": 2,
                "bbox": [9, 10, 11, 12],
                "source_type": "text",
                "source_sentence": DSC_SENTENCE,
            },
        }],
        "properties": [{
            "property_id": "prop001",
            "sample_id": "s001",
            "property_name_raw": "glass transition temperature",
            "property_name_normalized": "glass_transition_temperature",
            "property_code": "P3110",
            "property_category": "thermal_property",
            "molecular_weight_type": None,
            "determination_method_raw": determination_method_raw,
            "observation_group_id": None,
            "value_raw": "-85",
            "value_min": -85,
            "value_max": -85,
            "unit_raw": "°C",
            "unit_normalized": "°C",
            "measurement_condition_id": "mc001",
            "source_type": "text",
            "evidence": [{
                "block_id": "P_2_1",
                "page": 2,
                "bbox": [9, 10, 11, 12],
                "source_type": "text",
                "source_sentence": DSC_SENTENCE,
            }],
        }],
        "unresolved_properties": [],
        "provenance": {
            "provider": "test",
            "model": "fake",
            "models": ["fake"],
            "prompt_id": "polymer.stage4.property",
            "prompt_version": "1.0.0",
            "prompt_sha256": digest,
            "vocabulary_sha256": digest,
            "input_hash": digest,
            "model_config_hash": digest,
            "cache_key": digest,
            "output_schema_version": "property_observation_schema.v1",
            "implementation_version": "1.0.0",
            "context_block_count": 3,
            "context_chars": 300,
            "call_count": 1,
        },
        "warnings": [],
    })


def stage4_with_unresolved_method(
    *,
    entity_id: str = "pe001",
) -> Stage4Document:
    data = stage4_document(
        determination_method_raw=None
    ).model_dump(mode="json")
    data["unresolved_properties"] = [{
        "unresolved_id": "uprop001",
        "entity_id": entity_id,
        "sample_id": None,
        "property_name_raw": "absorption band",
        "property_name_normalized": None,
        "property_code": None,
        "property_category": None,
        "molecular_weight_type": None,
        "determination_method_raw": "FTIR",
        "observation_group_id": None,
        "value_raw": "1650",
        "value_min": None,
        "value_max": None,
        "unit_raw": "cm-1",
        "unit_normalized": None,
        "measurement_condition_id": None,
        "reason": "sample_ambiguous",
        "evidence": [{
            "block_id": "P_2_0",
            "page": 2,
            "bbox": [5, 6, 7, 8],
            "source_type": "text",
            "source_sentence": FTIR_SENTENCE,
        }],
    }]
    return Stage4Document.model_validate(data)


def stage4_with_two_series(*, second_sample_id: str = "s001") -> Stage4Document:
    data = stage4_document().model_dump(mode="json")
    evidence = {
        "block_id": "P_2_1",
        "page": 2,
        "bbox": [9, 10, 11, 12],
        "source_type": "text",
        "source_sentence": DSC_SENTENCE,
    }
    data["property_series"] = [
        {
            "series_id": series_id,
            "sample_id": sample_id,
            "entity_id": "pe001",
            "sample_resolution_status": "resolved",
            "property_name_raw": property_name,
            "property_name_normalized": normalized,
            "property_code": property_code,
            "property_category": "thermal_property",
            "determination_method_raw": "DSC",
            "unit_raw": "°C",
            "unit_normalized": "°C",
            "measurement_context": {"condition_status": "not_reported"},
            "points": [{
                "point_id": point_id,
                "sample_id": sample_id,
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "coordinates": [],
                "value_raw": value,
                "value_min": float(value),
                "value_max": float(value),
                "unit_raw": "°C",
                "unit_normalized": "°C",
                "measurement_context": {"condition_status": "not_reported"},
                "coverage_status": "covered",
                "evidence": [evidence],
                "confidence": {"score": 0.9},
            }],
            "coverage": {
                "expected": 1,
                "covered": 1,
                "missing": 0,
                "not_applicable": 0,
                "ratio": 1.0,
            },
            "evidence": [evidence],
            "confidence": {"score": 0.9},
        }
        for series_id, sample_id, property_name, normalized, property_code,
        point_id, value in (
            (
                "series001", "s001", "glass transition temperature",
                "glass_transition_temperature", "P3110", "pt001", "-85",
            ),
            (
                "series002", second_sample_id, "melting temperature",
                "melting_temperature", "P3120", "pt002", "120",
            ),
        )
    ]
    return Stage4Document.model_validate(data)


class FakeClient:
    def __init__(self) -> None:
        self.resolved = ResolvedLLMConfig(
            provider="test",
            requested_model="fake",
            model="fake",
            base_url="https://example.test/v1",
            timeout_seconds=10,
            max_retries=0,
            retry_backoff_seconds=0,
        )
        self.calls = 0

    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        self.calls += 1
        return LLMJSONResponse(
            data=add_model_confidence({
                "characterizations": [
                    {
                        "characterization_id": "char010",
                        "method_raw": "FTIR",
                        "method_normalized": "FTIR",
                        "sample_id": "s001",
                        "entity_id": "pe001",
                        "sample_resolution_status": "resolved",
                        "instrument": None,
                        "parameters": {
                            "wavenumber_range": "4000-400 cm-1",
                        },
                        "result_summary": (
                            "An absorption band at 1650 cm-1 was assigned "
                            "to C=C stretching."
                        ),
                        "derived_property_ids": ["prop_s5_010"],
                        "evidence": [
                            {
                                "block_id": "P_1_0",
                                "source_sentence": METHOD_SENTENCE,
                                "table_locator": None,
                            },
                            {
                                "block_id": "P_2_0",
                                "source_sentence": FTIR_SENTENCE,
                                "table_locator": None,
                            },
                        ],
                    },
                    {
                        "characterization_id": "char020",
                        "method_raw": "DSC",
                        "method_normalized": "DSC",
                        "sample_id": "s001",
                        "entity_id": "pe001",
                        "sample_resolution_status": "resolved",
                        "instrument": None,
                        "parameters": {},
                        "result_summary": (
                            "The glass transition temperature was -85 °C."
                        ),
                        "derived_property_ids": ["prop001"],
                        "evidence": [{
                            "block_id": "P_2_1",
                            "source_sentence": DSC_SENTENCE,
                            "table_locator": None,
                        }],
                    },
                ],
                "properties": [{
                    "property_id": "prop_s5_010",
                    "characterization_id": "char010",
                    "sample_id": "s001",
                    "entity_id": "pe001",
                    "sample_resolution_status": "resolved",
                    "property_name_raw": "absorption band",
                    "property_name_normalized": "ftir_peak_wavenumber",
                    "property_category": "composition_structure",
                    "value_raw": "1650",
                    "value_min": 1650,
                    "value_max": 1650,
                    "unit_raw": "cm-1",
                    "unit_normalized": "cm⁻¹",
                    "spectral_assignment": "C=C stretching",
                    "solvent": None,
                    "source_stage": "stage5",
                    "evidence": [{
                        "block_id": "P_2_0",
                        "source_sentence": FTIR_SENTENCE,
                        "table_locator": None,
                    }],
                }],
            }),
            provider="test",
            model="fake-actual",
        )


class RetryClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        if self.calls == 1:
            response.data["characterizations"][1][
                "derived_property_ids"
            ] = ["prop999"]
        return response


class InvalidMethodClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        response.data["properties"][0][
            "property_name_normalized"
        ] = "xrd_diffraction_peak_2theta"
        response.data["properties"][0]["property_category"] = "morphology"
        return response


class MissingRequiredFieldClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        del response.data["characterizations"][0]["method_raw"]
        return response


class UnknownEvidenceBlockClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        response.data["characterizations"][0]["evidence"][0][
            "block_id"
        ] = "P_missing"
        return response


class MixedSpecializedEvidenceClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        response.data["specialized_property_observations"] = [{
            "specialized_id": "sp_cand001",
            "sample_id": "s001",
            "entity_id": "pe001",
            "sample_resolution_status": "resolved",
            "property_name_raw": "molecular weight",
            "value_raw": "67500",
            "unit_raw": "g/mol",
            "method_raw": "GPC",
            "confidence": {"score": 0.9},
            "evidence": [{
                "block_id": "P_missing",
                "source_sentence": "A molecular weight was reported.",
            }],
        }]
        return response


class MissingStage4LinkClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        response.data["characterizations"][1]["derived_property_ids"] = []
        return response


class UnknownSeriesClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        response.data["characterizations"][0]["series_id"] = "series999"
        return response


class MultiSeriesClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        characterization = response.data["characterizations"][1]
        characterization["series_id"] = "series001"
        characterization["derived_property_ids"] = [
            "prop001",
            "series001",
            "series002",
        ]
        return response


class SameMethodTwicePayloadClient(FakeClient):
    """同一方法、同一 sample/entity，但证据块与派生 property 不同。

    对应 reference_no_0071569：薄膜 IR 与 KBr 压片 IR 是两次独立测量。
    """

    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        second = response.data["characterizations"][1]
        second["method_raw"] = "FTIR"
        second["method_normalized"] = "FTIR"
        second["result_summary"] = (
            "Bands at 1760 cm-1 and 840 cm-1 were observed."
        )
        second["evidence"] = [{
            "block_id": "P_2_2",
            "source_sentence": SECOND_FTIR_SENTENCE,
            "table_locator": None,
        }]
        # 原 fixture 里这条挂着 DSC 测定的 prop001；改成 FTIR 后不再回链它。
        second["derived_property_ids"] = []
        return response


class TrueDuplicatePayloadClient(FakeClient):
    """完全相同的两条 Characterization：方法、归属、证据、派生 property 均一致。"""

    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        characterizations = response.data["characterizations"]
        clone = json.loads(json.dumps(characterizations[0]))
        clone["characterization_id"] = "char011"
        characterizations[1] = clone
        for item in response.data["properties"]:
            item["characterization_id"] = "char010"
        return response


class UnresolvedStage4LinkClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        response.data["characterizations"][0][
            "derived_property_ids"
        ].append("uprop001")
        return response


class UnresolvedClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        self.calls += 1
        return LLMJSONResponse(
            data=add_model_confidence({
                "characterizations": [{
                    "characterization_id": "char010",
                    "method_raw": "FTIR",
                    "method_normalized": "FTIR",
                    "sample_id": None,
                    "entity_id": "pe001",
                    "sample_resolution_status": "unresolved",
                    "instrument": None,
                    "parameters": {},
                    "result_summary": None,
                    "derived_property_ids": [],
                    "evidence": [{
                        "block_id": "P_2_0",
                        "source_sentence": FTIR_SENTENCE,
                        "table_locator": None,
                    }],
                }],
                "properties": [],
            }),
            provider="test",
            model="fake-actual",
        )


class MethodShardClient(FakeClient):
    def __init__(self, *, inject_invalid: bool = False) -> None:
        super().__init__()
        self.inject_invalid = inject_invalid
        self.messages: list[str] = []

    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        self.calls += 1
        self.messages.append(user_message)
        method_section = user_message.split(
            "--- BEGIN CONTROLLED CHARACTERIZATION METHODS ---", 1
        )[1].split(
            "--- END CONTROLLED CHARACTERIZATION METHODS ---", 1
        )[0]
        if '"FTIR"' in method_section:
            payload = {
                "characterizations": [{
                    "characterization_id": "char010",
                    "method_raw": "FTIR",
                    "method_normalized": "FTIR",
                    "sample_id": "s001",
                    "entity_id": "pe001",
                    "sample_resolution_status": "resolved",
                    "parameters": {},
                    "derived_property_ids": ["prop_s5_010"],
                    "evidence": [{
                        "block_id": "P_2_0",
                        "source_text": FTIR_SENTENCE,
                    }],
                }],
                "properties": [{
                    "property_id": "prop_s5_010",
                    "characterization_id": "char010",
                    "sample_id": "s001",
                    "entity_id": "pe001",
                    "sample_resolution_status": "resolved",
                    "property_name_raw": "absorption band",
                    "property_name_normalized": "ftir_peak_wavenumber",
                    "property_category": "composition_structure",
                    "value_raw": "1650",
                    "value_min": 1650,
                    "value_max": 1650,
                    "unit_raw": "cm-1",
                    "unit_normalized": "cm⁻¹",
                    "source_stage": "stage5",
                    "evidence": [{
                        "block_id": "P_2_0",
                        "source_text": FTIR_SENTENCE,
                    }],
                }],
            }
        else:
            payload = {
                "characterizations": [{
                    "characterization_id": "char020",
                    "method_raw": "DSC",
                    "method_normalized": "DSC",
                    "sample_id": "s001",
                    "entity_id": "pe001",
                    "sample_resolution_status": "resolved",
                    "parameters": {},
                    "derived_property_ids": ["prop001"],
                    "evidence": [{
                        "block_id": "P_2_1",
                        "source_sentence": DSC_SENTENCE,
                    }],
                }],
                "properties": [],
            }
        if self.inject_invalid:
            payload["characterizations"].append({
                "characterization_id": "char099",
                "method_normalized": "FTIR",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "parameters": {},
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": FTIR_SENTENCE,
                }],
            })
        return LLMJSONResponse(
            data=add_model_confidence(payload),
            provider="test",
            model="fake-sharded",
        )


class UnscopedCharacterizationClient(FakeClient):
    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMJSONResponse:
        response = super().call_json(
            system_prompt,
            user_message,
            max_tokens=max_tokens,
        )
        characterization = response.data["characterizations"][0]
        characterization["sample_id"] = None
        characterization["entity_id"] = None
        characterization["sample_resolution_status"] = "unresolved"
        return response


def rendered_prompt():
    return PromptLoader().render_stage_prompt(
        "polymer.stage5.characterization",
        CharacterizationStageResponse,
        expected_stage="stage5_characterization",
        expected_output_schema="characterization_schema.v4",
    )


class Stage5Tests(unittest.TestCase):
    def test_collects_unscoped_candidate_with_linked_properties(self) -> None:
        payload = {
            "characterizations": [{
                "characterization_id": "char001",
                "sample_id": None,
                "entity_id": None,
                "sample_ids": None,
                "entity_ids": None,
                "sample_resolution_status": "unresolved",
                "evidence": [{"block_id": "P_1_0"}],
            }],
            "properties": [{
                "property_id": "prop001",
                "characterization_id": "char001",
                "value_raw": "1650",
                "evidence": [{"block_id": "P_1_0"}],
            }],
        }

        candidates = _collect_unscoped_preview_candidates(payload)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate_id"], "stage5_raw_char001")
        self.assertEqual(candidates[0]["publication_status"], "candidate_only")
        self.assertEqual(
            candidates[0]["raw_object"]["properties"][0]["property_id"],
            "prop001",
        )
        self.assertEqual(len(candidates[0]["evidence"]), 1)

    def test_run_stage5_writes_unscoped_preview_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            documents = {
                "stage0": stage0_document(),
                "stage2": stage2_document(),
                "stage3": stage3_document(),
                "stage4": stage4_document(),
            }
            paths = {name: root / f"{name}.json" for name in documents}
            for name, model in documents.items():
                paths[name].write_text(
                    json.dumps(model.model_dump(mode="json")),
                    encoding="utf-8",
                )
            output_path = root / "stage5_characterizations.json"

            run_stage5(
                paths["stage0"],
                paths["stage2"],
                paths["stage3"],
                paths["stage4"],
                output_path,
                UnscopedCharacterizationClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                force=True,
                preview_relaxed=True,
                sharded=False,
                max_validation_retries=0,
            )

            sidecar = json.loads(
                (root / "stage5_preview_audit.json").read_text(
                    encoding="utf-8"
                )
            )
            formal = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(sidecar["candidate_count"], 1)
        self.assertEqual(sidecar["accounting"]["preserved"], 1)
        self.assertEqual(sidecar["accounting"]["raw_unscoped_candidates"], 1)
        self.assertEqual(
            sidecar["candidates"][0]["source"]["scope"],
            "document_attempt",
        )
        self.assertEqual(
            sidecar["candidates"][0]["reason"],
            "subject_unresolved",
        )
        self.assertEqual(len(formal["characterizations"]), 2)
        self.assertEqual(
            {item["sample_resolution_status"] for item in formal["characterizations"]},
            {"resolved", "unresolved"},
        )
    def test_same_value_in_different_table_rows_is_not_duplicate(self) -> None:
        base = add_model_confidence({
            "property_id": "prop_s5_001",
            "characterization_id": "char001",
            "sample_ids": ["s001", "s002"],
            "entity_ids": ["pe001", "pe002"],
            "sample_resolution_status": "multi_resolved",
            "property_name_raw": "IR peak",
            "property_name_normalized": "ftir_peak_wavenumber",
            "property_category": "composition_structure",
            "value_raw": "1589",
            "confidence": {"score": 0.9},
            "evidence": [{
                "block_id": "T_1_0",
                "source_sentence": "Table 1",
                "table_locator": {
                    "table_id": "T_1_0",
                    "row_label": "polymer A",
                    "column_label": "IR peak",
                    "cell_value": "1589",
                },
            }],
        })
        other = dict(base)
        other["property_id"] = "prop_s5_002"
        other["evidence"] = [dict(base["evidence"][0])]
        other["evidence"][0]["table_locator"] = dict(
            base["evidence"][0]["table_locator"]
        )
        other["evidence"][0]["table_locator"]["row_label"] = "polymer B"

        first = Stage5PropertyCandidate.model_validate(base)
        second = Stage5PropertyCandidate.model_validate(other)

        self.assertNotEqual(
            _stage5_property_dedupe_key(first),
            _stage5_property_dedupe_key(second),
        )

    def test_preview_preserves_unscoped_characterization_and_property(self) -> None:
        payload = {
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "NMR",
                "method_normalized": "NMR",
                "sample_id": None,
                "entity_id": None,
                "sample_ids": None,
                "entity_ids": None,
                "sample_resolution_status": "unresolved",
                "derived_property_ids": ["prop_s5_001"],
                "evidence": [{
                    "block_id": "P_1_0",
                    "source_sentence": "NMR",
                }],
                "confidence": {"score": 0.5},
            }],
            "properties": [{
                "property_id": "prop_s5_001",
                "characterization_id": "char001",
            }],
        }

        strict, _ = _repair_candidate_response_payload(payload)
        self.assertEqual(len(strict["characterizations"]), 1)

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            preview_relaxed=True,
        )

        self.assertEqual(len(repaired["characterizations"]), 1)
        self.assertEqual(len(repaired["properties"]), 1)
        self.assertTrue(any(
            warning["code"] == "unresolved_characterization_identity"
            for warning in warnings
        ))

    def test_preview_downgrades_empty_reported_measurement_context(self) -> None:
        payload = {
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "DSC",
                "method_normalized": "DSC",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "measurement_context": {
                    "condition_status": "reported",
                },
                "derived_property_ids": ["prop_s5_001"],
                "evidence": [{
                    "block_id": "P_1_0",
                    "source_sentence": "DSC",
                }],
                "confidence": {"score": 0.9},
            }],
            "properties": [{
                "property_id": "prop_s5_001",
                "characterization_id": "char001",
                "property_name_raw": "Tg",
                "property_name_normalized": "glass_transition_temperature",
                "property_category": "thermal",
                "value_raw": "100",
                "unit_raw": "°C",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "evidence": [{
                    "block_id": "P_1_0",
                    "source_sentence": "Tg 100 °C",
                }],
                "confidence": {"score": 0.9},
            }],
        }

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            preview_relaxed=True,
        )

        self.assertIsNone(
            repaired["characterizations"][0]["measurement_context"]
        )
        self.assertIsNotNone(repaired["properties"][0])
        self.assertTrue(any(
            warning["code"] == "preview_measurement_context_downgraded"
            for warning in warnings
        ))

    def test_stage5_specialized_dispatches_non_numeric_to_text(self) -> None:
        candidate = SpecializedPropertyCandidate.model_validate({
            "specialized_id": "sp_cand001",
            "sample_id": "s001",
            "entity_id": "pe001",
            "sample_resolution_status": "resolved",
            "property_name_raw": "crystallinity",
            "value_raw": "amorphous",
            "method_raw": "X-ray diffraction",
            "confidence": {"score": 0.9},
            "evidence": [{
                "block_id": "P_2_0",
                "source_sentence": FTIR_SENTENCE,
            }],
        })

        observations = _materialize_specialized(
            [candidate],
            {block.block_id: block for block in stage0_document().elements},
            get_specialized_vocabulary(),
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].value_kind, "text")
        self.assertEqual(observations[0].text_value, "amorphous")
        self.assertEqual(observations[0].publication_status, "published")

    def test_stage5_specialized_normalizes_numeric_multiple(self) -> None:
        candidate = SpecializedPropertyCandidate.model_validate({
            "specialized_id": "sp_cand001",
            "sample_id": "s001",
            "entity_id": "pe001",
            "sample_resolution_status": "resolved",
            "property_name_raw": "molecular weight",
            "value_raw": "12000, 13500",
            "unit_raw": "g/mol",
            "method_raw": "GPC",
            "confidence": {"score": 0.9},
            "evidence": [{
                "block_id": "P_2_0",
                "source_sentence": FTIR_SENTENCE,
            }],
        })

        observations = _materialize_specialized(
            [candidate],
            {block.block_id: block for block in stage0_document().elements},
            get_specialized_vocabulary(),
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].value_kind, "numeric_multiple")
        self.assertEqual(observations[0].value_min, 12000.0)
        self.assertEqual(observations[0].value_max, 13500.0)
        self.assertEqual(observations[0].unit_normalized, "g/mol")
        self.assertEqual(observations[0].unit_status, "normalized")

        three = candidate.model_copy(update={"value_raw": "12000, 13500, 67000"})
        result = _materialize_specialized([three], {b.block_id: b for b in stage0_document().elements}, get_specialized_vocabulary())[0]
        self.assertEqual(result.numeric_values, [12000, 13500, 67000])
        self.assertEqual(result.value_max, 67000)
        grouped = candidate.model_copy(update={"value_raw": "67,500"})
        result = _materialize_specialized([grouped], {b.block_id: b for b in stage0_document().elements}, get_specialized_vocabulary())[0]
        self.assertEqual(result.value_kind, "numeric_scalar")
        self.assertEqual(result.numeric_values, [67500])

    def test_specialized_outside_shard_is_retained_without_losing_valid_neighbors(self) -> None:
        good = SpecializedPropertyCandidate.model_validate({
            "specialized_id": "sp_cand001", "sample_id": "s001", "entity_id": "pe001",
            "sample_resolution_status": "resolved", "property_name_raw": "molecular weight",
            "value_raw": "67500", "unit_raw": "g/mol", "method_raw": "GPC",
            "confidence": {"score": 0.9},
            "evidence": [{"block_id": "P_2_0", "source_sentence": FTIR_SENTENCE}],
        })
        bad = good.model_copy(update={"evidence": [good.evidence[0].model_copy(update={"block_id": "P_outside"})]})
        parsed = CharacterizationStageResponse(characterizations=[], properties=[], specialized_property_observations=[good, bad, good])
        _, _, kept, rejected = stage5_module._materialize_shard_with_salvage(parsed, stage0_document().elements, get_specialized_vocabulary())
        self.assertEqual([c.specialized_id for c in kept], ["sp001", "sp002"])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["missing_block_ids"], ["P_outside"])
        self.assertEqual(rejected[0]["raw_candidate"]["value_raw"], "67500")
        self.assertIn("evidence_outside_shard", rejected[0]["reason"])

    def test_symbolic_method_alias_requires_full_match(self) -> None:
        methods = {"viscometry": ("[\\eta]",)}

        self.assertEqual(
            _method_names_for_raw("[\\eta]", methods),
            {"viscometry"},
        )
        self.assertEqual(
            _method_names_for_raw("$\\eta_{inh}$ (DMSO)", methods),
            set(),
        )

    def test_ftir_hyphenated_alias_matches(self) -> None:
        self.assertEqual(
            _method_names_for_raw("FT-IR", {"FTIR": ("FTIR",)}),
            {"FTIR"},
        )

    def test_preview_synthesizes_characterization_from_unique_series_method(
        self,
    ) -> None:
        stage4_data = stage4_with_two_series().model_dump(mode="json")
        stage4_data["property_series"] = [stage4_data["property_series"][0]]
        stage4_data["property_series"][0][
            "determination_method_raw"
        ] = "inherent viscosities"
        stage4 = Stage4Document.model_validate(stage4_data)

        repaired, warnings = _repair_candidate_response_payload(
            {"characterizations": [], "properties": []},
            stage4=stage4,
            methods={"viscometry": ("inherent viscosities",)},
            preview_relaxed=True,
        )

        characterization = repaired["characterizations"][0]
        self.assertEqual(characterization["method_normalized"], "viscometry")
        self.assertEqual(characterization["series_id"], "series001")
        self.assertEqual(characterization["confidence"]["score"], 0.5)
        self.assertEqual(
            warnings[0]["code"],
            "preview_characterization_synthesized_from_series",
        )

    def test_preview_removes_only_additional_table_evidence_without_locator(
        self,
    ) -> None:
        document_data = stage0_document().model_dump(mode="json")
        document_data["elements"].append({
            "block_id": "T_2_0",
            "type": "table",
            "section": "Results",
            "caption": "Table 1. FTIR bands",
            "table_body": "<table><tr><td>1650</td></tr></table>",
            "page": 2,
            "bbox": [17, 18, 19, 20],
            "source_block_index": 4,
        })
        document = Stage0Document.model_validate(document_data)
        payload = {
            "characterizations": [{
                "characterization_id": "char001",
                "derived_property_ids": [],
                "evidence": [
                    {
                        "block_id": "P_2_0",
                        "source_sentence": FTIR_SENTENCE,
                    },
                    {
                        "block_id": "T_2_0",
                        "source_sentence": "Table 1. FTIR bands",
                        "table_locator": None,
                    },
                ],
            }],
            "properties": [],
        }

        strict, _ = _repair_candidate_response_payload(
            payload,
            blocks=document.elements,
        )
        self.assertEqual(len(strict["characterizations"][0]["evidence"]), 2)

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            blocks=document.elements,
            preview_relaxed=True,
        )

        self.assertEqual(
            [
                item["block_id"]
                for item in repaired["characterizations"][0]["evidence"]
            ],
            ["P_2_0"],
        )
        self.assertEqual(
            warnings[0]["code"],
            "preview_incomplete_table_evidence_removed",
        )

    def test_preview_recovers_method_surface_from_evidence(self) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "FT-IR",
                "method_normalized": "FTIR",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": "IR spectra were recorded.",
                }],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            methods={"FTIR": ("FTIR", "IR spectra")},
            preview_relaxed=True,
        )

        self.assertEqual(
            repaired["characterizations"][0]["method_raw"],
            "IR spectra",
        )
        self.assertIn(
            "preview_characterization_method_surface_recovered",
            [warning["code"] for warning in warnings],
        )

    def test_preview_removes_unlocatable_additional_text_evidence(self) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "FTIR",
                "method_normalized": "FTIR",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "derived_property_ids": [],
                "evidence": [
                    {
                        "block_id": "P_2_0",
                        "source_sentence": FTIR_SENTENCE,
                    },
                    {
                        "block_id": "P_2_1",
                        "source_sentence": "invented sentence",
                    },
                ],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            blocks=stage0_document().elements,
            preview_relaxed=True,
        )

        self.assertEqual(
            [
                item["block_id"]
                for item in repaired["characterizations"][0]["evidence"]
            ],
            ["P_2_0"],
        )
        self.assertIn(
            "preview_unlocatable_additional_evidence_removed",
            [warning["code"] for warning in warnings],
        )

    def test_preview_normalizes_singleton_property_subject_scope(self) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "X-ray diffraction",
                "method_normalized": "XRD",
                "sample_ids": ["s005", "s006"],
                "entity_ids": ["pe005", "pe006"],
                "sample_resolution_status": "multi_resolved",
                "derived_property_ids": ["prop_s5_001"],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": "The polymers were examined by XRD.",
                }],
            }],
            "properties": [{
                "property_id": "prop_s5_001",
                "characterization_id": "char001",
                "sample_id": None,
                "sample_ids": ["s006"],
                "entity_id": None,
                "sample_resolution_status": "resolved",
                "property_name_raw": "amorphous",
                "property_name_normalized": "crystallinity",
                "property_category": "composition_structure",
                "value_raw": "amorphous",
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": "The polymer was amorphous.",
                }],
            }],
        })

        strict, _ = _repair_candidate_response_payload(payload)
        self.assertEqual(strict["properties"][0]["sample_ids"], ["s006"])
        with self.assertRaises(ValidationError):
            CharacterizationStageResponse.model_validate(strict)

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            preview_relaxed=True,
        )

        item = repaired["properties"][0]
        self.assertEqual(item["sample_id"], "s006")
        self.assertIsNone(item["sample_ids"])
        CharacterizationStageResponse.model_validate(repaired)
        self.assertIn(
            "preview_singleton_subject_scope_normalized",
            [warning["code"] for warning in warnings],
        )

    def test_preview_normalizes_conflicting_multi_subject_fields(self) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "FTIR",
                "method_normalized": "FTIR",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_ids": ["s001", "s002"],
                "entity_ids": ["pe001", "pe002"],
                "sample_resolution_status": "multi_resolved",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": FTIR_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            preview_relaxed=True,
        )

        item = repaired["characterizations"][0]
        self.assertEqual(item["sample_resolution_status"], "resolved")
        self.assertEqual(item["sample_id"], "s001")
        self.assertIsNone(item["sample_ids"])
        self.assertIsNone(item["entity_ids"])
        CharacterizationStageResponse.model_validate(repaired)
        self.assertIn(
            "preview_subject_scope_normalized",
            [warning["code"] for warning in warnings],
        )

    def test_preview_corrects_plural_scope_status(self) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "FTIR",
                "method_normalized": "FTIR",
                "entity_ids": ["pe001", "pe002"],
                "sample_resolution_status": "unresolved",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": FTIR_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, _ = _repair_candidate_response_payload(
            payload,
            preview_relaxed=True,
        )

        self.assertEqual(
            repaired["characterizations"][0]["sample_resolution_status"],
            "multi_resolved",
        )
        CharacterizationStageResponse.model_validate(repaired)

    def test_preview_retains_unverified_value_and_optional_unit(self) -> None:
        document = stage0_document()
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "FTIR",
                "method_normalized": "FTIR",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "derived_property_ids": ["prop_s5_001", "prop_s5_002"],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": FTIR_SENTENCE,
                }],
            }],
            "properties": [
                {
                    "property_id": "prop_s5_001",
                    "characterization_id": "char001",
                    "sample_id": "s001",
                    "entity_id": "pe001",
                    "sample_resolution_status": "resolved",
                    "property_name_raw": "band",
                    "property_name_normalized": "chemical_structure",
                    "property_category": "composition_structure",
                    "value_raw": "not in source",
                    "evidence": [{
                        "block_id": "P_2_0",
                        "source_sentence": FTIR_SENTENCE,
                    }],
                },
                {
                    "property_id": "prop_s5_002",
                    "characterization_id": "char001",
                    "sample_id": "s001",
                    "entity_id": "pe001",
                    "sample_resolution_status": "resolved",
                    "property_name_raw": "1650",
                    "property_name_normalized": "chemical_structure",
                    "property_category": "composition_structure",
                    "value_raw": "1650",
                    "unit_raw": "invented-unit",
                    "unit_normalized": "invented-unit",
                    "evidence": [{
                        "block_id": "P_2_0",
                        "source_sentence": FTIR_SENTENCE,
                    }],
                },
            ],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            blocks=document.elements,
            preview_relaxed=True,
        )

        self.assertEqual(
            [item["property_id"] for item in repaired["properties"]],
            ["prop_s5_001", "prop_s5_002"],
        )
        self.assertEqual(repaired["properties"][1]["unit_raw"], "invented-unit")
        self.assertIsNone(repaired["properties"][1]["unit_normalized"])
        self.assertEqual(
            repaired["characterizations"][0]["derived_property_ids"],
            ["prop_s5_001", "prop_s5_002"],
        )
        codes = [warning["code"] for warning in warnings]
        self.assertIn("preview_unverified_stage5_property", codes)
        self.assertIn("preview_unverified_stage5_optional_fields", codes)

    def test_preview_numeric_surface_match_handles_spaced_math(self) -> None:
        self.assertTrue(
            _preview_numeric_surface_match(
                "The band was reported as 1 3 7 8 cm-1.",
                "1378",
            )
        )

    def test_preview_repairs_unique_table_locator(self) -> None:
        document = stage0_document()
        table = {
            "block_id": "T_3_0",
            "type": "table",
            "section": "Results",
            "table_body": (
                "<table><tr><th>Sample</th><th>Tg</th></tr>"
                "<tr><td>PC-1</td><td>120</td></tr></table>"
            ),
            "page": 3,
            "bbox": [1, 2, 3, 4],
            "source_block_index": 4,
        }
        document = document.model_copy(update={
            "elements": [*document.elements, Stage0Element.model_validate(table)],
        })
        payload = add_model_confidence({
            "characterizations": [],
            "properties": [{
                "property_id": "prop_s5_001",
                "characterization_id": "char001",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "property_name_raw": "Tg",
                "property_name_normalized": "glass_transition_temperature",
                "property_category": "material_characteristics",
                "value_raw": "120",
                "evidence": [{
                    "block_id": "T_3_0",
                    "source_sentence": "table row PC-1",
                    "table_locator": {
                        "table_id": "T_3_0",
                        "row_label": "pc-1",
                        "column_label": "tg",
                        "cell_value": "120",
                    },
                }],
            }],
        })
        repaired, warnings = _repair_candidate_response_payload(
            payload,
            blocks=document.elements,
            preview_relaxed=True,
        )
        locator = repaired["properties"][0]["evidence"][0]["table_locator"]
        self.assertEqual(locator["cell_id"], "T_3_0:r0001:c0001")
        self.assertEqual(locator["row_index"], 1)
        self.assertEqual(locator["column_index"], 1)
        self.assertIn(
            "preview_table_locator_repaired",
            [warning["code"] for warning in warnings],
        )

    def test_preview_retains_unsupported_characterization_details(self) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "FTIR",
                "method_normalized": "FTIR",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "instrument": "invented instrument",
                "parameters": {"mode": "invented mode"},
                "measurement_context": {
                    "condition_status": "reported",
                    "other_conditions": {"curve": "second heating curve"},
                    "other_condition_evidence": {},
                },
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": FTIR_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            blocks=stage0_document().elements,
            preview_relaxed=True,
        )

        item = repaired["characterizations"][0]
        self.assertEqual(item["instrument"], "invented instrument")
        self.assertEqual(item["parameters"], {"mode": "invented mode"})
        self.assertIsNotNone(item["measurement_context"])
        self.assertIn(
            "preview_unverified_characterization_details",
            [warning["code"] for warning in warnings],
        )

    def test_preview_aligns_conflicting_property_scope_to_owner(self) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "FTIR",
                "method_normalized": "FTIR",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "derived_property_ids": ["prop_s5_001"],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": FTIR_SENTENCE,
                }],
            }],
            "properties": [{
                "property_id": "prop_s5_001",
                "characterization_id": "char001",
                "sample_id": "s002",
                "entity_id": "pe002",
                "sample_resolution_status": "resolved",
                "property_name_raw": "1650",
                "property_name_normalized": "chemical_structure",
                "property_category": "composition_structure",
                "value_raw": "1650",
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": FTIR_SENTENCE,
                }],
            }],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            preview_relaxed=True,
        )

        item = repaired["properties"][0]
        self.assertEqual(item["sample_id"], "s001")
        self.assertEqual(item["entity_id"], "pe001")
        self.assertIn(
            "preview_property_subject_scope_aligned",
            [warning["code"] for warning in warnings],
        )

    def test_unique_method_block_is_added_to_characterization_evidence(
        self,
    ) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "glass transition temperature",
                "method_normalized": "DSC",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_1_0",
                    "source_sentence": METHOD_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            blocks=stage0_document().elements,
        )

        self.assertEqual(
            repaired["characterizations"][0]["evidence"][-1]["block_id"],
            "P_2_1",
        )
        self.assertIn(
            "characterization_method_evidence_supplemented",
            [warning["code"] for warning in warnings],
        )

    def test_ambiguous_method_block_is_not_added(self) -> None:
        document_data = stage0_document().model_dump(mode="json")
        elements = document_data["elements"]
        # 复制承载 DSC 语句的块，制造"两个块都能匹配"的歧义。
        # 不能取 elements[-1]——那是第二条 FTIR 语句。
        source = next(
            item for item in elements if item["text"] == DSC_SENTENCE
        )
        duplicate = dict(source)
        duplicate["block_id"] = "P_2_9"
        duplicate["source_block_index"] = len(elements)
        elements.append(duplicate)
        document = Stage0Document.model_validate(document_data)
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "glass transition temperature",
                "method_normalized": "DSC",
                "sample_id": "s001",
                "entity_id": "pe001",
                "sample_resolution_status": "resolved",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_1_0",
                    "source_sentence": METHOD_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            blocks=document.elements,
        )

        self.assertEqual(
            [item["block_id"] for item in repaired["characterizations"][0]["evidence"]],
            ["P_1_0"],
        )
        self.assertNotIn(
            "characterization_method_evidence_supplemented",
            [warning["code"] for warning in warnings],
        )

    def test_cross_subject_series_scope_is_inherited(self) -> None:
        stage4_data = stage4_with_two_series(
            second_sample_id="s002"
        ).model_dump(mode="json")
        first, second = stage4_data["property_series"]
        first["sample_id"] = None
        first["entity_id"] = None
        first["sample_resolution_status"] = "unresolved"
        second_point = second["points"][0]
        second_point["entity_id"] = "pe002"
        first["points"].append(second_point)
        first["coverage"] = {
            "expected": 2,
            "covered": 2,
            "missing": 0,
            "not_applicable": 0,
            "ratio": 1.0,
        }
        stage4_data["property_series"] = [first]
        stage4 = Stage4Document.model_validate(stage4_data)
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "DSC",
                "method_normalized": "DSC",
                "sample_id": None,
                "entity_id": None,
                "sample_resolution_status": "unresolved",
                "series_id": "series001",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_1",
                    "source_sentence": DSC_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            stage4=stage4,
        )

        item = repaired["characterizations"][0]
        self.assertEqual(item["sample_resolution_status"], "multi_resolved")
        self.assertEqual(item["sample_ids"], ["s001", "s002"])
        self.assertEqual(item["entity_ids"], ["pe001", "pe002"])
        CharacterizationStageResponse.model_validate(repaired)
        self.assertIn(
            "series_point_subject_scope_inherited",
            [warning["code"] for warning in warnings],
        )

    def test_single_subject_series_does_not_expand_scope(self) -> None:
        stage4 = stage4_with_two_series()
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "DSC",
                "method_normalized": "DSC",
                "sample_id": None,
                "entity_id": None,
                "sample_resolution_status": "unresolved",
                "series_id": "series001",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_1",
                    "source_sentence": DSC_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            stage4=stage4,
        )

        self.assertNotIn(
            "series_point_subject_scope_inherited",
            [warning["code"] for warning in warnings],
        )
        unresolved = CharacterizationStageResponse.model_validate(repaired).characterizations[0]
        self.assertIsNone(unresolved.sample_id)
        self.assertIsNone(unresolved.entity_id)

    def test_nested_multi_series_scopes_inherit_unique_superset(self) -> None:
        stage4_data = stage4_with_two_series(
            second_sample_id="s002"
        ).model_dump(mode="json")
        first, second = stage4_data["property_series"]
        for series in (first, second):
            series["sample_id"] = None
            series["entity_id"] = None
            series["sample_resolution_status"] = "unresolved"
            series["points"][0]["entity_id"] = (
                "pe002"
                if series["points"][0]["sample_id"] == "s002"
                else "pe001"
            )
            extra = dict(series["points"][0])
            extra["point_id"] = f"pt{100 + len(series['points']):03d}"
            extra["sample_id"] = "s002" if extra["sample_id"] == "s001" else "s001"
            extra["entity_id"] = "pe002" if extra["sample_id"] == "s002" else "pe001"
            series["points"].append(extra)
            series["coverage"] = {
                "expected": 2,
                "covered": 2,
                "missing": 0,
                "not_applicable": 0,
                "ratio": 1.0,
            }
        third = dict(first["points"][0])
        third["point_id"] = "pt200"
        third["sample_id"] = "s003"
        third["entity_id"] = "pe003"
        first["points"].append(third)
        first["coverage"] = {
            "expected": 3,
            "covered": 3,
            "missing": 0,
            "not_applicable": 0,
            "ratio": 1.0,
        }
        stage4 = Stage4Document.model_validate(stage4_data)
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "DSC",
                "method_normalized": "DSC",
                "sample_id": None,
                "entity_id": None,
                "sample_resolution_status": "unresolved",
                "series_ids": ["series001", "series002"],
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_1",
                    "source_sentence": DSC_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, _ = _repair_candidate_response_payload(
            payload,
            stage4=stage4,
            preview_relaxed=True,
        )

        item = repaired["characterizations"][0]
        self.assertEqual(item["sample_resolution_status"], "multi_resolved")
        self.assertEqual(set(item["sample_ids"]), {"s001", "s002", "s003"})
        self.assertEqual(set(item["entity_ids"]), {"pe001", "pe002", "pe003"})
        CharacterizationStageResponse.model_validate(repaired)

    def test_different_multi_series_scopes_are_not_inherited(self) -> None:
        stage4_data = stage4_with_two_series(
            second_sample_id="s002"
        ).model_dump(mode="json")
        for index, series in enumerate(stage4_data["property_series"]):
            series["sample_id"] = None
            series["entity_id"] = None
            series["sample_resolution_status"] = "unresolved"
            extra = dict(series["points"][0])
            extra["point_id"] = f"pt{100 + index:03d}"
            extra["sample_id"] = "s002" if index == 0 else "s003"
            extra["entity_id"] = "pe002" if index == 0 else "pe003"
            series["points"].append(extra)
            series["coverage"] = {
                "expected": 2,
                "covered": 2,
                "missing": 0,
                "not_applicable": 0,
                "ratio": 1.0,
            }
        stage4 = Stage4Document.model_validate(stage4_data)
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "DSC",
                "method_normalized": "DSC",
                "sample_id": None,
                "entity_id": None,
                "sample_resolution_status": "unresolved",
                "series_ids": ["series001", "series002"],
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_1",
                    "source_sentence": DSC_SENTENCE,
                }],
            }],
            "properties": [],
        })

        repaired, _ = _repair_candidate_response_payload(
            payload,
            stage4=stage4,
        )

        unresolved = CharacterizationStageResponse.model_validate(repaired).characterizations[0]
        self.assertIsNone(unresolved.sample_id)
        self.assertIsNone(unresolved.entity_id)

    def test_explicit_all_synthesized_polymers_expands_multi_subject_scope(
        self,
    ) -> None:
        process_data = stage3_document().model_dump(mode="json")
        process_data["samples"] = [
            {
                **process_data["samples"][0],
                "sample_id": sample_id,
                "sample_kind": "synthesis_batch",
                "refers_to_entity": entity_id,
                "polymer_name": label,
                "sample_label_raw": label,
            }
            for sample_id, entity_id, label in (
                ("s001", "pe001", "PU1"),
                ("s002", "pe002", "PU2"),
            )
        ]
        process = Stage3Document.model_validate(process_data)
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "X-ray diffraction",
                "method_normalized": "XRD",
                "sample_id": None,
                "entity_id": None,
                "sample_resolution_status": "unresolved",
                "derived_property_ids": ["prop_s5_001"],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": (
                        "All synthesized polymers were examined by "
                        "X-ray diffraction."
                    ),
                }],
            }],
            "properties": [{
                "property_id": "prop_s5_001",
                "characterization_id": "char001",
                "sample_id": None,
                "entity_id": None,
                "sample_resolution_status": "unresolved",
                "property_name_raw": "amorphous",
                "property_name_normalized": "crystallinity",
                "property_category": "composition_structure",
                "value_raw": "amorphous",
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": (
                        "All synthesized polymers were amorphous."
                    ),
                }],
            }],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            process=process,
        )

        characterization = repaired["characterizations"][0]
        property_item = repaired["properties"][0]
        self.assertEqual(
            characterization["sample_resolution_status"],
            "multi_resolved",
        )
        self.assertEqual(characterization["sample_ids"], ["s001", "s002"])
        self.assertEqual(characterization["entity_ids"], ["pe001", "pe002"])
        self.assertEqual(property_item["sample_ids"], ["s001", "s002"])
        CharacterizationStageResponse.model_validate(repaired)
        self.assertIn(
            "explicit_all_samples_scope_expanded",
            [warning["code"] for warning in warnings],
        )

    def test_generic_polymers_does_not_expand_subject_scope(self) -> None:
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "X-ray diffraction",
                "method_normalized": "XRD",
                "sample_id": None,
                "entity_id": None,
                "sample_resolution_status": "unresolved",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": "Polymers were examined by XRD.",
                }],
            }],
            "properties": [],
        })

        repaired, warnings = _repair_candidate_response_payload(
            payload,
            process=stage3_document(),
        )

        self.assertEqual(warnings, [])
        unresolved = CharacterizationStageResponse.model_validate(repaired).characterizations[0]
        self.assertIsNone(unresolved.sample_id)
        self.assertIsNone(unresolved.entity_id)

    def test_explicit_all_scope_is_inherited_only_within_same_block(self) -> None:
        process_data = stage3_document().model_dump(mode="json")
        process_data["samples"] = [
            {
                **process_data["samples"][0],
                "sample_id": sample_id,
                "sample_kind": "synthesis_batch",
                "refers_to_entity": entity_id,
                "polymer_name": label,
                "sample_label_raw": label,
            }
            for sample_id, entity_id, label in (
                ("s001", "pe001", "PU1"),
                ("s002", "pe002", "PU2"),
            )
        ]
        process = Stage3Document.model_validate(process_data)
        document_data = stage0_document().model_dump(mode="json")
        document_data["elements"][1]["text"] = (
            "All synthesized polymers were amorphous. "
            "DSC thermograms of polymers showed glass transitions."
        )
        document = Stage0Document.model_validate(document_data)
        payload = add_model_confidence({
            "characterizations": [{
                "characterization_id": "char001",
                "method_raw": "DSC",
                "method_normalized": "DSC",
                "sample_id": None,
                "entity_id": None,
                "sample_resolution_status": "unresolved",
                "derived_property_ids": [],
                "evidence": [{
                    "block_id": "P_2_0",
                    "source_sentence": (
                        "DSC thermograms of polymers showed glass transitions."
                    ),
                }],
            }],
            "properties": [],
        })

        repaired, _ = _repair_candidate_response_payload(
            payload,
            process=process,
            blocks=document.elements,
        )

        self.assertEqual(
            repaired["characterizations"][0]["sample_ids"],
            ["s001", "s002"],
        )

    @classmethod
    def setUpClass(cls) -> None:
        (
            cls.methods,
            cls.vocabulary,
            cls.vocabulary_hash,
        ) = load_characterization_vocabulary(DEFAULT_VOCABULARY_PATH)

    def test_plan_shards_keeps_explicit_results_in_their_method(self) -> None:
        blocks, _, _ = select_context_blocks(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
        )

        shards, _ = plan_shards(blocks, self.methods)
        by_method = {item.method_normalized: item for item in shards}

        self.assertIn("FTIR", by_method)
        self.assertIn("DSC", by_method)
        ftir_blocks = {block.block_id for block in by_method["FTIR"].blocks}
        dsc_blocks = {block.block_id for block in by_method["DSC"].blocks}
        self.assertIn("P_2_0", ftir_blocks)
        self.assertNotIn("P_2_1", ftir_blocks)
        self.assertIn("P_2_1", dsc_blocks)

    def test_known_field_aliases_are_repaired_before_validation(self) -> None:
        response = MethodShardClient().call_json(
            "",
            "--- BEGIN CONTROLLED CHARACTERIZATION METHODS ---\n"
            '{"FTIR": {}}\n'
            "--- END CONTROLLED CHARACTERIZATION METHODS ---",
        )
        response.data["characterizations"][0]["series_ids"] = ["series001"]

        repaired, warnings = _repair_candidate_response_payload(response.data)

        characterization = repaired["characterizations"][0]
        self.assertEqual(characterization["series_id"], "series001")
        self.assertNotIn("series_ids", characterization)
        self.assertEqual(
            characterization["evidence"][0]["source_sentence"],
            FTIR_SENTENCE,
        )
        codes = {item["code"] for item in warnings}
        self.assertIn("source_text_alias_normalized", codes)
        self.assertIn("singleton_series_ids_normalized", codes)

    def test_offline_replay_without_saved_shards_never_calls_model(self) -> None:
        client = MethodShardClient()
        diagnostics = {}
        with patch.object(client, "call_json", side_effect=AssertionError("offline replay called model")):
            result = extract_characterizations(stage0_document(), stage2_document(), stage3_document(),
                stage4_document(), client, rendered_prompt(), self.methods, self.vocabulary,
                self.vocabulary_hash, preview_relaxed=True, sharded=True,
                max_validation_retries=0, diagnostic_sink=diagnostics, replay_shard_responses=True)
        self.assertEqual(result.provenance.status, "candidate_partial")
        self.assertEqual(result.provenance.call_count, 0)
        self.assertEqual(len(diagnostics["shards"]), diagnostics["shard_count"])
        self.assertTrue(all(x["status"] == "not_executed_no_saved_response" for x in diagnostics["shards"]))

    def test_sharded_preview_extracts_one_method_per_request(self) -> None:
        client = MethodShardClient()
        diagnostics: dict[str, object] = {}

        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
            client,
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            preview_relaxed=True,
            sharded=True,
            max_validation_retries=0,
            diagnostic_sink=diagnostics,
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(result.provenance.status, "success")
        self.assertEqual(
            [item.method_normalized for item in result.characterizations],
            ["FTIR", "DSC"],
        )
        self.assertEqual(
            [item.characterization_id for item in result.characterizations],
            ["char001", "char002"],
        )
        self.assertEqual(result.properties[0].property_id, "prop_s5_001")
        self.assertEqual(diagnostics["shard_count"], 2)
        self.assertFalse(diagnostics["parallelism"]["enabled"])
        for message in client.messages:
            method_section = message.split(
                "--- BEGIN CONTROLLED CHARACTERIZATION METHODS ---", 1
            )[1].split(
                "--- END CONTROLLED CHARACTERIZATION METHODS ---", 1
            )[0]
            self.assertEqual(method_section.count('"aliases"'), 1)

    def test_shard_workers_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "shard_workers"):
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_document(),
                MethodShardClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                preview_relaxed=True,
                sharded=True,
                shard_workers=0,
                max_validation_retries=0,
            )

    def test_sharded_preview_keeps_valid_objects_when_one_is_invalid(
        self,
    ) -> None:
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
            MethodShardClient(inject_invalid=True),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            preview_relaxed=True,
            sharded=True,
            max_validation_retries=0,
        )

        self.assertEqual(result.provenance.status, "candidate_partial")
        self.assertEqual(len(result.characterizations), 2)
        self.assertEqual(len(result.properties), 1)
        self.assertTrue(any(
            item.get("code") == "stage5_shards_partial"
            and item.get("blocking") is True
            for item in result.warnings
        ))

    def test_run_stage5_writes_shard_raw_response_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {
                "stage0": root / "stage0.json",
                "stage2": root / "stage2.json",
                "stage3": root / "stage3.json",
                "stage4": root / "stage4.json",
            }
            for name, model in (
                ("stage0", stage0_document()),
                ("stage2", stage2_document()),
                ("stage3", stage3_document()),
                ("stage4", stage4_document()),
            ):
                paths[name].write_text(
                    json.dumps(model.model_dump(mode="json")),
                    encoding="utf-8",
                )
            output_path = root / "stage5_characterizations.json"
            diagnostics_path = root / "stage5_shards.json"

            run_stage5(
                paths["stage0"],
                paths["stage2"],
                paths["stage3"],
                paths["stage4"],
                output_path,
                MethodShardClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                force=True,
                preview_relaxed=True,
                sharded=True,
                max_validation_retries=0,
                diagnostics_path=diagnostics_path,
            )

            audit = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            result = json.loads(output_path.read_text(encoding="utf-8"))
            preview_audit = json.loads(
                (root / "stage5_preview_audit.json").read_text(
                    encoding="utf-8"
                )
            )

            output_path.unlink()
            cached_client = MethodShardClient()
            run_stage5(
                paths["stage0"],
                paths["stage2"],
                paths["stage3"],
                paths["stage4"],
                output_path,
                cached_client,
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                preview_relaxed=True,
                sharded=True,
                max_validation_retries=0,
                diagnostics_path=diagnostics_path,
            )
            cached_audit = json.loads(
                diagnostics_path.read_text(encoding="utf-8")
            )

        self.assertEqual(audit["status"], "success")
        self.assertEqual(audit["shard_count"], 2)
        self.assertTrue(all(
            item["duration_seconds"] >= 0
            and item["ended_at"] >= item["started_at"]
            for item in audit["shards"]
        ))
        self.assertTrue(all(
            item["attempts"][0]["raw_response"]["content"]
            for item in audit["shards"]
        ))
        self.assertEqual(
            sum(
                item["attempts"][0]["characterization_count"]
                for item in audit["shards"]
            ),
            2,
        )
        self.assertEqual(result["provenance"]["status"], "success")
        self.assertEqual(preview_audit["candidate_count"], 0)
        self.assertEqual(cached_client.calls, 0)
        self.assertTrue(all(
            item["cache_hit"] for item in cached_audit["shards"]
        ))

    def test_old_shard_raw_response_is_revalidated_without_model_call(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            documents = {
                "stage0": stage0_document(),
                "stage2": stage2_document(),
                "stage3": stage3_document(),
                "stage4": stage4_document(),
            }
            paths = {name: root / f"{name}.json" for name in documents}
            for name, model in documents.items():
                paths[name].write_text(
                    json.dumps(model.model_dump(mode="json")),
                    encoding="utf-8",
                )
            output_path = root / "stage5_characterizations.json"
            diagnostics_path = root / "stage5_shards.json"
            prompt = rendered_prompt()
            initial_client = MethodShardClient()

            run_stage5(
                paths["stage0"],
                paths["stage2"],
                paths["stage3"],
                paths["stage4"],
                output_path,
                initial_client,
                prompt,
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                force=True,
                preview_relaxed=True,
                sharded=True,
                max_validation_retries=0,
                diagnostics_path=diagnostics_path,
            )

            audit = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            audit["schema_version"] = "stage5_shards.v0.1"
            for cached in audit["shards"]:
                cached.pop("result", None)
                cached.pop("cache_key", None)
                if cached["method_normalized"] == "FTIR":
                    raw = cached["attempts"][-1]["raw_response"]
                    payload = json.loads(raw["content"])
                    payload["characterizations"][0][
                        "derived_property_ids"
                    ].append("uprop999")
                    raw["content"] = json.dumps(payload)
            diagnostics_path.write_text(json.dumps(audit), encoding="utf-8")

            output = json.loads(output_path.read_text(encoding="utf-8"))
            _, _, legacy_cache_key = stage5_module._cache_components(
                documents["stage0"],
                documents["stage2"],
                documents["stage3"],
                documents["stage4"],
                prompt,
                self.vocabulary_hash,
                initial_client,
                implementation_version="1.8.0",
                preview_relaxed=True,
                sharded=True,
            )
            output["provenance"]["implementation_version"] = "1.8.0"
            output["provenance"]["cache_key"] = legacy_cache_key
            output_path.write_text(json.dumps(output), encoding="utf-8")

            replay_guard = MethodShardClient()
            run_stage5(
                paths["stage0"],
                paths["stage2"],
                paths["stage3"],
                paths["stage4"],
                output_path,
                replay_guard,
                prompt,
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                preview_relaxed=True,
                sharded=True,
                max_validation_retries=0,
                diagnostics_path=diagnostics_path,
            )
            replayed = json.loads(output_path.read_text(encoding="utf-8"))
            replay_audit = json.loads(
                diagnostics_path.read_text(encoding="utf-8")
            )

        self.assertEqual(replay_guard.calls, 0)
        self.assertEqual(replayed["provenance"]["call_count"], 0)
        self.assertEqual(replayed["provenance"]["status"], "candidate_partial")
        self.assertTrue(all(
            item["cache_hit"] and item["raw_replayed"]
            for item in replay_audit["shards"]
        ))
        warning_codes = {item["code"] for item in replayed["warnings"]}
        self.assertIn("stage5_shard_response_replayed", warning_codes)
        self.assertIn(
            "preview_shard_semantic_validation_bypassed",
            warning_codes,
        )

    def test_explicit_shard_replay_accepts_stale_cache_key(self) -> None:
        client = MethodShardClient()
        replay = stage5_module._cached_shard_replay_client(
            client,
            {
                "cache_key": "stale-cache-key",
                "attempts": [{
                    "raw_response": {
                        "provider": "test",
                        "model": "test-model",
                        "content": json.dumps({
                            "characterizations": [],
                            "properties": [],
                        }),
                    },
                }],
            },
            {"current-cache-key"},
            allow_cache_key_mismatch=True,
        )
        self.assertIsNotNone(replay)
        self.assertEqual(replay.calls, 0)

    def test_vocabulary_separates_stage4_measurements(self) -> None:
        self.assertIn("FTIR", self.methods)
        self.assertIn("DSC", self.methods)
        self.assertEqual(
            self.vocabulary["ftir_peak_wavenumber"],
            ("composition_structure", frozenset({"FTIR"})),
        )
        self.assertNotIn(
            "glass_transition_temperature",
            self.vocabulary,
        )
        self.assertIn("swelling", self.methods)
        self.assertIn(r"[\eta]", self.methods["viscometry"])
        self.assertIn("[Q]", self.methods["swelling"])
        self.assertIn(r"[\Phi]", self.methods["turbidimetry"])
        self.assertIn("dilatometry", self.methods)
        self.assertEqual(
            _method_names_for_raw("measured dilatometrically", self.methods),
            {"dilatometry"},
        )
        self.assertEqual(
            _method_names_for_raw("dila-tometric", self.methods),
            {"dilatometry"},
        )

    def test_prompt_contains_stage4_series_section(self) -> None:
        blocks, _, _ = stage5_module.select_context_blocks(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
        )
        message = stage5_module._user_message(
            "reference_no_0000002",
            stage2_document(),
            stage3_document(),
            stage4_document(),
            blocks,
            self.methods,
            self.vocabulary,
        )

        self.assertIn("BEGIN EXISTING STAGE 4 SERIES", message)

    def test_unknown_series_reference_is_rejected(self) -> None:
        with self.assertRaises(Stage5Error):
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_document(),
                UnknownSeriesClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                max_validation_retries=0,
            )

    def test_duplicate_series_derived_reference_is_removed(self) -> None:
        original = {
            "characterizations": [{
                "characterization_id": "char001",
                "series_id": "series001",
                "derived_property_ids": ["series001", "prop001"],
            }],
        }

        repaired, warnings = _repair_candidate_response_payload(original)

        self.assertEqual(
            repaired["characterizations"][0]["derived_property_ids"],
            ["prop001"],
        )
        self.assertEqual(
            original["characterizations"][0]["derived_property_ids"],
            ["series001", "prop001"],
        )
        self.assertEqual(
            warnings[0]["code"],
            "duplicate_series_derived_reference_removed",
        )

    def test_other_unknown_derived_reference_is_not_removed(self) -> None:
        repaired, warnings = _repair_candidate_response_payload({
            "characterizations": [{
                "characterization_id": "char001",
                "series_id": "series001",
                "derived_property_ids": ["series999"],
            }],
        })

        self.assertEqual(
            repaired["characterizations"][0]["derived_property_ids"],
            ["series999"],
        )
        self.assertEqual(warnings, [])

    def test_property_completes_missing_characterization_back_reference(
        self,
    ) -> None:
        repaired, warnings = _repair_candidate_response_payload({
            "characterizations": [{
                "characterization_id": "char001",
                "derived_property_ids": [],
            }],
            "properties": [{
                "property_id": "prop_s5_001",
                "characterization_id": "char001",
            }],
        })

        self.assertEqual(
            repaired["characterizations"][0]["derived_property_ids"],
            ["prop_s5_001"],
        )
        self.assertEqual(
            warnings[0]["code"],
            "derived_property_back_reference_completed",
        )

    def test_conflicting_property_owner_is_not_repaired(self) -> None:
        payload = {
            "characterizations": [
                {
                    "characterization_id": "char001",
                    "derived_property_ids": [],
                },
                {
                    "characterization_id": "char002",
                    "derived_property_ids": ["prop_s5_001"],
                },
            ],
            "properties": [{
                "property_id": "prop_s5_001",
                "characterization_id": "char001",
            }],
        }
        repaired, warnings = _repair_candidate_response_payload(payload)

        self.assertEqual(
            repaired["characterizations"][0]["derived_property_ids"], []
        )
        self.assertEqual(warnings, [])

        preview_repaired, preview_warnings = (
            _repair_candidate_response_payload(
                payload,
                preview_relaxed=True,
            )
        )
        self.assertEqual(
            preview_repaired["characterizations"][0]["derived_property_ids"],
            ["prop_s5_001"],
        )
        self.assertEqual(
            preview_repaired["characterizations"][1]["derived_property_ids"],
            [],
        )
        self.assertEqual(
            preview_warnings[0]["code"],
            "preview_property_back_reference_reassigned",
        )

    def test_known_series_references_move_to_series_ids(self) -> None:
        stage4 = stage4_with_two_series()
        response = MultiSeriesClient().call_json("", "")

        repaired, warnings = _repair_candidate_response_payload(
            response.data,
            stage4,
        )

        characterization = repaired["characterizations"][1]
        self.assertIsNone(characterization["series_id"])
        self.assertEqual(
            characterization["series_ids"],
            ["series001", "series002"],
        )
        self.assertEqual(characterization["derived_property_ids"], ["prop001"])
        self.assertEqual(
            warnings[0]["code"],
            "series_references_moved_from_derived_properties",
        )

    def test_multiple_series_are_validated_and_materialized(self) -> None:
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_with_two_series(),
            MultiSeriesClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            max_validation_retries=0,
        )

        characterization = result.characterizations[1]
        self.assertIsNone(characterization.series_id)
        self.assertEqual(
            characterization.series_ids,
            ["series001", "series002"],
        )
        self.assertEqual(characterization.derived_property_ids, ["prop001"])

    def test_same_method_on_distinct_evidence_is_not_duplicate(self) -> None:
        """同一方法在不同位置的两次表征不是重复。

        真实案例 reference_no_0071569：薄膜 IR（P_8_66，N—H 3420/C=O 1685）
        与 KBr 压片 IR（P_8_72，1760/1168/840）是两次独立测量，
        旧去重键只看 (方法, sample, entity)，会把它们判成重复而整篇硬失败。
        """
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(determination_method_raw=None),
            SameMethodTwicePayloadClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            max_validation_retries=0,
        )

        methods = [
            item.method_normalized for item in result.characterizations
        ]
        self.assertEqual(methods, ["FTIR", "FTIR"])
        self.assertEqual(
            [
                sorted(evidence.block_id for evidence in item.evidence)
                for item in result.characterizations
            ],
            [["P_1_0", "P_2_0"], ["P_2_2"]],
        )

    def test_identical_characterizations_still_fail(self) -> None:
        """放宽去重键之后，真正的重复输出仍须硬失败。"""
        with self.assertRaises(Stage5Error) as ctx:
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_document(),
                TrueDuplicatePayloadClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                max_validation_retries=0,
            )

        self.assertIn("重复 Characterization", str(ctx.exception))

    def test_multiple_series_cannot_cross_samples(self) -> None:
        with self.assertRaises(Stage5Error):
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_with_two_series(second_sample_id="s999"),
                MultiSeriesClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                max_validation_retries=0,
            )

    def test_series_id_and_series_ids_are_mutually_exclusive(self) -> None:
        payload = MultiSeriesClient().call_json("", "").data
        payload["characterizations"][1]["series_ids"] = [
            "series001",
            "series002",
        ]

        with self.assertRaises(ValidationError):
            CharacterizationStageResponse.model_validate(payload)

    def test_extracts_ftir_property_and_links_dsc_stage4_property(self) -> None:
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
            FakeClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
        )

        self.assertEqual(
            [item.characterization_id for item in result.characterizations],
            ["char001", "char002"],
        )
        self.assertEqual(result.properties[0].property_id, "prop_s5_001")
        self.assertEqual(
            result.properties[0].characterization_id,
            "char001",
        )
        self.assertEqual(
            result.characterizations[0].derived_property_ids,
            ["prop_s5_001"],
        )
        self.assertEqual(
            result.characterizations[1].derived_property_ids,
            ["prop001"],
        )
        self.assertEqual(
            result.characterizations[0].parameters["wavenumber_range"],
            "4000-400 cm-1",
        )
        self.assertEqual(result.provenance.model, "fake-actual")

    def test_unknown_derived_property_is_retried(self) -> None:
        client = RetryClient()

        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
            client,
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            max_validation_retries=1,
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(len(result.characterizations), 2)

    def test_property_method_mismatch_is_rejected(self) -> None:
        with self.assertRaises(Stage5Error):
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_document(),
                InvalidMethodClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                max_validation_retries=0,
            )

    def test_preview_preserves_schema_valid_semantic_mismatch(self) -> None:
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
            InvalidMethodClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            max_validation_retries=0,
            preview_relaxed=True,
        )

        self.assertEqual(
            result.properties[0].property_name_normalized,
            "xrd_diffraction_peak_2theta",
        )
        self.assertTrue(any(
            item["code"] == "preview_semantic_validation_bypassed"
            for item in result.warnings
        ))

    def test_preview_preserves_valid_neighbor_for_invalid_schema(self) -> None:
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
            MissingRequiredFieldClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            max_validation_retries=0,
            preview_relaxed=True,
        )

        self.assertEqual(len(result.characterizations), 1)
        self.assertEqual(result.characterizations[0].method_normalized, "DSC")
        self.assertEqual(result.properties, [])
        warning = next(
            item
            for item in result.warnings
            if item["code"] == "stage5_schema_objects_rejected"
        )
        self.assertTrue(warning["blocking"])
        self.assertEqual(result.provenance.status, "candidate_partial")

    def test_strict_rejects_invalid_schema(self) -> None:
        with self.assertRaises(Stage5Error):
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_document(),
                MissingRequiredFieldClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                max_validation_retries=0,
            )

    def test_preview_isolates_unsafe_evidence_and_keeps_valid_neighbors(self) -> None:
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
            UnknownEvidenceBlockClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            max_validation_retries=0,
            preview_relaxed=True,
        )

        self.assertEqual(len(result.characterizations), 1)
        self.assertEqual(len(result.properties), 0)
        self.assertTrue(any(
            item["code"] == "stage5_objects_rejected"
            for item in result.warnings
        ))

    def test_strict_isolates_one_dangling_specialized_evidence_candidate(self) -> None:
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_document(),
            MixedSpecializedEvidenceClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            max_validation_retries=0,
        )

        self.assertEqual(len(result.characterizations), 2)
        self.assertEqual(len(result.properties), 1)
        self.assertEqual(result.specialized_property_observations, [])
        warning = next(
            item for item in result.warnings
            if item["code"] == "stage5_objects_rejected"
        )
        self.assertEqual(
            warning["items"][0]["collection"],
            "specialized_property_observations",
        )
        self.assertEqual(warning["items"][0]["missing_block_ids"], ["P_missing"])

    def test_unscoped_specialized_keeps_valid_neighbors_and_counts_received_call(self) -> None:
        class UnscopedClient(FakeClient):
            def call_json(self, *args, **kwargs):
                response = super().call_json(*args, **kwargs)
                response.data["specialized_property_observations"] = [{
                    "specialized_id": "sp_cand001", "sample_resolution_status": "unresolved",
                    "sample_id": None, "entity_id": None, "property_name_raw": "structure assignment",
                    "value_raw": "C=C stretching", "confidence": {"score": 0.7},
                    "evidence": [{"block_id": "P_2_0", "source_sentence": FTIR_SENTENCE}]}]
                return response
        result = extract_characterizations(stage0_document(),stage2_document(),stage3_document(),
            stage4_document(),UnscopedClient(),rendered_prompt(),self.methods,self.vocabulary,
            self.vocabulary_hash,max_validation_retries=0,preview_relaxed=True)
        self.assertEqual(len(result.characterizations),2)
        self.assertEqual(len(result.properties),1)
        self.assertEqual(len(result.specialized_property_observations),1)
        self.assertIsNone(result.specialized_property_observations[0].sample_id)
        self.assertEqual(result.provenance.call_count,1)
        self.assertTrue(any(w["code"]=="unresolved_specialized_identity" for w in result.warnings))

    def test_received_but_invalid_response_is_still_counted(self) -> None:
        result = extract_characterizations(stage0_document(),stage2_document(),stage3_document(),
            stage4_document(),MissingRequiredFieldClient(),rendered_prompt(),self.methods,self.vocabulary,
            self.vocabulary_hash,max_validation_retries=0,preview_relaxed=True)
        self.assertEqual(len(result.characterizations),1)
        self.assertEqual(result.provenance.call_count,1)

    def test_stage4_method_requires_characterization_backlink(self) -> None:
        with self.assertRaises(Stage5Error):
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_document(),
                MissingStage4LinkClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                max_validation_retries=0,
            )

    def test_unresolved_stage4_method_links_by_entity(self) -> None:
        result = extract_characterizations(
            stage0_document(),
            stage2_document(),
            stage3_document(),
            stage4_with_unresolved_method(),
            UnresolvedStage4LinkClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
            max_validation_retries=0,
        )

        self.assertIn(
            "uprop001",
            result.characterizations[0].derived_property_ids,
        )

    def test_unresolved_stage4_method_requires_backlink(self) -> None:
        with self.assertRaises(Stage5Error):
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_with_unresolved_method(),
                FakeClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                max_validation_retries=0,
            )

    def test_unresolved_stage4_link_cannot_cross_entity(self) -> None:
        with self.assertRaises(Stage5Error):
            extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_with_unresolved_method(entity_id="pe999"),
                UnresolvedStage4LinkClient(),
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                max_validation_retries=0,
            )

    def test_unresolved_sample_generates_warning(self) -> None:
        result = extract_characterizations(
                stage0_document(),
                stage2_document(),
                stage3_document(),
                stage4_document(determination_method_raw=None),
                UnresolvedClient(),
            rendered_prompt(),
            self.methods,
            self.vocabulary,
            self.vocabulary_hash,
        )

        self.assertEqual(
            result.characterizations[0].sample_resolution_status,
            "unresolved",
        )
        self.assertEqual(
            result.warnings[0]["code"],
            "unresolved_characterizations",
        )

    def test_compatible_output_cache_is_reused(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stage0_path = root / "stage0.json"
            stage2_path = root / "stage2.json"
            stage3_path = root / "stage3.json"
            stage4_path = root / "stage4.json"
            output_path = root / "stage5.json"
            for path, model in (
                (stage0_path, stage0_document()),
                (stage2_path, stage2_document()),
                (stage3_path, stage3_document()),
                (stage4_path, stage4_document()),
            ):
                path.write_text(
                    json.dumps(model.model_dump(mode="json")),
                    encoding="utf-8",
                )

            _, first_cached = run_stage5(
                stage0_path,
                stage2_path,
                stage3_path,
                stage4_path,
                output_path,
                client,
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
            )
            _, second_cached = run_stage5(
                stage0_path,
                stage2_path,
                stage3_path,
                stage4_path,
                output_path,
                client,
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
            )

        self.assertFalse(first_cached)
        self.assertTrue(second_cached)
        self.assertEqual(client.calls, 1)

    def test_failure_response_can_be_replayed_without_network(self) -> None:
        response = FakeClient().call_json("", "")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_paths = {
                "stage0": root / "stage0.json",
                "stage2": root / "stage2.json",
                "stage3": root / "stage3.json",
                "stage4": root / "stage4.json",
            }
            output_path = root / "stage5.json"
            failure_path = root / "stage5_failure.json"
            for name, model in (
                ("stage0", stage0_document()),
                ("stage2", stage2_document()),
                ("stage3", stage3_document()),
                ("stage4", stage4_document()),
            ):
                input_paths[name].write_text(
                    json.dumps(model.model_dump(mode="json")),
                    encoding="utf-8",
                )
            failure_path.write_text(
                json.dumps({
                    "raw_response": {
                        "provider": "saved-provider",
                        "model": "saved-model",
                        "content": json.dumps(response.data),
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                        },
                        "cost": {
                            "currency": "CNY",
                            "input_per_million": "6.75",
                            "output_per_million": "40.48",
                            "input_cost": "0.000675",
                            "output_cost": "0.002024",
                            "total_cost": "0.002699",
                        },
                    }
                }),
                encoding="utf-8",
            )
            client = _failure_replay_client(
                failure_path,
                load_pipeline_config(DEFAULT_CONFIG_PATH),
            )

            run_stage5(
                input_paths["stage0"],
                input_paths["stage2"],
                input_paths["stage3"],
                input_paths["stage4"],
                output_path,
                client,
                rendered_prompt(),
                self.methods,
                self.vocabulary,
                self.vocabulary_hash,
                force=True,
                max_validation_retries=0,
            )

            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(client.calls, 1)
            self.assertEqual(result["provenance"]["model"], "saved-model")
            self.assertEqual(result["provenance"]["usage"]["input_tokens"], 100)
            self.assertEqual(result["provenance"]["cost"]["total_cost"], "0.002699")
            self.assertTrue(any(
                item["code"] == "failure_response_replayed"
                for item in result["warnings"]
            ))

    def test_failure_replay_requires_saved_raw_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            failure_path = Path(temp_dir) / "stage5_failure.json"
            failure_path.write_text(
                json.dumps({"raw_response": None}),
                encoding="utf-8",
            )

            with self.assertRaises(Stage5Error):
                _failure_replay_client(
                    failure_path,
                    load_pipeline_config(DEFAULT_CONFIG_PATH),
                )

    def test_cli_failure_writes_raw_response_audit(self) -> None:
        client = FakeClient()
        client.call_history = []
        client.last_raw_response = None
        usage = LLMTokenUsage(input_tokens=11, output_tokens=7)

        def fail_after_response(*args, **kwargs):
            client.call_history.append(LLMCallRecord(
                provider="test",
                model="fake-actual",
                usage=usage,
                cost=None,
                usage_available=True,
            ))
            client.last_raw_response = LLMRawResponse(
                provider="test",
                model="fake-actual",
                finish_reason="stop",
                content='{"characterizations": []}',
                usage=usage,
                cost=None,
            )
            raise Stage5Error("schema failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            argv = [
                "stage5_characterization.py",
                "--ref-no",
                "reference_no_0000002",
                "--input-root",
                str(root),
                "--output-root",
                str(root),
            ]
            with (
                patch.object(
                    stage5_module.LLMClient,
                    "from_pipeline_config",
                    return_value=client,
                ),
                patch.object(
                    stage5_module,
                    "run_stage5",
                    side_effect=fail_after_response,
                ),
                patch.object(sys, "argv", argv),
            ):
                status = stage5_module.main()

            audit_path = (
                root
                / "reference_no_0000002"
                / "stage5_failure.json"
            )
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(status, 1)
            self.assertEqual(audit["usage"]["input_tokens"], 11)
            self.assertEqual(
                audit["raw_response"]["content"],
                '{"characterizations": []}',
            )

    def test_historical_method_aliases_map_uniquely(self) -> None:
        self.assertEqual(
            _method_names_for_raw(
                "scanning electron microscope",
                self.methods,
            ),
            {"SEM"},
        )
        self.assertEqual(
            _method_names_for_raw("Infrared Absorption", self.methods),
            {"FTIR"},
        )
        self.assertEqual(
            _method_names_for_raw("Thermal Degradation", self.methods),
            {"TGA"},
        )
        self.assertEqual(
            _method_names_for_raw(
                "thermogravimetric analyses conducted in nitrogen",
                self.methods,
            ),
            {"TGA"},
        )
        self.assertEqual(
            _method_names_for_raw(
                "Inherent viscosities were obtained from polymer solutions",
                self.methods,
            ),
            {"viscometry"},
        )
        self.assertEqual(
            _method_names_for_raw("x-ray diffractions", self.methods),
            {"XRD"},
        )
        self.assertEqual(
            _method_names_for_raw(
                "The IR spectra of polymers were scanned in KBr pellets",
                self.methods,
            ),
            {"FTIR"},
        )

    def test_short_method_alias_does_not_match_inside_word(self) -> None:
        raw = "polymer was placed on a metal block"

        self.assertNotIn(
            "viscometry",
            _method_names_for_raw(raw, self.methods),
        )

    def test_untraceable_property_name_falls_back_to_raw_value(self) -> None:
        response = FakeClient().call_json("", "").data
        candidate = CharacterizationStageResponse.model_validate(response)
        item = candidate.properties[0].model_copy(update={
            "property_name_raw": "invented peak label",
        })
        document = stage0_document()
        block_map = {block.block_id: block for block in document.elements}
        characterization = candidate.characterizations[0]

        normalized = _normalize_stage5_property(
            item,
            block_map,
            characterization,
            self.vocabulary,
        )

        self.assertEqual(normalized.property_name_raw, item.value_raw)

    def _material_char_blocks(self, *texts: str) -> list[object]:
        """构造只含指定正文的 stage0 blocks，用于单测 plan_shards 分流。"""
        document = Stage0Document.model_validate({
            "schema_version": "1.0",
            "source_document_schema_version": "1.0",
            "document_id": "reference_no_0000009",
            "paper": {
                "ref_no": "reference_no_0000009",
                "pdf_filename": "uuid_origin.pdf",
                "source_pdf_path": "mineru_output/x/uuid_origin.pdf",
                "organized_pdf_path": "wenxian/x/origin.pdf",
                "doi": None,
                "title": "Material characteristics demo",
                "authors": ["A. Author"],
                "journal": "Journal",
                "year": 2026,
                "metadata_status": "partial",
                "metadata_extraction": {"status": "success"},
            },
            "source_files": {},
            "ocr": {"status": "done"},
            "elements": [
                {
                    "block_id": f"P_1_{index}",
                    "type": "text",
                    "section": "Results",
                    "text": text,
                    "page": 1,
                    "bbox": [1, 2, 3, 4],
                    "source_block_index": index,
                }
                for index, text in enumerate(texts)
            ],
            "warnings": [],
        })
        return list(document.elements)

    def test_plan_shards_routes_material_characteristics_without_method_keyword(
        self,
    ) -> None:
        """无任何表征方法关键词，仅凭 33 个受控词命中即应单独分片。"""
        blocks = self._material_char_blocks(
            "The obtained polymer is a linear, thermoplastic resin.",
        )

        shards, unrouted = plan_shards(blocks, self.methods)

        by_method = {item.method_normalized: item for item in shards}
        self.assertIn("material_characteristics", by_method)
        self.assertEqual(
            [block.block_id for block in by_method["material_characteristics"].blocks],
            ["P_1_0"],
        )
        # 已分流的块不得同时留在 unrouted，否则会被重复送模型。
        self.assertNotIn("P_1_0", [block.block_id for block in unrouted])

    def test_plan_shards_matches_parenthesized_material_char_term(self) -> None:
        """`Non-linear optical(NLO)` 以括号结尾，\\b 边界会漏匹配，需用环视。"""
        blocks = self._material_char_blocks(
            "Non-linear optical(NLO) response was observed for the films.",
        )

        shards, _ = plan_shards(blocks, self.methods)

        self.assertIn(
            "material_characteristics",
            {item.method_normalized for item in shards},
        )

    def test_plan_shards_does_not_route_text_without_material_char_term(self) -> None:
        """不含受控词也不含方法词的块应留在 unrouted，不得凭空造分片。"""
        blocks = self._material_char_blocks(
            "The reaction mixture was stirred overnight and then filtered.",
        )

        shards, unrouted = plan_shards(blocks, self.methods)

        self.assertNotIn(
            "material_characteristics",
            {item.method_normalized for item in shards},
        )
        self.assertEqual(len(unrouted), 1)

    def test_method_shard_wins_over_material_characteristics(self) -> None:
        """同时含方法词与受控词时归方法分片，避免同一块被两处抽取。"""
        blocks = self._material_char_blocks(FTIR_SENTENCE + " The polymer is linear.")

        shards, _ = plan_shards(blocks, self.methods)

        owners = {
            block.block_id: item.method_normalized
            for item in shards
            for block in item.blocks
        }
        self.assertEqual(owners.get("P_1_0"), "FTIR")


if __name__ == "__main__":
    unittest.main()
