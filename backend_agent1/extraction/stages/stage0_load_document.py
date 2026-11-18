"""Stage 0：加载标准化 document JSON 并重建受控 section。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EXTRACTION_ROOT.parent.parent
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))

from llm_client import DEFAULT_CONFIG_PATH, load_pipeline_config
from schema.polymer_schema import (
    SourceDocument,
    SourceElement,
    Stage0Document,
    Stage0Element,
)
from stages.table_grid import parse_table_cells


SECTION_ROUTING_VERSION = "section_routing.v2"
SECTION_ALIASES = {
    "Methods": {
        "experimental",
        "experimental part",
        "experimental section",
        "methods",
        "materials and methods",
        "synthesis",
        "preparation",
        "procedure",
    },
    "Results": {
        "results",
        "results and discussion",
        "discussion",
        "experimental comparison",
    },
    "Introduction": {
        "introduction",
        "background",
    },
    "Abstract": {
        "abstract",
        "synopsis",
    },
    "Conclusion": {
        "conclusion",
        "conclusions",
        "summary and conclusion",
        "summary and conclusions",
    },
}
REFERENCE_HEADINGS = {
    "reference",
    "references",
    "bibliography",
}
RETAINED_TYPES = {
    "text",
    "title",
    "table",
    "image",
    "equation",
    "footnote",
}


class Stage0Error(RuntimeError):
    """Stage 0 输入、Schema 或文件操作失败。"""


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def load_source_document(path: Path) -> SourceDocument:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return SourceDocument.model_validate(raw)
    except OSError as exc:
        raise Stage0Error(f"无法读取 document JSON：{path}") from exc
    except json.JSONDecodeError as exc:
        raise Stage0Error(f"document JSON 格式无效：{path}") from exc
    except ValidationError as exc:
        raise Stage0Error(f"document JSON 未通过 Schema：{path.name}") from exc


def recover_missing_equations(source: SourceDocument) -> SourceDocument:
    """Recover legacy omissions from the document's own organized OCR, without editing it."""
    pdf = Path(source.paper.organized_pdf_path)
    if not pdf.is_absolute():
        pdf = PROJECT_ROOT / pdf
    content = pdf.parent / str(source.source_files.get("content_v1") or "content.json")
    if not content.is_file():
        return source
    raw = json.loads(content.read_text(encoding="utf-8-sig"))
    if isinstance(raw, dict) and raw.get("document_id", source.document_id) != source.document_id:
        raise Stage0Error("组织后的 OCR 文献编号不一致")
    blocks = raw.get("blocks", []) if isinstance(raw, dict) else raw
    if not isinstance(blocks, list):
        raise Stage0Error("组织后的 OCR blocks 必须为数组")
    result = source.model_copy(deep=True)
    occupied = {(e.page_id, e.block_index) for e in result.elements}
    ids = {e.block_id for e in result.elements}
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("type") != "equation":
            continue
        page = int(block.get("page_idx", 0))
        text = str(block.get("text") or "")
        if not text.strip() or (page, index) in occupied:
            continue
        bid = f"E_{page}_{index}"
        if bid in ids:
            raise Stage0Error(f"公式恢复遇到重复 block_id：{bid}")
        result.elements.append(SourceElement(block_id=bid, page_id=page, block_index=index,
            element_type="equation", text=text, bbox=block.get("bbox"),
            equation_kind="unresolved", alignment_status="unresolved"))
        result.warnings.append(_stage0_warning("equation_recovered_from_ocr",
            f"从 {content} 的 blocks[{index}] 补回独立公式，保留原文", bid))
    result.elements.sort(key=lambda e: (e.block_index, e.page_id, e.block_id))
    return result


def _normalize_heading(text: str) -> str:
    normalized = text.casefold().strip()
    normalized = re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s*", "", normalized)
    normalized = re.sub(r"[\s:：.;。]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def infer_section(
    title_text: str,
    current_section: str | None,
) -> str | None:
    normalized = _normalize_heading(title_text)
    if normalized in REFERENCE_HEADINGS:
        return "References"
    if normalized == "summary":
        if current_section in {"Methods", "Results", "Conclusion"}:
            return "Conclusion"
        return "Abstract"
    for section, aliases in SECTION_ALIASES.items():
        if normalized in aliases:
            return section
    return current_section


