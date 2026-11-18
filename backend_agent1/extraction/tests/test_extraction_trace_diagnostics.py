from stages.extraction_trace_diagnostics import diagnose_response_trace


def test_locator_tracing_is_distinct_from_numeric_capture_and_catalog_gate():
    inventory = [{"table_id":"T", "cell_id":"T:r0001:c0001", "value_raw":"71.6(71.9)",
                  "eligible_for_capture":False, "composite_diagnostic":{"status":"explicit_parenthetical_pair"}}]
    item = {"property_id":"prop001", "property_name_raw":"Uncatalogued", "value_raw":"71.6",
            "evidence":[{"block_id":"T", "table_locator":{"row_index":1,"column_index":1}}]}
    result = diagnose_response_trace(inventory, [], [item], [item])
    row = result["cells"][0]
    assert not row["local_candidate_generated"] and row["response_locator_present"]
    assert result["uncatalogued_response_items"][0]["final_id_present"]
    assert not row["interpretation_metadata_is_capture_proof"]
    item["evidence"]=[]
    result = diagnose_response_trace(inventory, [], [item], [])
    assert result["cells"][0]["status"]=="response_not_traced"
    assert result["response_items_without_cell_locator"]==1


def test_final_derived_cell_context_is_traceable_without_registry_locator():
    inventory=[{"table_id":"T","cell_id":"T:r0001:c0001","value_raw":"12","eligible_for_capture":True}]
    final={"value_raw":"12","evidence":[],"value_derivation":{"source_semantics":{"source_contexts":[
        {"block_id":"T","source_cell_id":"T:r0001:c0001","scope":"table_cell"}]}}}
    result=diagnose_response_trace(inventory,[],[],[final])
    assert result["cells"][0]["final_locator_present"]
    assert result["cells"][0]["status"]=="response_not_traced"


def test_unparsed_outside_catalog_shadow_is_included_in_diagnostics():
    inventory=[{"table_id":"T","cell_id":"T:r0001:c0001","value_raw":"13·30",
                "eligible_for_capture":False,"composite_diagnostic":{"status":"not_composite"}}]
    shadow=[{"table_id":"T","cell_id":"T:r0001:c0001","value_raw":"13·30"}]
    row=diagnose_response_trace(inventory,shadow,[],[])["cells"][0]
    assert row["local_candidate_generated"] and not row["response_locator_present"]


def test_renumbered_catalog_free_property_uses_source_trace_not_id_as_proof():
    item={"property_id":"prop010","property_name_raw":"Unknown","value_raw":"12",
          "evidence":[{"block_id":"T","table_locator":{"cell_id":"T:r0001:c0001"}}]}
    row=diagnose_response_trace([],[],[item],[{**item,"property_id":"prop001"}])["uncatalogued_response_items"][0]
    assert not row["final_id_present"] and row["final_source_cell_trace_present"]
    assert not row["id_presence_is_retention_proof"]
