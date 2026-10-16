"""Build an allowlisted source archive while preserving the recorded license status."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

APP=Path(__file__).resolve().parents[1]
ROOT_FILES=['.gitignore','README.md','README.zh-CN.md','CONTRIBUTING.md','CONTRIBUTORS.md',
    'SECURITY.md','LICENSE_STATUS.md','THIRD_PARTY_NOTICES.md','start.sh','pytest.ini',
    'requirements.txt','requirements-dev.txt','requirements-warp.txt',
    'docs/TASKFLOW.md','docs/SOURCE_PACKAGE.md',
    'scripts/__init__.py','scripts/build_source_candidate.py','scripts/build_preview_meshes.py',
    'scripts/create_demo.py','scripts/evaluate_taskflow.py','scripts/install_models.py','scripts/verify_models.py']
PATTERNS=['*.py','tests/test_*.py','tests/*.test.mjs','tests/warp_fixtures.py',
    'static/*.js','static/*.mjs','static/*.svg','static/index.html','static/*.css','static/licenses/*.txt',
    'static/viewer/*.js','static/viewer/*.mjs','static/viewer/*.html','static/viewer/*.css',
    'static/viewer/g1-preview.json','static/viewer/vendor/*.js',
    'robot/*.urdf','robot/SOURCE.json','robot/meshes/*.STL',
    'warp_progress/*.py','taskflow/*.py','curation/*.py',
    'vendor/*.py','vendor/warp_rm/*.py','vendor/warp_rm/LICENSE','vendor/warp_rm/provenance.json',
    'docs/licensing/*.json','.github/workflows/*.yml','models/*.json']
EXCLUDED={'static/holocurate.css','static/shell.css','static/studio.css','static/ui-system.css',
    'static/workflow.css','static/task-audit.js','static/task-audit.css'}
FORBIDDEN_SUFFIXES={'.mcap','.npz','.pt','.pth','.safetensors','.sqlite','.sqlite3','.zip','.pyc','.key','.pem'}
SECRET_PATTERNS=[rb'hf_[A-Za-z0-9]{25,}',rb'gh[pousr]_[A-Za-z0-9]{30,}',
    rb'github_pat_[A-Za-z0-9_]{30,}',rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----']


def selected_files():
    files={APP/name for name in ROOT_FILES}
    for pattern in PATTERNS:files.update(APP.glob(pattern))
    for path in sorted(files):
        relative=path.relative_to(APP)
        if relative.as_posix() in EXCLUDED:continue
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(APP):
            raise ValueError(f'Not an ordinary source file: {relative}')
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or any(part in ('.git','.venv','workspace','__pycache__') for part in relative.parts):
            raise ValueError(f'Runtime/private file selected: {relative}')
        raw=path.read_bytes()
        if any(re.search(pattern,raw) for pattern in SECRET_PATTERNS):
            raise ValueError(f'Credential-shaped value found; inspect locally: {relative}')
        yield path,relative,raw


def build(output,label):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',label):raise ValueError('Use a simple release label without path separators')
    status=dict(publication_ready=False,open_source_license_ready=False,release=label,github_target='Lee-hz/RoboCurate')
    rows=list(selected_files())
    folder=output.resolve()/f'RoboCurate-{label}-source'
    folder.mkdir(parents=True,exist_ok=False)
    source=folder/'RoboCurate';source.mkdir()
    manifest=dict(project='RoboCurate',publication_ready=bool(status['publication_ready']),
        open_source_license_ready=bool(status.get('open_source_license_ready',False)),
        release=status['release'],github_target=status.get('github_target'),source_only=True,
        generated_at=datetime.now(timezone.utc).isoformat(),files=[])
    for path,relative,raw in rows:
        target=source/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        manifest['files'].append(dict(path=relative.as_posix(),size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    (source/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    archive=folder.with_name(folder.name+'.zip')
    if archive.exists():raise FileExistsError(archive)
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as package:
        for row in manifest['files']:package.write(source/row['path'],'RoboCurate/'+row['path'])
        package.write(source/'SOURCE_MANIFEST.json','RoboCurate/SOURCE_MANIFEST.json')
    with zipfile.ZipFile(archive) as package:
        if package.testzip():raise ValueError('ZIP CRC verification failed')
        for row in manifest['files']:
            if hashlib.sha256(package.read('RoboCurate/'+row['path'])).hexdigest()!=row['sha256']:
                raise ValueError('Packaged source hash mismatch')
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n')
    result=dict(source=str(source),archive=str(archive),files=len(manifest['files']),bytes=archive.stat().st_size,
        sha256=digest,publication_ready=bool(status['publication_ready']),
        open_source_license_ready=bool(status.get('open_source_license_ready',False)),
        crc_verified=True,all_file_hashes_verified=True)
    archive.with_suffix('.verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=APP/'dist')
    parser.add_argument('--label',default=datetime.now().strftime('%Y%m%d-%H%M%S'))
    args=parser.parse_args();build(args.output,args.label)