def _stage0_warning(code: str, message: str, block_id: str) -> dict[str, Any]:
    return {
        "stage": "stage0",
        "code": code,
        "message": message,
        "block_id": block_id,
    }


def _element_payload(
    source: SourceElement,
    *,
    element_type: str,
    section: str | None,
    equation_kind: str | None = None,
) -> dict[str, Any]:
    data = source.model_dump(mode="python")
    payload: dict[str, Any] = {
        "block_id": source.block_id,
        "type": element_type,
        "section": section,
        "page": source.page_id,
        "bbox": source.bbox,
        "source_block_index": source.block_index,
        "alignment_status": source.alignment_status,
    }
    for key in (
        "text",
        "title_level",
        "caption",
        "table_body",
        "image_path",
        "image_kind",
        "merged_source_block_ids",
        "content",
    ):
        if key in data:
            payload[key] = data[key]
    if equation_kind is not None:
        payload["equation_kind"] = equation_kind
    if element_type == "table":
        notes = []
        for key in ("table_notes", "table_footnote", "footnotes", "notes"):
            value = data.get(key)
            for text in value if isinstance(value, list) else [value]:
                if isinstance(text, str) and text.strip() and text not in notes:
                    notes.append(text)
        payload["table_notes"] = notes
    if element_type == "table" and payload.get("table_body") is not None:
        payload["table_cells"] = [
            cell.model_dump(mode="python")
            for cell in parse_table_cells(
                str(payload["table_body"]),
                source.block_id,
            )
        ]
    return payload


def load_document_elements(source: SourceDocument) -> Stage0Document:
    current_section: str | None = None
    output_elements: list[Stage0Element] = []
    warnings = [dict(warning) for warning in source.warnings]

    for element in source.elements:
        element_type = element.element_type
        data = element.model_dump(mode="python")
        if element_type == "references":
            continue
        if element_type not in RETAINED_TYPES:
            warnings.append(_stage0_warning(
                "unsupported_element_type",
                f"跳过 Stage 0 不支持的 element_type={element_type!r}",
                element.block_id,
            ))
            continue

        if element_type == "title":
            title_text = str(data.get("text") or "")
            if data.get("section") == "DocumentTitle":
                section = "DocumentTitle"
            else:
                current_section = infer_section(title_text, current_section)
                section = current_section
            payload = _element_payload(
                element,
                element_type=element_type,
                section=section,
            )
        elif element_type == "equation":
            raw_kind = str(data.get("equation_kind") or "unresolved")
            if raw_kind not in {"display", "unresolved"}:
                warnings.append(_stage0_warning(
                    "inline_equation_skipped",
                    "跳过已应合并进正文的 inline equation element",
                    element.block_id,
                ))
                continue
            payload = _element_payload(
                element,
                element_type=element_type,
                section=current_section,
                equation_kind=raw_kind,
            )
        else:
            payload = _element_payload(
                element,
                element_type=element_type,
                section=current_section,
            )
        try:
            normalized = Stage0Element.model_validate(payload)
            output_elements.append(normalized)
            if normalized.type == "table" and not normalized.table_cells:
                warnings.append(_stage0_warning(
                    "table_grid_unavailable",
                    "表格无法解析为稳定单元格网格",
                    normalized.block_id,
                ))
        except ValidationError as exc:
            raise Stage0Error(
                f"Stage 0 element 未通过 Schema：{element.block_id}"
            ) from exc

    return Stage0Document(
        source_document_schema_version=source.schema_version,
        document_id=source.document_id,
        paper=source.paper,
        source_files=source.source_files,
        ocr=source.ocr,
        elements=output_elements,
        warnings=warnings,
    )


def rebuild_sections(document: Stage0Document) -> tuple[Stage0Document, list[dict[str, Any]]]:
    """Re-route saved elements without changing source content or evidence IDs."""
    result = document.model_copy(deep=True)
    current_section = None
    changes = []
    for element in result.elements:
        if element.type == "title" and element.section == "DocumentTitle":
            continue
        if element.type == "title":
            current_section = infer_section(element.text or "", current_section)
        if element.section != current_section:
            changes.append({"block_id": element.block_id, "before": element.section, "after": current_section})
            element.section = current_section
    return result, changes


