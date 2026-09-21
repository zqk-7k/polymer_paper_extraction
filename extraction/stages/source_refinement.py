"""Single source-only refinement entry shared by Stage4 and evolution replay.

No gold, PoLyInfo, experiment references or evaluation modules are imported.
Keeps the existing numbered pipeline; repairs execute within property Stage4.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from functools import lru_cache

from stages.stage4_direct_text_supplement import merge_text
from stages.stage4_direct_table_supplement import merge_supplement
from stages.source_standard_unit_resolution import resolve_standard_units
from stages.source_quantity_normalization import normalize_source_quantities
from stages.stage4_aligned_table_release import recover_aligned_temperature_rows
from stages.source_phase_transitions import recover_phase_transitions
from stages.source_peak_lists import recover_peak_lists
from stages.source_diffraction_lists import recover_diffraction_lists
from stages.source_display_scaling import repair_display_scales
from stages.source_verified_exponent_runs import repair_verified_exponent_runs
from stages.source_explicit_thermal_cells import recover_explicit_thermal_cells
from stages.source_prose_loss_facts import recover_prose_loss_facts
from stages.source_subject_labels import preserve_prose_subject_labels

VERSION='1.7.0'


@lru_cache(maxsize=1)
def runtime_fingerprint():
    folder=Path(__file__).resolve().parent
    paths=[Path(__file__),*folder.glob('source_*.py'),*folder.glob('stage4_*supplement.py'),
           folder/'stage4_aligned_table_release.py',folder/'stage4_symbol_condition_binding.py']
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
    return hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()


def refine_source_properties(stage4,stage0,*,table_responses=(),text_responses=()):
    output,table_audit=merge_supplement(stage4,list(table_responses))
    output,text_audit=merge_text(output,stage0,list(text_responses))
    output,unit_audit=resolve_standard_units(output,stage0)
    output,alignment_audit=recover_aligned_temperature_rows(output,stage0)
    output,phase_audit=recover_phase_transitions(output,stage0)
    output,peak_audit=recover_peak_lists(output,stage0)
    output,diffraction_audit=recover_diffraction_lists(output,stage0)
    output,display_audit=repair_display_scales(output,stage0)
    output,run_audit=repair_verified_exponent_runs(output,stage0)
    output,explicit_thermal_audit=recover_explicit_thermal_cells(output,stage0)
    output,prose_loss_audit=recover_prose_loss_facts(output,stage0)
    output,subject_label_audit=preserve_prose_subject_labels(output,stage0)
    output,quantity_audit=normalize_source_quantities(output)
    return output,{'version':VERSION,'runtime_fingerprint':runtime_fingerprint(),
        'table':table_audit,'text':text_audit,'standard_units':unit_audit,
        'aligned_rows':alignment_audit,'phase_transitions':phase_audit,'peak_lists':peak_audit,'quantity_normalization':quantity_audit,
        'diffraction_lists':diffraction_audit,'display_scales':display_audit,
        'verified_exponent_runs':run_audit,'explicit_thermal_cells':explicit_thermal_audit,
        'prose_loss_relations':prose_loss_audit,'source_subject_labels':subject_label_audit,'gold_access':False}
