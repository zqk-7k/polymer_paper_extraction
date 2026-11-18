"""Join supplied residue graphs at explicit dummy ports; never predict reactions."""
from copy import deepcopy

try:
    from rdkit import Chem
except ImportError:
    Chem = None

CONTRACT = "supplied-fragment-assembly/1.0"
MOTIFS = (("ester", 6, 8), ("amide", 6, 7), ("si_o_linkage", 14, 8))


class _Rejected(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise _Rejected(reason)


def _source(value):
    return (isinstance(value, list) and bool(value)
            and all(isinstance(s, str) and bool(s.strip()) for s in value)
            and len(set(value)) == len(value))


def _identity(atom):
    return atom.GetAtomicNum(), atom.GetIsotope(), atom.GetFormalCharge()


def _linkage(mol, u, v):
    for name, first, second in MOTIFS:
        for x, y in ((u, v), (v, u)):
            a, b = mol.GetAtomWithIdx(x), mol.GetAtomWithIdx(y)
            if (a.GetAtomicNum(), b.GetAtomicNum()) != (first, second):
                continue
            if first == 6 and any(
                bond.GetBondType() == Chem.BondType.DOUBLE
                and bond.GetOtherAtom(a).GetAtomicNum() == 8 for bond in a.GetBonds()
            ):
                return name
            if first == 14:
                onward_si = any(
                    bond.GetOtherAtom(b).GetIdx() != x
                    and bond.GetOtherAtom(b).GetAtomicNum() == 14
                    and bond.GetBondType() == Chem.BondType.SINGLE for bond in b.GetBonds()
                )
                return "siloxane" if onward_si else name
    return "explicit_single_bond"


def assemble(fragments, links) -> dict:
    """Return a candidate or a local rejection, retaining all supplied evidence.

    Atom indices are zero based, including explicit H atoms (removeHs=False).
    Correspondence covers every input atom; consumed dummies have null outputs.
    Output indices refer to product_smiles parsed with removeHs=False. Output
    maps are unique generated labels, not the caller's original map identities.
    """
    result = {
        "contract": CONTRACT, "status": "UNDETERMINED",
        "fragments": deepcopy(fragments), "links": deepcopy(links), "src": [],
        "source_fact": False, "used_for_identity": False,
        "automatic_update": False, "full_iupac_conformance": False,
        "atom_correspondence": [], "consumed_ports": [], "remaining_ports": [],
        "recognized_linkages": [],
        "assumptions": ["Supplied fragments are residue graphs, not reactants.",
                        "Only explicitly linked dummy atoms are deleted; only single bonds are added."],
        "limitations": ["No reaction prediction, naming, identity decision, or inferred closure.",
                        "Explicit atom/bond stereochemistry is unsupported; chirality preservation is not claimed.",
                        "Linkage classes describe endpoint motifs only, not a whole polymer.",
                        "Disconnected supplied components are retained; output maps are generated labels.",
                        "Hydrogens follow RDKit valence rules; no solvent, reagent, or leaving group is inferred."],
    }
    for items in (fragments, links):
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("src"), list):
                    for source in item["src"]:
                        if isinstance(source, str) and source not in result["src"]:
                            result["src"].append(source)
    if Chem is None:
        result.update(status="TOOL_UNAVAILABLE", error="RDKIT_UNAVAILABLE")
        return result
    try:
        _require(isinstance(fragments, list) and 2 <= len(fragments) <= 12, "FRAGMENT_COUNT")
        _require(isinstance(links, list) and bool(links), "LINKS_REQUIRED")
        params = Chem.SmilesParserParams()
        params.removeHs = False
        params.sanitize = False
        params.parseName = False
        params.allowCXSMILES = False
        mols, origins, ports, ids = [], [], {}, set()
        for fragment in fragments:
            _require(isinstance(fragment, dict), "INVALID_FRAGMENT")
            fid, smiles = fragment.get("id"), fragment.get("smiles")
            _require(isinstance(fid, str) and bool(fid.strip()) and fid not in ids, "INVALID_FRAGMENT_ID")
            ids.add(fid)
            _require(_source(fragment.get("src")), "FRAGMENT_SOURCE_REQUIRED")
            _require(isinstance(smiles, str) and 0 < len(smiles) <= 4000, "SMILES_SIZE")
            _require(not any(marker in smiles for marker in ("@", "/", "\\")), "UNSUPPORTED_STEREO")
            mol = Chem.MolFromSmiles(smiles, params)
            _require(mol is not None, "INVALID_SMILES")
            _require(0 < mol.GetNumAtoms() <= 400, "ATOM_COUNT")
            _require(not any(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms())
                     and not any(b.GetStereo() != Chem.BondStereo.STEREONONE
                                 or b.GetBondDir() != Chem.BondDir.NONE for b in mol.GetBonds()),
                     "UNSUPPORTED_STEREO")
            identities = [_identity(a) for a in mol.GetAtoms()]
            Chem.SanitizeMol(mol)
            _require(identities == [_identity(a) for a in mol.GetAtoms()], "SANITIZATION_CHANGED_ATOMS")
            offset, maps = len(origins), set()
            for atom in mol.GetAtoms():
                index, amap = atom.GetIdx(), atom.GetAtomMapNum()
                _require(amap == 0 or amap not in maps, "DUPLICATE_ATOM_MAP")
                maps.add(amap)
                origin = {"fragment": fid, "atom_index": index, "original_atom_map": amap,
                          "atomic_number": atom.GetAtomicNum(), "isotope": atom.GetIsotope(),
                          "formal_charge": atom.GetFormalCharge()}
                origins.append(origin)
                if atom.GetAtomicNum() == 0:
                    _require(amap > 0 and atom.GetDegree() == 1
                             and atom.GetBonds()[0].GetBondType() == Chem.BondType.SINGLE,
                             "INVALID_PORT")
                    neighbor = atom.GetNeighbors()[0]
                    _require(neighbor.GetAtomicNum() != 0, "DUMMY_NEIGHBOR_UNSUPPORTED")
                    ports[(fid, amap)] = (offset + index, offset + neighbor.GetIdx())
            mols.append(mol)
        selected, used, bond_pairs = [], set(), set()
        for link_index, link in enumerate(links):
            _require(isinstance(link, dict) and link.get("bond") == "single", "INVALID_LINK_BOND")
            _require(_source(link.get("src")), "LINK_SOURCE_REQUIRED")
            endpoints = []
            for side in ("left", "right"):
                endpoint = link.get(side)
                _require(isinstance(endpoint, dict), "INVALID_ENDPOINT")
                fid, port = endpoint.get("fragment"), endpoint.get("port")
                _require(isinstance(fid, str) and type(port) is int and port > 0, "INVALID_ENDPOINT")
                key = (fid, port)
                _require(key in ports, "PORT_NOT_FOUND")
                _require(key not in used, "PORT_REUSED")
                used.add(key)
                endpoints.append(key)
            _require(endpoints[0][0] != endpoints[1][0], "INTRAFRAGMENT_LINK_UNSUPPORTED")
            pair = tuple(sorted(ports[key][1] for key in endpoints))
            _require(pair not in bond_pairs, "DUPLICATE_NEIGHBOR_BOND")
            bond_pairs.add(pair)
            selected.append((link_index, endpoints, pair))
        combined = mols[0]
        for mol in mols[1:]:
            combined = Chem.CombineMols(combined, mol)
        rw = Chem.RWMol(combined)
        for atom in rw.GetAtoms():
            atom.SetAtomMapNum(atom.GetIdx() + 1)
        removed = {ports[key][0] for key in used}
        for _, _, (u, v) in selected:
            _require(rw.GetBondBetweenAtoms(u, v) is None, "EXISTING_NEIGHBOR_BOND")
            rw.AddBond(u, v, Chem.BondType.SINGLE)
        for index in sorted(removed, reverse=True):
            rw.RemoveAtom(index)
        product = rw.GetMol()
        Chem.SanitizeMol(product)
        product_smiles = Chem.MolToSmiles(product, canonical=True, isomericSmiles=True)
        output = Chem.MolFromSmiles(product_smiles, params)
        _require(output is not None, "OUTPUT_PARSE_FAILED")
        Chem.SanitizeMol(output)
        by_map = {a.GetAtomMapNum(): a for a in output.GetAtoms()}
        _require(len(by_map) == output.GetNumAtoms()
                 and set(by_map) == {i + 1 for i in range(len(origins)) if i not in removed},
                 "ATOM_CONSERVATION_FAILED")
        correspondence = []
        for index, origin in enumerate(origins):
            atom = by_map.get(index + 1)
            if atom is not None:
                _require(_identity(atom) == (origin["atomic_number"], origin["isotope"], origin["formal_charge"]),
                         "ATOM_CONSERVATION_FAILED")
            correspondence.append({**origin, "output_atom_index": atom.GetIdx() if atom is not None else None,
                                   "output_atom_map": atom.GetAtomMapNum() if atom is not None else None})
        consumed, remaining, recognized = [], [], []
        for key, (index, neighbor) in ports.items():
            record = {**correspondence[index], "port": key[1],
                      "neighbor_atom_index": origins[neighbor]["atom_index"]}
            (consumed if key in used else remaining).append(record)
        for link_index, endpoints, (u, v) in selected:
            x, y = by_map[u + 1].GetIdx(), by_map[v + 1].GetIdx()
            recognized.append({"link_index": link_index, "class": _linkage(output, x, y),
                               "output_atom_indices": [x, y], "src": deepcopy(links[link_index]["src"]),
                               "basis": "endpoint_local_motif", "source_fact": False})
        result.update(status="ASSEMBLED_CANDIDATE", product_smiles=product_smiles,
                      atom_correspondence=correspondence, consumed_ports=consumed,
                      remaining_ports=remaining, recognized_linkages=recognized)
    except _Rejected as exc:
        result["error"] = str(exc)
    except (ValueError, RuntimeError, OverflowError) as exc:
        result.update(error="RDKIT_VALIDATION_FAILED", detail=str(exc))
    return result
