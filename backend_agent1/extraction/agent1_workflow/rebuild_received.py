from stage4r import source_index
from subject_axis_adapter import canonical,bind_records,receive,scope_record
from metadata_roles import separate
from reference_location import receive as receive_reference
def install():
    import mapping_contract,finalize
    from range_evidence import install as ranges
    from cell_evidence import install as cells
    from header_coordinates import install as headers
    from legend_scope import install as legends
    ranges();cells();headers();legends()
    if getattr(mapping_contract,'subject_axis_projection_installed',False):return
    old_read=mapping_contract.read_table;old_record=finalize.observation_record
    def read(task,response,target_ids,sample_ids):
        from ownership import ENABLED
        identity=task.get('_owner_identity')
        if identity is None or not ENABLED.get():return old_read(task,response,target_ids,sample_ids)
        from composition_endpoint import project as endpoints,annotate as annotate_endpoints
        projected,audit=canonical(task['source_table'],response,identity)
        from subject_scope import project
        projected,scope_audit=project(task,projected,identity)
        projected,endpoint_audit=endpoints(task['source_table'],projected,identity)
        rows,info=old_read(task,projected,target_ids,sample_ids)
        rows=bind_records(rows,task['source_table'],projected)
        rows=annotate_endpoints(rows,task['source_table'],projected)
        info['composition_endpoint_reception']=endpoint_audit
        info['subject_axis_reception']=audit
        info['subject_region_reception']=scope_audit
        return rows,info
    def record(observation,ref,raw,identity,catalog,owned_ids,evidence_ids=None):
        row=old_record(observation,ref,raw,identity,catalog,owned_ids,evidence_ids)
        def base(clean,**kw):return old_record(clean,ref,kw['raw'],kw['identity'],kw['catalog'],kw['owned_ids'],kw['evidence_ids'])
        row=separate(observation,row,raw,identity,catalog,owned_ids,evidence_ids,base)
        blocks,cells=source_index(raw)
        def validate(clean):
            initial=old_record(clean,ref,raw,identity,catalog,owned_ids,evidence_ids)
            return separate(clean,initial,raw,identity,catalog,owned_ids,evidence_ids,base)
        row=receive_reference(observation,row,blocks,set(owned_ids if evidence_ids is None else evidence_ids),validate)
        row=receive(row,observation,identity,blocks,cells)
        row = scope_record(row,observation,identity)
        from subject_roles import explicit_monomers, annotate as annotate_role
        from stage3_completion import source_proof
        finalize.reclassify_catalog_annotation(row, observation)
        if observation.get('composition_endpoint_binding'):
            row['composition_endpoint_binding']=observation['composition_endpoint_binding']
        return annotate_role(row, explicit_monomers(identity, blocks, source_proof))
    mapping_contract.read_table=read;finalize.observation_record=record
    mapping_contract.subject_axis_projection_installed=True
