"""Remove unused vulnerable evaluator capabilities; preserve versions and raw audit findings."""
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('/usr/local/lib/python3.12/site-packages')
notice = '# Quarry security modification: unsafe optional capabilities disabled; see /usr/local/share/quarry/eval-hardening.json.\n'
record = {'policy':'text-only-no-pickle-v1','advisories':['CVE-2026-6587','CVE-2025-69872'],'files':[]}


def original(relative, expected):
    path = ROOT/relative
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError('Pinned evaluator source changed; review the patch before building')
    return path,data.decode()


def save(path, source, before):
    path.write_text(notice+source)
    record['files'].append({'path':str(path),'original_sha256':hashlib.sha256(before.encode()).hexdigest(),'patched_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})


path,source = original('ragas/metrics/collections/multi_modal_faithfulness/util.py','99808618a8574f0a1d666b4f20e7549b570ea7ac203aab448bfeb87596428fbe')
before = source
names = {'process_image_to_base64','_try_process_url','_try_process_local_file'}
functions = [node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name in names]
if len(functions)!=3:
    raise RuntimeError('Expected multimodal entry points were not found')
lines=source.splitlines(keepends=True)
for function in sorted(functions,key=lambda value:value.lineno,reverse=True):
    lines[function.body[0].lineno-1:function.end_lineno]=['    raise ValueError("Multimodal URL and file access is disabled in Quarry text-only evaluation")\n']
save(path,''.join(lines),before)

path,source=original('diskcache/core.py','a229e61e76025ef476417551681a2a3dff2233bf4ce6901e8b16a395a27d4cdb')
before=source
if 'pickle.Unpickler' in source:
    raise RuntimeError('Unexpected pickle deserializer requires review')
source,count=re.subn(r'\bpickle\.(?:load|loads)\s*\(','_quarry_disabled_pickle_read(',source)
if count!=3:
    raise RuntimeError('Unexpected cache deserializer count requires review')
source+='\n\ndef _quarry_disabled_pickle_read(*args, **kwargs):\n    raise ValueError("Pickle cache deserialization is disabled in Quarry evaluation")\n'
save(path,source,before)
destination=Path('/usr/local/share/quarry')
destination.mkdir(parents=True,exist_ok=True)
(destination/'eval-hardening.json').write_text(json.dumps(record,indent=2))
