"""Quiesced local backup and restoration rehearsal; all payloads remain ignored locally."""
import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import manage

ROOT=manage.ROOT


def binary(args,*,source=None,target=None):
    with (open(source,'rb') if source else open(__import__('os').devnull,'rb')) as incoming:
        if target:
            with open(target,'wb') as outgoing:
                subprocess.run([manage.docker(),'compose',*args],cwd=ROOT,stdin=incoming,stdout=outgoing,check=True)
        else:
            subprocess.run([manage.docker(),'compose',*args],cwd=ROOT,stdin=incoming,check=True)


def backup(*,source_endpoint=None,restart=True):
    folder=ROOT/'.runtime/backups'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    folder.mkdir(parents=True,mode=0o700)
    manage.compose('stop','api','worker')
    try:
        binary(['exec','-T','postgres','pg_dump','-U','quarry','-Fc','--no-owner','--no-privileges','quarry'],target=folder/'database.dump')
        override=['-e','QUARRY_S3_ENDPOINT='+source_endpoint] if source_endpoint else []
        binary(['run','--rm','--no-deps',*override,'api','python','-m','quarry.admin','export-objects'],target=folder/'objects.zip')
    finally:
        if restart:
            manage.compose('start','api','worker')
    manifest={'created_at':time.time(),'method':'Quiesced API and workers; PostgreSQL custom dump and hashed private source objects',
              'sha256':{name:hashlib.file_digest((folder/name).open('rb'),'sha256').hexdigest() for name in ['database.dump','objects.zip']}}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Backup saved under ignored .runtime/backups/'+folder.name)
    return folder


def rehearse(folder):
    project=['--project-name','quarry-restore','-f','compose.yaml','-f','infra/restore.compose.yaml']
    manifest=json.loads((folder/'manifest.json').read_text())
    for name,expected in manifest['sha256'].items():
        if hashlib.file_digest((folder/name).open('rb'),'sha256').hexdigest()!=expected:
            raise SystemExit('Backup file checksum mismatch')
    started=time.monotonic()
    manage.compose(*project,'up','--detach','--wait','--wait-timeout','900')
    manage.compose(*project,'stop','api','worker')
    try:
        binary([*project,'exec','-T','postgres','pg_restore','-U','quarry','-d','quarry','--clean','--if-exists','--no-owner','--no-privileges'],source=folder/'database.dump')
        # pg_restore drops table grants; initialization restores least-privilege DML grants.
        manage.compose(*project,'run','--rm','--no-deps','initialize')
        binary([*project,'run','--rm','--no-deps','api','python','-m','quarry.admin','restore-objects','--acknowledge-isolated'],source=folder/'objects.zip')
        manage.compose(*project,'run','--rm','--no-deps','api','python','-m','quarry.admin','reindex')
    finally:
        manage.compose(*project,'start','api','worker')
    check=manage.compose(*project,'exec','-T','api','python','-m','quarry.admin','verify-restore',capture=True)
    evidence=json.loads(check.stdout.strip().splitlines()[-1])
    report={'status':'passed','restoration_seconds':round(time.monotonic()-started,2),
            'evidence':evidence,'backup_checksums':manifest['sha256'],
            'isolated_project':'quarry-restore','paid_calls':0}
    (ROOT/'evaluation/results/restore.json').write_text(json.dumps(report,indent=2))
    print('Isolated restoration stack available at http://localhost:3001. Primary volumes were not restored over.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rehearse',action='store_true')
    args=parser.parse_args()
    result=backup()
    if args.rehearse:
        rehearse(result)