def run_stage0(
    document_path: Path,
    output_root: Path,
    *,
    force: bool = False,
) -> tuple[Path, bool]:
    ref_no = document_path.name.removesuffix("_document.json")
    output_path = output_root / ref_no / "stage0_blocks.json"
    source = recover_missing_equations(load_source_document(document_path))
    if source.document_id != ref_no:
        raise Stage0Error(f"文件名文献编号与 document_id 不一致：{document_path.name}")
    result = load_document_elements(source)
    if output_path.is_file() and not force:
        try:
            cached = json.loads(output_path.read_text(encoding="utf-8-sig"))
            cached_document = Stage0Document.model_validate(cached)
            # 比较实际派生输入，脚注、表体、正文及元数据变化均不能复用旧缓存。
            if cached_document.model_dump(mode="json") != result.model_dump(mode="json"):
                raise ValueError("Stage 0 缓存与当前标准文档不一致")
            expected = {(e.block_id, e.model_dump().get("text")) for e in source.elements
                        if e.element_type == "equation" and e.model_dump().get("equation_kind", "unresolved") in {"display", "unresolved"}}
            actual = {(e.block_id, e.text) for e in cached_document.elements if e.type == "equation"}
            if expected != actual:
                raise ValueError("Stage 0 公式缓存与原始输入不一致")
            if "doi" not in (cached.get("paper") or {}):
                raise ValueError("Stage 0 缓存缺少固定 doi 字段")
            _, section_changes = rebuild_sections(cached_document)
            if section_changes:
                raise ValueError("Stage 0 section routing rules changed")
            if cached_document.schema_version != "1.1" or any(
                item.type == "table" and item.table_cells is None
                for item in cached_document.elements
            ):
                raise ValueError("Stage 0 缓存缺少稳定表格网格")
            return output_path, True
        except (OSError, json.JSONDecodeError, ValidationError, ValueError):
            pass

    if source.document_id != ref_no:
        raise Stage0Error(
            f"文件名文献编号与 document_id 不一致：{document_path.name}"
        )
    payload = result.model_dump(mode="json", exclude_none=True)
    payload["paper"] = result.paper.model_dump(mode="json", exclude_none=False)
    write_json_atomic(
        output_path,
        payload,
    )
    return output_path, False


def _configured_paths(config_path: Path) -> tuple[Path, Path]:
    config = load_pipeline_config(config_path)
    paths = config.get("paths") or {}
    input_dir = Path(paths.get("input_dir") or PROJECT_ROOT / "processed_data" / "documents")
    output_dir = Path(paths.get("output_dir") or EXTRACTION_ROOT / "output")
    return input_dir, output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行 Stage 0 文档加载与 section 重建")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ref-no")
    mode.add_argument("--batch", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    configured_input, configured_output = _configured_paths(
        args.config.expanduser().resolve()
    )
    input_dir = (
        args.input_dir.expanduser().resolve()
        if args.input_dir
        else configured_input.expanduser().resolve()
    )
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else configured_output.expanduser().resolve()
    )
    if not input_dir.is_dir():
        raise Stage0Error(f"Stage 0 输入目录不存在：{input_dir}")

    if args.ref_no:
        document_paths = [input_dir / f"{args.ref_no}_document.json"]
    else:
        document_paths = sorted(input_dir.glob("reference_no_*_document.json"))
    if not document_paths:
        raise Stage0Error(f"未找到 document JSON：{input_dir}")

    failures: list[tuple[str, str]] = []
    for document_path in document_paths:
        try:
            output_path, cached = run_stage0(
                document_path,
                output_dir,
                force=args.force,
            )
            state = "cached" if cached else "done"
            print(f"[{state}] {output_path}")
        except Exception as exc:
            failures.append((document_path.name, type(exc).__name__))
            print(
                f"[failed] {document_path.name}: {type(exc).__name__}",
                file=sys.stderr,
            )
    print(f"Stage 0 完成：成功 {len(document_paths) - len(failures)}，失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
