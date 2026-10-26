import json,time,uuid
from pathlib import Path
import manage
from release import fingerprint
project_name='quarry-clean-'+uuid.uuid4().hex[:12]
project=['--project-name',project_name,'-f','compose.yaml','-f','infra/restore.compose.yaml']
report={'status':'running','project':project_name,'source_sha256':fingerprint(),'method':'Fresh isolated project volumes with shared read-only verified model cache. Clean startup, durable PostgreSQL marker, stop/start, marker and readiness verification. Primary data untouched.','paid_calls':0}
started=time.monotonic()
def states():
 value=manage.compose(*project,'ps','--format','json',capture=True).stdout
 rows=[json.loads(line) for line in value.splitlines() if line.strip()]
 assert all(any(r['Service']==s and r['State']=='running' and r.get('Health','') in {'healthy',''} for r in rows) for s in ['api','worker','parser','gateway','postgres','objectstore'])
 return [{'service':r['Service'],'state':r['State'],'health':r.get('Health','')} for r in rows]
try:
 assert not manage.compose(*project,'ps','--all','--quiet',capture=True).stdout.strip(), 'Probe project must be new'
 manage.compose(*project,'up','--no-build','--detach','--wait','--wait-timeout','900')
 report['first_services']=states()
 marker=manage.compose(*project,'exec','-T','api','python','-c',"from quarry.db import Workspace,session;\nwith session() as db, db.begin():\n row=Workspace(name='Restart persistence probe');db.add(row);db.flush();print(row.id)",capture=True).stdout.strip()
 manage.compose(*project,'stop')
 manage.compose(*project,'up','--no-build','--detach','--wait','--wait-timeout','900')
 report['restarted_services']=states()
 result=manage.compose(*project,'exec','-T','api','python','-c',"from quarry.db import Workspace,session;\nwith session() as db:\n assert db.get(Workspace,"+repr(marker)+").name=='Restart persistence probe';print('persisted')",capture=True)
 assert result.stdout.strip()=='persisted'
 report['persistent_marker_verified']=True
 report['status']='passed'
finally:
 report['seconds']=round(time.monotonic()-started,2)
 (manage.ROOT/'evaluation/results/clean-start-restart.json').write_text(json.dumps(report,indent=2))
 manage.compose(*project,'down',check=False)
print(json.dumps(report,indent=2))
