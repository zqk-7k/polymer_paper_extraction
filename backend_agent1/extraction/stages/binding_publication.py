"""Publication options require independently source-checked binding identities."""


def binding_publication_options(check):
    located = check.get("evidence_status") == "source_cell_verified" and check.get("path_status") == "complete"
    return {
        "allow_article_alias": bool(located and check.get("binding_status") == "article_alias_confirmed"
            and check.get("article_sample_key") and check.get("binding_basis") in {"row_label", "column_label"}),
        "allow_entity_only": bool(located and check.get("binding_status") == "entity_only"
            and check.get("entity_source_proof") and check.get("binding_basis") == "entity_source_axis"),
    }
