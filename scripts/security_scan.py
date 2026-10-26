"""Pinned free scanner containers; no hosted scanner accounts or paid services."""
import argparse
import hashlib
import json
import os
import tarfile
import time
import uuid
from pathlib import Path

from manage import ROOT, compose, docker, redact, run, scan
from release import fingerprint


def source_snapshot(folder, output):
    """Copy all public source, including uncommitted files, onto native scanner storage."""
    before = fingerprint()
    archive = folder/'source.tar'
    excluded = {'.git','.runtime','.venv','node_modules','.next','__pycache__','.pytest_cache','.ruff_cache'}
    files = {}
    with tarfile.open(archive,'w') as target:
        for directory, directories, names in os.walk(ROOT):
            relative_folder=Path(directory).relative_to(ROOT).as_posix()
            directories[:] = [d for d in directories if d not in excluded and
                               not d.endswith('.egg-info') and (relative_folder,d)
                               not in {('evaluation','results'),('docs','assets'),('.','data'),('.','htmlcov'),('.','test-results'),('.','playwright-report'),('frontend','test-results'),('frontend','playwright-report')}]
            if any((Path(directory)/d).is_symlink() or getattr(Path(directory)/d,'is_junction',lambda:False)() for d in directories):
                raise SystemExit('Resolve source directory symlinks before scanning')
            for name in names:
                path=Path(directory)/name
                if name.startswith('.env') and name != '.env.example':
                    continue
                if path.suffix in {'.pyc','.log','.tsbuildinfo'} or name=='.coverage':
                    continue
                if path.is_symlink() or getattr(path,'is_junction',lambda:False)():
                    raise SystemExit('Resolve source symlinks before scanning: '+str(path.relative_to(ROOT)))
                relative=path.relative_to(ROOT).as_posix()
                files[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
                target.add(path,arcname=relative,recursive=False)
    if fingerprint()!=before:
        raise SystemExit('Source changed while creating the scan snapshot; retry after edits finish')
    manifest={'source_sha256':before,'archive_sha256':hashlib.file_digest(archive.open('rb'),'sha256').hexdigest(),
              'files':files,'scope':'All source including uncommitted files; excludes secrets, Git metadata, runtime/data/backups, dependency/build caches, generated reports and screenshots.'}
    (output/'source-manifest.json').write_text(json.dumps(manifest,indent=2))
    return archive,manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dynamic', action='store_true')
    parser.add_argument('--images', action='store_true')
    parser.add_argument('--only', nargs='+', choices=['semgrep','trivy-filesystem','pip-audit','zap-baseline'])
    args = parser.parse_args()
    scan()
    images = json.loads((ROOT/'security/scanners.json').read_text(encoding='utf-8'))
    output = ROOT/'evaluation/results/security'
    output.mkdir(parents=True, exist_ok=True)
    folder=ROOT/'.runtime/scanner-input'
    folder.mkdir(parents=True,exist_ok=True)
    archive,manifest=source_snapshot(folder,output)
    mount = ['--mount', f'type=bind,source={archive},target=/input/source.tar,readonly', '--mount', f'type=bind,source={output},target=/reports']
    wrapper=['--entrypoint','/bin/sh']
    extract=['-c','mkdir -p /tmp/quarry-source && tar -xf /input/source.tar -C /tmp/quarry-source && cd /tmp/quarry-source && exec "$@"','quarry-scan']
    cache = ['--mount','type=volume,source=quarry_trivy_cache,target=/root/.cache/trivy']
    steps = [
        ('semgrep', ['run','--rm',*mount,'--env','SEMGREP_SEND_METRICS=off',*wrapper,images['semgrep'],*extract,'semgrep','scan','--config','p/owasp-top-ten','--config','p/python','--config','p/javascript','--config','p/typescript','--metrics','off','--disable-version-check','--no-git-ignore','--exclude','.git','--error','--json','--output','/reports/semgrep.json','--exclude','.env','--exclude','evaluation/results','--exclude','frontend/node_modules','--exclude','frontend/.next','--exclude','.runtime','--exclude','backend/tests','.']),
        ('trivy-filesystem', ['run','--rm',*mount,*cache,*wrapper,images['trivy'],*extract,'trivy','fs','--scanners','vuln,secret,misconfig','--severity','HIGH,CRITICAL','--exit-code','1','--format','json','--output','/reports/trivy-filesystem.json','--skip-files','.env','.']),
        ('pip-audit', ['compose','--profile','test','run','--rm','--no-deps','tests','pip-audit','--disable-pip','--no-deps','-r','/tmp/requirements.lock','--format','json','--output','/app/evaluation/results/security/pip-audit.json']),
        ('pip-audit-dev', ['compose','--profile','test','run','--rm','--no-deps','tests','pip-audit','--disable-pip','--no-deps','-r','/app/requirements-dev.lock','--format','json','--output','/app/evaluation/results/security/pip-audit-dev.json']),
        ('pip-audit-eval', ['compose','--profile','test','run','--rm','--no-deps','tests','pip-audit','--disable-pip','--no-deps','-r','/app/requirements-eval.lock','--format','json','--output','/app/evaluation/results/security/pip-audit-eval.json']),
    ]
    if args.dynamic or args.only and 'zap-baseline' in args.only:
        steps.append(('zap-baseline', []))
    if args.only:
        steps = [(name, command) for name, command in steps if name in args.only]
    report = {'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'source_sha256':fingerprint(),'images':images,'steps':[], 'source_snapshot':manifest['archive_sha256'],'source_file_count':len(manifest['files']),'scope':'Local source and optional unauthenticated loopback deployment. No model provider calls.', 'rules':'Public Semgrep community packs and Trivy databases retrieved at run time; reports preserve tool/rule metadata.'}
    for name, arguments in steps:
        print(f'Starting {name}…',flush=True)
        if name == 'zap-baseline':
            # Pull first: a long image download must not freeze an obsolete container ID.
            run([docker(),'pull',images['zap']])
            gateway = compose('ps','-q','gateway',capture=True).stdout.strip()
            if not gateway:
                raise SystemExit('Start the current gateway before dynamic scanning')
            arguments = ['run','--rm','--network',f'container:{gateway}','--mount',f'type=bind,source={output},target=/zap/wrk','--mount',f'type=bind,source={ROOT / "security"},target=/quarry-security,readonly',images['zap'],'zap-baseline.py','-c','/quarry-security/zap-baseline.conf','-t','http://localhost:3000','-J','zap.json','-r','zap.html','-m','1','-T','5']
        start = time.monotonic()
        if name.startswith('pip-audit'):
            (output/(name+'.json')).unlink(missing_ok=True)
        result = run([docker(),*arguments],capture=True,check=False)
        log = redact(result.stdout + result.stderr)
        (output/(name+'.log')).write_text(log,encoding='utf-8')
        step={'name':name,'exit_code':result.returncode,'seconds':round(time.monotonic()-start,2),'log_sha256':hashlib.sha256(log.encode()).hexdigest(),'gate_passed':result.returncode==0}
        if name=='pip-audit-eval' and result.returncode==1 and (output/'pip-audit-eval.json').exists():
            audit=json.loads((output/'pip-audit-eval.json').read_text(encoding='utf-8'))
            found={(package['name'],package['version'],finding['id']) for package in audit.get('dependencies',[]) for finding in package.get('vulns',[])}
            expected={('diskcache','5.6.3','PYSEC-2026-2447'),('ragas','0.4.3','PYSEC-2026-3046')}
            if found==expected:
                compose('--profile','evaluation','build','evaluate')
                check=compose('--profile','evaluation','run','--rm','--no-deps','evaluate','python','-m','quarry.eval_guard',capture=True,check=False)
                if check.returncode==0:
                    evidence=json.loads(check.stdout.strip().splitlines()[-1])
                    (output/'eval-mitigations.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
                    step['gate_passed']=evidence.get('status')=='passed' and set(evidence.get('advisories',[]))=={'CVE-2026-6587','CVE-2025-69872'}
                    step['disposition']='Locally patched optional components; vulnerable capabilities removed and exploit-negative checks passed. Raw package findings remain present. See security/EVALUATOR_MITIGATIONS.md.'
        report['steps'].append(step)
        print(f'{name}: exit {result.returncode}\n{log[-2200:]}',flush=True)
    if args.images:
        folder = ROOT/'.runtime/scanner-input'
        folder.mkdir(parents=True,exist_ok=True)
        for name in ['backend','web','objectstore','gateway','postgres','qdrant','searxng','mailpit']:
            archive = folder/(name+'.tar')
            image = f'quarry-{name}:local'
            scanner_name='quarry-image-audit-'+uuid.uuid4().hex
            temporary=output/('.image-'+name+'-'+uuid.uuid4().hex+'.json')
            print(f'Scanning built image {image}…',flush=True)
            run([docker(),'image','save','--output',str(archive),image])
            try:
                # Write on native container storage. Direct overwrite of a Windows
                # bind-mounted report can fail with EINVAL despite a completed scan.
                command = [docker(),'run','--name',scanner_name,*cache,'--mount',f'type=bind,source={folder},target=/images,readonly',images['trivy'],'image','--input',f'/images/{name}.tar','--scanners','vuln','--severity','HIGH,CRITICAL','--exit-code','1','--format','json','--output','/tmp/quarry-image.json']
                result = run(command,capture=True,check=False)
                copied=run([docker(),'cp',scanner_name+':/tmp/quarry-image.json',str(temporary)],capture=True,check=False)
                if copied.returncode==0:
                    temporary.replace(output/f'image-{name}.json')
                (output/f'image-{name}.log').write_text(redact(result.stdout+result.stderr+copied.stderr),encoding='utf-8')
                report['steps'].append({'name':f'image-{name}','exit_code':result.returncode,'image':image,'report_copied':copied.returncode==0,'gate_passed':result.returncode==0 and copied.returncode==0})
                print(f'Image {name}: exit {result.returncode}',flush=True)
            finally:
                run([docker(),'rm','--force',scanner_name],capture=True,check=False)
                temporary.unlink(missing_ok=True)
                archive.unlink(missing_ok=True)
    report['status'] = 'passed' if all(s['gate_passed'] for s in report['steps']) else 'findings_or_error'
    report['known_optional_package_findings_present']=any('disposition' in step for step in report['steps'])
    target='summary.json' if not args.only and args.images and args.dynamic else 'selected-summary.json'
    (output/target).write_text(json.dumps(report,indent=2),encoding='utf-8')
    raise SystemExit(0 if report['status']=='passed' else 1)


if __name__=='__main__':
    main()
