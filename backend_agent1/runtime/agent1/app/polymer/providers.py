"""Optional real local OPSIN API adapter. No network or implicit downloads.
Source is compiled against a supplied core-with-dependencies JAR. Missing tools
are not cached as unsupported chemical names. WARNING is not a verified binding.
"""
from __future__ import annotations
import base64,os,shutil,subprocess,re
from pathlib import Path
from .common import ROOT,sha_file,fail
from .chemistry import canonicalize

class OpsinProvider:
    PINNED_VERSION = '2.9.0'
    PINNED_SHA256 = '627ee5da4af551f9c4d1d766f545eb7cf519a344776e0bb677247a47abac0252'
    def __init__(self,jar=None):
        raw=jar or os.environ.get('OPSIN_JAR')
        self.jar=Path(raw).resolve() if raw else None
        # Paper sessions can read the frozen application but only write their
        # own workspace. The runner supplies a job-local compiler destination.
        build=os.environ.get('OPSIN_BUILD_DIR')
        self.cache={};self.build=Path(build).resolve() if build else ROOT/'third_party'/'build'
    def probe(self):
        missing=[]
        if not self.jar or not self.jar.is_file():missing.append('OPSIN_JAR')
        if not shutil.which('java'):missing.append('java')
        if not shutil.which('javac'):missing.append('javac')
        return {'available':not missing,'missing':missing,'opsin_version':self.PINNED_VERSION,
                'expected_jar_sha256':self.PINNED_SHA256,
                'jar_sha256':sha_file(self.jar) if self.jar and self.jar.is_file() else None,
                'mode':'LOCAL_JAVA_API','network_requests':0,'chemical_accuracy':None,
                'bridge_source_sha256':sha_file(ROOT/'third_party/OpsinBridge.java'),
                'runtime':{'java':shutil.which('java'),'javac':shutil.which('javac')}}
    def _compile(self):
        if sha_file(self.jar) != self.PINNED_SHA256:
            raise RuntimeError("OPSIN_JAR_HASH_MISMATCH")
        self.build.mkdir(parents=True,exist_ok=True)
        src=ROOT/'third_party/OpsinBridge.java';stamp=self.build/'bridge.version'
        version=sha_file(src)+'|'+sha_file(self.jar)
        if stamp.exists() and stamp.read_text()==version and (self.build/'OpsinBridge.class').exists():return
        p=subprocess.run(['javac','-encoding','UTF-8','-cp',str(self.jar),'-d',str(self.build),str(src)],text=True,capture_output=True,timeout=60,shell=False)
        if p.returncode:raise RuntimeError('OPSIN_BRIDGE_COMPILE_FAILED: '+p.stderr[:1500])
        stamp.write_text(version)
    def parse_many(self,names,timeout=180,allow_radicals=False,radical_scope='monovalent'):
        if radical_scope not in ('monovalent','divalent'):raise ValueError('EXPLICIT_RADICAL_SCOPE_REQUIRED')
        if not isinstance(names,list) or not all(isinstance(x,str) and 0<len(x)<=5000 for x in names):raise ValueError('INVALID_OPSIN_BATCH')
        if len(names)>20000:raise ValueError('OPSIN_BATCH_LIMIT')
        probe=self.probe()
        if not probe['available']:return [fail('PARSER_UNAVAILABLE','NEEDS_DETAILS',provider=probe) for _ in names]
        try:
            self._compile()
            text=''.join(base64.b64encode(n.encode()).decode()+'\n' for n in names)
            command=['java','-Xmx768m','-cp',str(self.build)+os.pathsep+str(self.jar),'OpsinBridge']
            if allow_radicals:command.append('--allow-radicals')
            p=subprocess.run(command,input=text,text=True,encoding='utf-8',capture_output=True,timeout=timeout,shell=False)
            if p.returncode:raise RuntimeError('OPSIN_PROCESS_FAILED: '+p.stderr[:500])
            lines=p.stdout.splitlines()
            if len(lines)!=len(names):raise RuntimeError('OPSIN_RESPONSE_COUNT_MISMATCH')
            out=[]
            for name,line in zip(names,lines):
                fields=line.split('\t')
                if len(fields)!=3:raise ValueError('OPSIN_PROTOCOL_ERROR')
                status,sm,ms=fields;smiles=base64.b64decode(sm,validate=True).decode();message=base64.b64decode(ms,validate=True).decode()
                if status=='SUCCESS' and smiles:
                    g=canonicalize(smiles)
                    if allow_radicals:
                        from rdkit import Chem
                        params=Chem.SmilesParserParams();params.removeHs=False;params.parseName=False
                        mol=Chem.MolFromSmiles(smiles,params)
                        if radical_scope=='monovalent' and mol and len(Chem.GetMolFrags(mol))==1 and sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms())==1:
                            g={'status':'PARSED','isomeric_smiles':Chem.MolToSmiles(mol,isomericSmiles=True),
                               'scope':'monovalent_substituent_radical_not_finite_molecule'}
                        elif radical_scope=='divalent' and mol and len(Chem.GetMolFrags(mol))==1 and sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms())==2 and len([a for a in mol.GetAtoms() if a.GetNumRadicalElectrons()==1])==2:
                            edit=Chem.RWMol(mol)
                            sites=[a.GetIdx() for a in mol.GetAtoms() if a.GetNumRadicalElectrons()==1]
                            used={a.GetAtomMapNum() for a in mol.GetAtoms() if a.GetAtomMapNum()};label=max(used or {0})+1
                            for i,index in enumerate(sites):
                                edit.GetAtomWithIdx(index).SetNumRadicalElectrons(0)
                                dummy=Chem.Atom(0);dummy.SetAtomMapNum(label+i)
                                edit.AddBond(index,edit.AddAtom(dummy),Chem.BondType.SINGLE)
                            unit=edit.GetMol();Chem.SanitizeMol(unit)
                            g={'status':'PARSED','unit_smiles':Chem.MolToSmiles(unit,isomericSmiles=True),
                               'scope':'divalent_unit_candidate_not_finite_molecule','radical_sites':sites}
                        else:g=fail('DIVALENT_UNIT_RADICAL_REQUIRED' if radical_scope=='divalent' else 'MONOVALENT_SUBSTITUENT_RADICAL_REQUIRED','INVALID')
                    # Keep parser outcome separate from graph validity.  OPSIN's
                    # SUCCESS does not establish a polymerization fact or review.
                    stereo_encoded=bool(re.search(r'[@/\\]',smiles))
                    stereo_requested=bool(re.search(r'(?i)\b(?:R|S|E|Z|cis|trans|racemic|stereo)\b',name))
                    stereo_state='explicit_encoded' if stereo_encoded else ('unspecified' if not stereo_requested else 'requested_not_encoded')
                    r={**g,'candidate_smiles':smiles,'binding_status':'EXTERNAL_PARSER_CANDIDATE','candidate_class':'FINITE_SOURCE_MOLECULE','source':{'type':'OPSIN','jar_sha256':probe['jar_sha256'],'bridge_source_sha256':probe['bridge_source_sha256']},'parser_message':message,'parser_status':status,'stereo_state':stereo_state}
                    if stereo_requested and not stereo_encoded:
                        r={**fail('OPSIN_STEREO_NOT_ENCODED','AMBIGUOUS',candidate_smiles=smiles,parser_message='stereochemical term present but output has no stereo encoding'),**{'source':r['source'],'stereo_state':stereo_state,'parser_status':status}}
                elif status=='WARNING':
                    r=fail('OPSIN_WARNING_REQUIRES_REVIEW','AMBIGUOUS',candidate_smiles=smiles,parser_message=message,
                           parser_status=status,candidate_class='FINITE_SOURCE_MOLECULE',
                           source={'type':'OPSIN','jar_sha256':probe['jar_sha256'],'bridge_source_sha256':probe['bridge_source_sha256']})
                elif status=='FAILURE':
                    r=fail('OPSIN_NAME_UNSUPPORTED',parser_message=message,parser_status=status,
                           source={'type':'OPSIN','jar_sha256':probe['jar_sha256'],'bridge_source_sha256':probe['bridge_source_sha256']})
                else:r=fail('PARSER_PROCESS_OR_PROTOCOL_ERROR','NEEDS_DETAILS',parser_message=message)
                if allow_radicals:
                    r['parser_scope']='explicit_divalent_unit/1.0' if radical_scope=='divalent' else 'explicit_substituent_radical/1.0'
                    r['candidate_class']='DIVALENT_UNIT_CANDIDATE' if radical_scope=='divalent' else 'SUBSTITUENT_RADICAL'
                if status in ('SUCCESS','FAILURE','WARNING'):self.cache[(('divalent' if radical_scope=='divalent' else 'substituent'),name) if allow_radicals else name]=r
                out.append(r)
            return out
        except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
            return [fail('PARSER_UNAVAILABLE_OR_PROTOCOL_ERROR','NEEDS_DETAILS',detail=str(exc)) for _ in names]
    def resolve(self,name):
        if name in self.cache:return self.cache[name]
        return self.parse_many([name])[0]
    def resolve_substituent(self,name):
        if ('substituent',name) in self.cache:return self.cache[('substituent',name)]
        return self.parse_many([name],allow_radicals=True)[0]
    def resolve_divalent_unit(self,name):
        """Explicit two radical sites only. Default/monovalent modes stay unchanged."""
        if ('divalent',name) in self.cache:return self.cache[('divalent',name)]
        return self.parse_many([name],allow_radicals=True,radical_scope='divalent')[0]
