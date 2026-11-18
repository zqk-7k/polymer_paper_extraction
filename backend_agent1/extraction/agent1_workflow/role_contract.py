"""Separate source derivation from method documentation; no receiver promotion."""
from evidence_handoff import GUIDANCE as PREVIOUS
GUIDANCE=PREVIOUS.split('Data roles:')[0]+'''
Role contract v2. Determine two independent dimensions for each property axis:
1. value_role and role_evidence_refs: how the source presents the result.
2. method_reporting: described | referenced | not_stated | unclear, with
method_reporting_reason_raw. Lack of a detailed instrument or procedure belongs
only to dimension 2; it is NOT, by itself, evidence that value_role is unknown.

measured: contextual source evidence presents the values as experimental results
for the authors' specimens (including an experimental results table and its
caption/narrative). A complete measurement procedure is not required. Cite the
actual contextual basis; never invent an instrument or procedure.
calculated: the source explicitly derives this quantity by a calculation or
equation from other quantities. Preserve that classification even when all inputs
were measured, and even when the method is completely described.
For source-identified experimental fitted parameters use unknown with role_detail
experimental_fit, retaining evidence. They remain outside scoring for this project.
unknown: the source context genuinely leaves competing origins unresolved, such
as mixed measured/predicted values without a row/column distinction. Explain that
ambiguity; do not use missing method details alone as the explanation.
predicted and reference retain their existing meanings and exclusions.

Do not assume measured just because a cell is numeric, because a familiar field
usually is measured, or because no equation was found. Require a positive source
context linking the reported quantity to experimental specimen results. Respect
explicit calculated/fitted/reference statements and local footnote scopes over
a broad experimental table title. If such context is absent, retain unknown.
Return role_reason_raw and role_evidence_refs, plus the independent method fields.
All other task requirements, raw values, conditions, identity and source boundaries
remain unchanged. Do not compute or convert any values. Do not extract figures.
'''

CASES=[
 {'id':'experimental_missing_method','source':'Experimental results for specimens A and B. Table: measured tensile stress, 21 and 24 MPa. No instrument or procedure is specified.','expected_role':'measured','expected_method':'not_stated'},
 {'id':'calculated_measured_inputs','source':'Surface energy was calculated from experimentally measured contact angles using the stated equation. Full procedures are described.','expected_role':'calculated','expected_method':'described'},
 {'id':'fitted_parameter','source':'The conductivity parameter was obtained by fitting measured dielectric spectra to the response model. The fitting procedure is described.','expected_role':'unknown','expected_detail':'experimental_fit'},
 {'id':'mixed_origins','source':'Values combine experimental measurements and simulation predictions. The table does not indicate which rows came from which source.','expected_role':'unknown'},
 {'id':'unlabelled_numbers','source':'A 10; B 20. No caption, quantity, origin or explanation is available.','expected_role':'unknown'}]
