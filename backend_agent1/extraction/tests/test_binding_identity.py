from stages.binding_identity import build_article_sample_key, classify_binding_status


def test_article_sample_key_is_stable_and_scope_local():
    first = build_article_sample_key(
        "reference_no_1", "T1", " IZO-3 ", variant_context={"dose": "5 kGy", "unit": "h"}
    )
    second = build_article_sample_key(
        "reference_no_1", "T1", "IZO-3", variant_context={"unit": "h", "dose": "5 kGy"}
    )
    assert first == second
    assert first.startswith("article_sample_")
    assert first != build_article_sample_key("reference_no_1", "T2", "IZO-3", variant_context={"dose": "5 kGy"})
    assert first != build_article_sample_key("reference_no_1", "T1", "IZO-3", variant_context={"dose": "10 kGy"})


def test_binding_status_distinguishes_sample_alias_and_entity():
    assert classify_binding_status(
        selected_sample_id="s001", selected_entity_id=None, article_sample_key=None,
        reasoning_status="accepted", validation_passed=True,
    ) == "resolved"
    assert classify_binding_status(
        selected_sample_id=None, selected_entity_id=None, article_sample_key="article_sample_x",
        reasoning_status="accepted", validation_passed=True,
    ) == "article_alias_confirmed"
    assert classify_binding_status(
        selected_sample_id=None, selected_entity_id="pe001", article_sample_key=None,
        reasoning_status="accepted", validation_passed=True,
    ) == "entity_only"
    assert classify_binding_status(
        selected_sample_id="s001", selected_entity_id=None, article_sample_key=None,
        reasoning_status="accepted", validation_passed=False,
        validation_errors=["candidate_sample_conflict"],
    ) == "conflict"
