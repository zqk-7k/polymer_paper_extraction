"""Short extraction contracts derived from configured field names and subtype boundaries.

These are operational mapping definitions, not new measurements or a standards crosswalk.
No source-specific answers or benchmark labels enter the definitions or routing.
"""
import re
from common import *

SPECIFIC = {
 'density': 'Reported material mass per volume; retain source state and temperature.',
 'specific_volume': 'Reported volume per mass; do not calculate from density.',
 'refractive_index': 'Reported optical refractive index with wavelength, direction and state.',
 'stress_optical_coefficient': 'Reported stress-optical coefficient; preserve its definition and measurement conditions.',
 'crystallization_kinetics': 'Reported crystallization rate, time or kinetic parameters; retain parameter name and method.',
 'crystallization_temperature': 'Reported crystallization temperature; distinguish a property from a Tc test condition.',
 'glass_transition_temperature': 'Reported glass transition Tg; retain method and thermal history.',
 'heat_of_crystallization': 'Reported crystallization heat or enthalpy; do not compute crystallinity from it.',
 'heat_of_fusion': 'Reported melting/fusion heat or enthalpy; preserve mass basis.',
 'thermal_decomposition_temperature': 'Reported decomposition temperature Td; retain loss criterion and atmosphere on the SAME record.',
 'thermal_decomposition_weight_loss': 'Reported decomposition mass-loss percentage or threshold; link to Td without inventing a separate measured value.',
 'contact_angle': 'Reported contact angle with liquid, surface state and test conditions.',
 'lc_phase_transition_temperature': 'Reported liquid-crystal phase transition temperature with named phases.',
 'linear_expansion_coefficient': 'Reported linear thermal expansion coefficient; retain direction and temperature interval.',
 'melting_temperature': 'Reported melting transition temperature Tm; distinguish from Tg and softening.',
 'specific_heat_capacity_cp': 'Reported constant-pressure specific heat capacity Cp; do not substitute Cv.',
 'specific_heat_capacity_cv': 'Reported constant-volume specific heat capacity Cv; do not substitute Cp.',
 'thermal_conductivity': 'Reported heat conductivity with direction, temperature and material state.',
 'thermal_diffusivity': 'Reported thermal diffusivity; do not compute it from other thermal properties.',
 'volume_expansion_coefficient': 'Reported volumetric thermal expansion coefficient; distinguish from linear expansion.',
 'dielectric_breakdown_voltage': 'Reported dielectric breakdown voltage; do not relabel breakdown field strength without definition support.',
 'dielectric_constant_dc': 'Explicit DC/static dielectric constant only; an AC value at kHz/MHz is not automatically DC.',
 'dielectric_dispersion': 'Reported frequency dependence of dielectric response, with original quantity and frequency.',
 'electric_conductivity': 'Reported electrical conductivity, preserving AC/DC, frequency and test conditions.',
 'surface_resistivity': 'Reported surface resistivity; distinguish from volume resistivity.',
 'volume_resistivity': 'Reported volume resistivity; distinguish from surface resistivity.',
 'cohesive_energy_density': 'Reported cohesive energy density; no derivation from a solubility parameter.',
 'gas_diffusion_coefficient_d': 'Reported gas diffusion coefficient D; retain gas species and conditions.',
 'gas_permeability_coefficient_p': 'Reported gas permeability coefficient P; retain gas species and conditions.',
 'gas_solubility_coefficient_s': 'Reported gas solubility coefficient S; not a qualitative solvent compatibility symbol.',
 'hansen_parameter_delta_d': 'Reported Hansen dispersion component delta_d; retain original component label.',
 'hansen_parameter_delta_h': 'Reported Hansen hydrogen-bonding component delta_h; retain original component label.',
 'hansen_parameter_delta_p': 'Reported Hansen polar component delta_p; retain original component label.',
 'interfacial_tension': 'Reported tension at a specified interface; distinguish from a single liquid surface tension.',
 'solubility_parameter': 'Reported solubility parameter; not a qualitative +/- solubility result.',
 'surface_tension': 'Reported surface tension with material, temperature and surrounding phase.',
 'water_absorption': 'Reported water uptake with conditioning and sample state; not film thickness or fluorine content.',
 'water_vapor_transmission': 'Reported water-vapor transmission/permeation quantity; preserve its name and thickness basis.',
 'diffusion_coefficient': 'Reported solution diffusion coefficient; retain species, medium and conditions.',
 'good_solvent': 'A solvent explicitly supported as good by source meaning; plus-count alone does not prove thermodynamic goodness.',
 'intrinsic_viscosity': 'Explicit intrinsic viscosity [eta]; preserve subtype and route to solution_viscosity canonical field.',
 'non_solvent': 'A named solvent reported as non-dissolving for this sample under the stated conditions; preserve symbol and legend.',
 'poor_solvent': 'A solvent explicitly supported as poor by source meaning; partial solubility alone needs source interpretation.',
 'radius_of_gyration': 'Reported radius of gyration with chain, medium and method.',
 'second_virial_coefficient': 'Reported second virial coefficient with solvent and temperature.',
 'sedimentation_coefficient': 'Reported sedimentation coefficient with medium and conditions.',
 'solvent': 'A named medium reported to dissolve this sample under stated conditions; preserve original symbol, solvent condition and legend.',
 'theta_solvent_theta_temperature': 'Explicit theta solvent/temperature relationship; not any solvent or test temperature.',
 'melt_viscosity': 'Reported melt viscosity with temperature and shear conditions; not solution viscosity.',
 'dynamic_viscosity': 'Reported dynamic viscosity with frequency/shear conditions and source-defined quantity.',
 'brittleness_temperature': 'Reported brittleness temperature; preserve test method.',
 'deflection_temperature_under_load': 'Reported heat-deflection temperature with specified load and method.',
 'softening_temperature': 'Reported softening Ts with method; do not assume a Vicat method.',
 'vicat_softening_temperature': 'Explicit Vicat softening temperature with load and method.',
 'charpy_impact': 'Reported Charpy impact quantity; retain notch, units and specimen conditions.',
 'izod_impact': 'Reported Izod impact quantity; retain notch, units and specimen conditions.',
 'rockwell_hardness': 'Reported Rockwell hardness with scale; no cross-scale conversion.',
 'shore_hardness': 'Reported Shore hardness with scale; no cross-scale conversion.',
 'oxygen_index': 'Reported oxygen index with source units and method.',
 'ul_flammability_code_rating': 'Reported UL flammability class; retain exact categorical code.',
 'ul_temperature_index': 'Reported UL temperature index with source definition.',
 'bulk_modulus': 'Reported bulk modulus; do not derive from another modulus.',
 'compressibility': 'Reported compressibility; do not calculate the inverse of bulk modulus.',
 'g_value': 'Reported radiation-chemistry G value; retain source species, meaning and basis.',
 'pvt_relation': 'Explicitly reported pressure-volume-temperature relationship or observations; no fitted calculation.',
 'radiation_resistance': 'Reported radiation-resistance result with dose, radiation type and criterion.',
 'molecular_weight': 'Reported molecular/molar weight; keep Mn, Mw or other subtype distinct and preserve scales and number formatting.',
 'solution_viscosity': 'Reported solution viscosity; keep intrinsic, inherent, reduced, specific and relative subtypes distinct.',
 'crystallinity': 'Reported crystallinity/crystalline fraction; retain method, component, measured/calculated role and raw fraction/percent.',
 'degree_of_polymerization': 'Reported degree of polymerization with subtype; do not derive from molecular weight.',
 'd_spacing': 'Explicitly reported crystallographic/interlayer spacing with diffraction method; no Bragg-law calculation.',
 'two_theta': 'Reported diffraction angle 2theta with method and reflection; no conversion into d-spacing.',
 'primary_structure_informations': 'Source-explicit primary-chain, end-group, branching/crosslinking or gel information for the sample.',
 'morphology': 'Source-explicit morphology or phase/domain description; no reading sizes from images.',
 'stereoregularity': 'Reported tacticity, cis/trans or stereoregularity information; preserve original descriptor or fraction.',
 'characteristics_of_material': 'Source-explicit material feature/type; preserve categorical wording without inventing a measured number.',
 'ftir_peak_wavenumber': 'Explicit FTIR peak wavenumber written in text/table, with assignment when reported; do not read spectrum pixels.',
 'nmr_chemical_shift': 'Explicit NMR chemical shift with nucleus, solvent and assignment when reported; do not read spectrum pixels.',
 'raman_peak_wavenumber': 'Explicit Raman peak wavenumber written in text/table; do not read spectrum pixels.',
 'xrd_diffraction_peak_2theta': 'Explicit XRD peak angle 2theta with reflection/method; do not read plot pixels.',
 'xrd_crystallinity': 'Explicit XRD-derived crystallinity reported by source; do not calculate from peaks.',
 'morphology_domain_size': 'Explicit domain size written in text/table with microscopy method and scope; no image measurement.',
 'morphology_particle_size': 'Explicit particle size written in text/table with method and scope; no image measurement.',
 'saxs_scattering_peak': 'Explicit SAXS scattering peak coordinate with source units and assignment; do not read plot pixels.'
}

