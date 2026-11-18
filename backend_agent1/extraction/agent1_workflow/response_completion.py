"""Response completeness contract, not scientific quality review."""
class UnexplainedEmptyResponseError(ValueError):pass
GUIDANCE='''
Completion contract: If all result arrays AND unresolved are empty, include
completion_explanation:{scope:"all_supplied_sources",reason:"specific reason this assigned field group/table has no reportable result"}.
An empty JSON result without this explanation is an incomplete task, not proof the article reports nothing.
Do not invent measurements to avoid an empty result. Use unresolved for evidence or identity gaps.
'''
def validate(data,stage):
    fields={'stage3_sample_process':('sample_updates','state_samples','protocols','state_transitions'),
            'stage4_property':('observations',),
            'stage4t_table_interpretation':('property_axes','subject_axes','condition_axes','cell_overrides'),
            'stage5_characterization':('observations','spectrum_groups','methods')}.get(stage,())
    if not fields or any(data.get(k) for k in (*fields,'unresolved')):return
    explanation=data.get('completion_explanation')
    if not isinstance(explanation,dict) or explanation.get('scope')!='all_supplied_sources' or len(str(explanation.get('reason') or '').strip())<12:
        raise UnexplainedEmptyResponseError('Empty result without a source-coverage explanation')
