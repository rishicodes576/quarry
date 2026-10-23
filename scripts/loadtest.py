import json
import time

import manage

reports=[]
try:
    for workers in [1,2,4]:
        print(f'Provisioning two API replicas and {workers} worker(s)…',flush=True)
        manage.compose('up','--detach','--no-deps','--wait','--wait-timeout','180','--scale','api=2','--scale',f'worker={workers}','api','worker')
        manage.compose('exec','-T','--index','1','api','python','-m','quarry.loadtest','--workers',str(workers))
        if workers==1:
            manage.compose('exec','-T','--index','1','api','python','-m','quarry.fairness_probe')
        path=manage.ROOT/f'evaluation/results/load-{workers}.json'
        report=json.loads(path.read_text())
        stats=manage.run([manage.docker(),'stats','--no-stream','--format','{{json .}}'],capture=True)
        report['container_stats']=[json.loads(line) for line in stats.stdout.splitlines() if 'quarry-' in line]
        path.write_text(json.dumps(report,indent=2))
        reports.append(report)
finally:
    manage.compose('up','--detach','--no-deps','--scale','api=1','--scale','worker=1','api','worker')
(manage.ROOT/'evaluation/results/scaling.json').write_text(json.dumps({'status':'passed','configurations':reports,'paid_calls':0},indent=2))
