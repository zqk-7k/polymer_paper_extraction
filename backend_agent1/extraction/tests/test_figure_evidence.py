from stages.figure_evidence import build_figure_index, related_figures


def test_only_caption_and_explicit_body_reference_link_to_figure(tmp_path):
    (tmp_path / "figure.png").write_bytes(b"opaque image bytes, never decoded")
    stage0 = {"document_id": "paper", "elements": [
        {"block_id": "I1", "type": "image", "page": 1, "caption": "FIG. 7. Tg of A is 120 C.", "image_path": "figure.png"},
        {"block_id": "P1", "type": "text", "page": 1, "text": "As shown in Fig. 7a, A remained stable."},
        {"block_id": "T1", "type": "table", "page": 1, "caption": "Table 7. B at 150 C"},
        {"block_id": "P2", "type": "text", "page": 2, "text": "See Fig. 8."}]}
    result = build_figure_index(stage0, asset_root=tmp_path)
    figure = result["figures"][0]
    assert figure["figure_id"] == "Fig.7"
    assert figure["image_link_status"] == "available"
    assert len(figure["image_sha256"]) == 64
    assert [r["block_id"] for r in figure["body_references"]] == ["P1"]
    assert result["unresolved_references"][0]["figure_id"] == "Fig.8"
    assert related_figures(stage0, {"T1"}) == []
    assert related_figures(stage0, {"P1"})[0]["caption_raw"] == figure["caption_raw"]
    assert result["image_value_extraction"] == "disabled"


def test_duplicate_figures_and_missing_files_remain_unresolved(tmp_path):
    stage0 = {"elements": [{"block_id": key, "type": "image", "caption": "Fig. 1. Caption", "image_path": "missing.png"} for key in ("I1", "I2")]
        + [{"block_id": "P1", "type": "text", "text": "Figure 1 shows the result."}]}
    result = build_figure_index(stage0, asset_root=tmp_path)
    assert result["unresolved_references"][0]["reason"] == "duplicate_figure_id"
    assert all(f["image_link_status"] == "file_missing" and not f["body_references"] for f in result["figures"])