FAMILY_CUES = {
 'thermal': r'therm|calorim|\bDSC\b|\bTGA\b|\bTMA\b|glass|melt|soften|crystalliz|\bT[ _{}\\]*(?:g|s|d|c|m)\b|wt\s*%\s*loss|heat',
 'mechanical': r'tensile|modul|stress|strain|elongat|mechanic|flexur|compress|shear|creep|impact|hardness|strength',
 'electrical': r'dielectr|electri|conductiv|resistiv|permittiv|\bHz\b|\bkHz\b|\bMHz\b',
 'optical': r'optic|refracti|\bUV\b|visib|wavelength|birefring',
 'solution': r'solub|solvent|viscos|inherent|intrinsic|\beta\b|\beta_|\\eta|hydrodynam|virial|gyration|sediment',
 'transport': r'absor|water|diffus|permeab|vapor|vapour|gas|surface|contact\s*angle|tension|Hansen|cohesive',
 'molecular': r'molecular|molar\s*mass|\bGPC\b|\bSEC\b|\bM[ _{}\\]*(?:text\s*\{)?[wn]\b|polymerization\s*degree',
 'structure': r'structur|morpholog|crystall|lamell|spherul|tactic|syndio|isotactic|atactic|crosslink|branch|amorph|thermoplast|thermoset|elastomer',
 'spectroscopy': r'\bIR\b|FTIR|infrared|\bNMR\b|Raman|\bXRD\b|diffraction|\bSAXS\b|\bSEM\b|\bTEM\b|\bAFM\b|wavenumber|chemical\s*shift',
 'other': r'radiation|flammab|\bUL\b|oxygen\s*index|\bpvt\b|compressib|G\s*value'
}

