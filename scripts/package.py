#!/usr/bin/env python3
"""Freeze source and a separate hash manifest, without runtime/dependency caches."""
from pathlib import Path
import hashlib,json,zipfile
root=Path(__file__).resolve().parents[1]
out=root.parent/'track-fold-output';out.mkdir(exist_ok=True)
skip={'node_modules','test-results','__pycache__','.git','.venv'}
files=sorted(p for p in root.rglob('*') if p.is_file() and not any(x in skip for x in p.relative_to(root).parts))
archive=out/'track-fold-source.zip'
records=[]
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for p in files:
  rel=p.relative_to(root).as_posix();data=p.read_bytes();info=zipfile.ZipInfo('track-fold/'+rel,(2026,10,4,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,data);records.append({'path':rel,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 for r in records:assert hashlib.sha256(z.read('track-fold/'+r['path'])).hexdigest()==r['sha256']
manifest={'archive':archive.name,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':records,'file_count':len(records),'verification':'Frozen source-stage review; hosted browser/native/print gates remain pending'}
(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:v for k,v in manifest.items() if k!='files'},indent=2))
