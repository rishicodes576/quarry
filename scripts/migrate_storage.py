"""Quiesced MinIO-to-SeaweedFS migration. Old data and a private backup are retained."""
import json
import time

import backup
import manage


def migrate():
    receipt = manage.ROOT/'.runtime/storage-migration.json'
    if receipt.exists():
        return
    legacy = manage.run([manage.docker(),'ps','--all','--filter','label=com.docker.compose.project=quarry','--filter','label=com.docker.compose.service=minio','--format','{{.Names}}'],capture=True).stdout.strip()
    if not legacy:
        return
    if '\n' in legacy:
        raise SystemExit('Ambiguous legacy storage containers; inspect before migration')
    print('Migrating existing sources to free SeaweedFS; retaining old storage and a backup.',flush=True)
    manage.run([manage.docker(),'start',legacy],capture=True)
    manage.compose('stop','api','worker')
    completed = False
    try:
        folder = backup.backup(source_endpoint=f'http://{legacy}:9000',restart=False)
        manage.compose('run','--rm','--no-deps','permissions')
        manage.compose('up','--detach','--wait','--wait-timeout','180','objectstore','object-gateway')
        manage.compose('run','--rm','--no-deps','initialize')
        backup.binary(['run','--rm','--no-deps','api','python','-m','quarry.admin','restore-objects','--acknowledge-isolated'],source=folder/'objects.zip')
        result=manage.compose('run','--rm','--no-deps','api','python','-m','quarry.admin','verify-objects',capture=True)
        evidence=json.loads(result.stdout.strip().splitlines()[-1])
        receipt.parent.mkdir(exist_ok=True)
        receipt.write_text(json.dumps({'status':'passed','created_at':time.time(),'backup':str(folder.relative_to(manage.ROOT)),'evidence':evidence},indent=2),encoding='utf-8')
        (manage.ROOT/'evaluation/results/storage-migration.json').write_text(json.dumps({'status':'passed','method':'Quiesced backup, immutable object copy, SHA-256 verification before cutover','evidence':evidence,'legacy_volume_preserved':True,'paid_calls':0},indent=2),encoding='utf-8')
        completed=True
        manage.run([manage.docker(),'stop',legacy],capture=True)
    finally:
        if not completed:
            # Start existing container configurations, which still point to MinIO.
            manage.compose('start','api','worker')
    print('Source hashes verified; old MinIO stopped. Completing application startup.',flush=True)


if __name__=='__main__':
    migrate()