def family(target):
    k = target['property_key']; definition = target['definition']
    if target['section'] == 'stage5_property_vocabulary': return 'spectroscopy'
    if target['section'] == 'specialized_property_vocabulary':
        return 'molecular' if k in ('molecular_weight','degree_of_polymerization') else 'solution' if k=='solution_viscosity' else 'structure'
    group = definition[1] if isinstance(definition, list) else ''
    if group in ('thermal_property','heat_characteristic'): return 'thermal'
    if group == 'optical_property': return 'optical'
    if group == 'electrical_property': return 'electrical'
    if group == 'dilute_solution_property': return 'solution'
    if group == 'rheological_property': return 'mechanical'
    if any(x in group for x in ('tensile','shear','flexural','compression','creep','impact','hardness')): return 'mechanical'
    if group == 'physicochemical_property': return 'transport'
    return 'other'

def definition(target):
    key = target['property_key']
    if key=='tensile_stress_at_break':
        return 'Project mapping policy: source Tensile Strength (including ultimate tensile strength) maps to tensile_stress_at_break. Preserve source wording, subtype, method and unit; do not claim the paper proved identical endpoints. Yield stress remains separate.'
    if key=='crystallinity':
        return 'Reported non-XRD crystallinity/fraction, including calorimetric reports; retain method/component and source measured/calculated role. Explicit XRD crystallinity belongs exclusively to Stage5 xrd_crystallinity; no calculation.'
    if key=='two_theta':
        return 'Source-reported diffraction angle outside explicitly XRD-specific peak reporting. Explicit XRD peak 2theta belongs exclusively to Stage5 xrd_diffraction_peak_2theta. Never convert angle into spacing.'
    if key in SPECIFIC: return SPECIFIC[key]
    # The remaining configured mechanics entries form explicit name families.
    if key.startswith('dynamic_'):
        return 'Source-reported ' + key.replace('_',' ') + '; retain test mode, frequency and temperature, not a static substitute.'
    if any(x in key for x in ('tensile','shear','flexural','compressive')):
        text = 'Source-reported ' + key.replace('_',' ') + '; preserve loading mode'
        if 'fiber_' in key: text += ' and fiber-specific scope'
        if 'at_break' in key: text += '; generic strength without rupture evidence is insufficient'
        elif 'at_yield' in key: text += '; source must identify yielding rather than rupture'
        elif 'modulus' in key: text += '; retain initial/Young/secant or other source subtype'
        elif 'creep' in key: text += '; retain time, load, temperature and rupture/recovery meaning'
        return text + '.'
    if key in ('elongation_at_break','elongation_at_yield'):
        return 'Source-reported ' + key.replace('_',' ') + '; preserve the specified break/yield endpoint and original representation.'
    raise ValueError('No operational definition for configured field: ' + key)

