"""Read source-bound local structure interpretations; never replace source records."""
from pathlib import Path
from copy import deepcopy
import json,hashlib,base64,io
CONTRACT='source-bound-structure-interpretation/1.0'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def draw_identity(smiles):
    """Natural-size depiction of encoded graphs; no inferred bonds or stereo.

    Atom maps remain in the saved SMILES. Asterisks denote dummy attachment
    atoms in this display, keeping them distinct from a source's R variables.
    """
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    from PIL import Image, ImageOps
    mol=Chem.MolFromSmiles(smiles)
    if mol is None or not 0 < mol.GetNumAtoms() <= 350:raise ValueError('INVALID_INTERPRETATION_GRAPH')
    drawer=rdMolDraw2D.MolDraw2DCairo(-1,-1)
    options=drawer.drawOptions();options.fixedBondLength=36;options.fixedFontSize=20
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
        if atom.GetAtomicNum()==0:options.atomLabels[atom.GetIdx()]='*'
    rdMolDraw2D.PrepareAndDrawMolecule(drawer,mol);drawer.FinishDrawing()
    picture=ImageOps.expand(Image.open(io.BytesIO(drawer.GetDrawingText())).convert('RGB'),border=20,fill='white')
    data=io.BytesIO();picture.save(data,format='PNG')
    return {'image':'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode(),
            'image_width':picture.width,'image_height':picture.height,
            'image_caption':'图示结构候选；星号为开放连接端口，原子映射保留在模型记录中。'}


def draw(smiles,labels=None):
    from rdkit import Chem
    from rdkit.Chem import Draw
    mol=Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms()>350:raise ValueError('INVALID_INTERPRETATION_GRAPH')
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum()==0 and labels:
            value=labels.get(str(atom.GetAtomMapNum()))
            if value:atom.SetProp('atomLabel',str(value)[:48])
    image=Draw.MolToImage(mol,size=(1050,340))
    from PIL import Image,ImageChops,ImageOps
    bounds=ImageChops.difference(image.convert('RGB'),Image.new('RGB',image.size,'white')).getbbox()
    if bounds:image=ImageOps.expand(image.crop(bounds),border=18,fill='white')
    data=io.BytesIO();image.save(data,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()


def read(root,view,owner):
    folder=Path(root)/'runs/structure-interpretations'/view['job_id']
    result={'models':[],'name_scopes':[],'parsed_fields':[],'unavailable':[],
        'source_records_modified':False,'model_calls':0,'network_calls':0}
    if not folder.exists():return result
    record=view['definitions'][owner]
    for path in sorted(folder.glob('IR-*.json')):
        try:
            envelope=json.loads(path.read_text(encoding='utf8'));value=envelope['value']
            if value.get('owner_ref')!=owner:continue
            if envelope['sha256']!=digest(value):raise ValueError('INTERPRETATION_HASH_MISMATCH')
            if value.get('contract')!=CONTRACT:raise ValueError('INTERPRETATION_CONTRACT_UNKNOWN')
            if value.get('source_sha256')!=view['source_sha256'] or value.get('record_sha256')!=digest(record):
                raise ValueError('SOURCE_IDENTITY_CHANGED')
            index=view.get('source_index',{}).get('items',{})
            for item in value.get('models',[]):
                if not item.get('src') or any(s not in index for s in item['src']):raise ValueError('MODEL_SOURCE_UNRESOLVED')
                if item.get('scope') not in ('repeating_subunit','chain_end_fragment','finite_molecule'):raise ValueError('UNSUPPORTED_MODEL_SCOPE')
                row=deepcopy(item);row['image_data_url']=draw(row['smiles'],row.get('port_labels'))
                row['independent_review']='NOT_REVIEWED';row['source_fact']=False
                row['interpretation_id']=value['id'];row['whole_material_identity']=False
                result['models'].append(row)
            for name in deepcopy(value.get('name_scopes',[])):
                model=next((m for m in value.get('models',[]) if m.get('id')==name.get('model_ref')),None)
                if model and not name.get('scope'):name['scope']=model['scope']
                result['name_scopes'].append(name)
            result['parsed_fields'].extend(deepcopy(value.get('parsed_fields',[])))
            for pending in value.get('unresolved',[]):
                result['unavailable'].append({'file':path.name,**deepcopy(pending)})
            if value.get('tool_evidence'):
                saved=result.setdefault('tool_evidence',{'queries':[],'profiles':[]})
                for key in ('queries','profiles'):saved[key].extend(deepcopy(value['tool_evidence'].get(key,[])))
        except (OSError,ValueError,TypeError,KeyError) as error:
            result['unavailable'].append({'file':path.name,'reason':str(error)})
    return result