def definitions(catalog):
    return {t['target_id']: {'definition': definition(t), 'family': family(t),
            'basis': 'configured_name_and_scope; conservative_extraction_contract_not_standards_equivalence'}
            for t in catalog['targets']}

def detect_families(text):
    return {name for name, pattern in FAMILY_CUES.items() if re.search(pattern, text, re.I)}

def detail_relevant(target, text, found):
    """Select explanations by named quantity/loading mode, not a whole large family."""
    key=target['property_key']
    flat=re.sub(r'\\(?:mathrm|text|mathbf|operatorname)\s*','',text)
    flat=re.sub(r'[_{}$^\\]',' ',flat)
    specific={
      'glass_transition_temperature':r'glass|\bT\s*g\b',
      'melting_temperature':r'melt|\bT\s*m\b',
      'softening_temperature':r'soften|\bT\s*s\b',
      'vicat_softening_temperature':r'Vicat',
      'crystallization_temperature':r'crystalli[sz]ation|\bT\s*c\b',
      'crystallization_kinetics':r'kinetic|crystalli[sz]ation\s*(?:rate|time)|Avrami',
      'heat_of_crystallization':r'crystalli[sz]ation|enthalp|\bDSC\b',
      'heat_of_fusion':r'fusion|melt|enthalp|\bDSC\b',
      'thermal_decomposition_temperature':r'decomp|degrad|weight.?loss|mass.?loss|\bT\s*d\b|\bTGA\b',
      'thermal_decomposition_weight_loss':r'decomp|degrad|weight.?loss|mass.?loss|\bT\s*d\b|\bTGA\b',
      'lc_phase_transition_temperature':r'liquid.?cryst|mesophase|nematic|smectic',
      'specific_heat_capacity_cp':r'heat.?capacity|specific.?heat|\bC\s*p\b',
      'specific_heat_capacity_cv':r'heat.?capacity|specific.?heat|\bC\s*v\b',
      'thermal_conductivity':r'thermal\s*conduct|heat\s*conduct',
      'thermal_diffusivity':r'thermal\s*diffus',
      'linear_expansion_coefficient':r'expansion|\bCTE\b|\bTMA\b',
      'volume_expansion_coefficient':r'expansion|\bCTE\b',
      'brittleness_temperature':r'brittl',
      'deflection_temperature_under_load':r'deflection|\bHDT\b',
      'elongation_at_break':r'elongat|tensile|strain.*break',
      'elongation_at_yield':r'yield|elongat',
      'charpy_impact':r'Charpy|impact', 'izod_impact':r'Izod|impact',
      'rockwell_hardness':r'Rockwell|hardness','shore_hardness':r'Shore|hardness',
      'good_solvent':r'solub|solvent','non_solvent':r'solub|solvent',
      'poor_solvent':r'solub|solvent','solvent':r'solub|solvent',
      'intrinsic_viscosity':r'viscos|intrinsic|inherent|eta',
      'theta_solvent_theta_temperature':r'theta',
      'radius_of_gyration':r'gyration','second_virial_coefficient':r'virial',
      'sedimentation_coefficient':r'sediment','diffusion_coefficient':r'diffus',
      'water_absorption':r'water|absor', 'contact_angle':r'contact\s*angle|wettab',
      'gas_solubility_coefficient_s':r'gas|sorption',
      'gas_diffusion_coefficient_d':r'gas|diffus',
      'gas_permeability_coefficient_p':r'gas|permeab',
      'water_vapor_transmission':r'water.?vapou?r|transmission',
      'interfacial_tension':r'interfacial|tension', 'surface_tension':r'surface|tension',
      'cohesive_energy_density':r'cohesive|energy.?density',
      'hansen_parameter_delta_d':r'Hansen|solubility.?parameter',
      'hansen_parameter_delta_h':r'Hansen|solubility.?parameter',
      'hansen_parameter_delta_p':r'Hansen|solubility.?parameter',
      'solubility_parameter':r'solubility.?parameter|Hansen',
    }
    if key in specific:return bool(re.search(specific[key],flat,re.I))
    if any(word in key for word in ('tensile','shear','flexural','compressive')):
        mode = 'tensile' if 'tensile' in key else 'shear' if 'shear' in key else 'flexural' if 'flexural' in key else 'compressive'
        pattern={'tensile':r'tensile|tension|Young|elongat','shear':r'shear',
                 'flexural':r'flexur|bend','compressive':r'compress'}[mode]
        if not re.search(pattern,flat,re.I):return False
        if 'creep' in key and not re.search(r'creep',flat,re.I):return False
        if key.startswith('dynamic_') and not re.search(r'dynamic|frequency|DMA|rheolog',flat,re.I):return False
        if key.startswith('fiber_') and not re.search(r'fib[er]{2}',flat,re.I):return False
        if 'yield' in key and not re.search(r'yield',flat,re.I):return False
        return True
    return family(target) in found

def render_targets(catalog, original, text):
    allowed = {x['target_id'] for x in original}; targets = [t for t in catalog['targets'] if t['target_id'] in allowed]
    found = detect_families(text)
    index = {}
    for t in targets: index.setdefault(t['section'], []).append(t['property_key'])
    selected = [t for t in targets if detail_relevant(t,text,found) or any(
        len(a) >= 4 and re.search(r'(?<![A-Za-z])' + re.escape(a.replace('_',' ')) + r'(?![A-Za-z])', text, re.I)
        for a in t['aliases'])]
    # Unknown-topic tasks keep the whole short definition set rather than an arbitrary top-k.
    if not selected: selected = targets
    details = [{'target_id': t['target_id'], 'definition': definition(t),
                **({'subtype_required': True} if t.get('subtype_required') else {})} for t in selected]
    return {'target_index': index, 'target_fields': details}, {'allowed_count': len(targets),
            'detailed_count': len(details), 'detected_families': sorted(found),
            'index_retains_every_allowed_id': True}
