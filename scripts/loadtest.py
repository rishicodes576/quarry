"""Finite scale experiment with concurrent resource samples and campaign quiescence."""
import json
import re
import subprocess
import threading
import time

import manage
from release import fingerprint

samples, errors, reports = [], [], []
stop = threading.Event()
source = fingerprint()
active = manage.compose('--profile','evaluation','ps','--status','running','--services',capture=True)
campaign_running = 'evaluation-campaign' in active.stdout.splitlines()
if campaign_running:
    manage.compose('--profile','evaluation','stop','evaluation-campaign')

def observe():
    while not stop.is_set() and len(samples) < 300:
        try:
            result = subprocess.run([manage.docker(),'stats','--no-stream','--format','{{json .}}'],capture_output=True,text=True,timeout=15,check=False)
            if result.returncode == 0:
                samples.append({'at':time.time(),'containers':[json.loads(line) for line in result.stdout.splitlines() if 'quarry-' in line]})
            else:
                errors.append({'at':time.time(),'exit_code':result.returncode})
        except (subprocess.TimeoutExpired, ValueError):
            errors.append({'at':time.time(),'error':'resource_snapshot_unavailable'})
        stop.wait(2)

observer = threading.Thread(target=observe,daemon=True)
observer.start()
try:
    for workers in [1,2,4]:
        print(f'Provisioning two API replicas and {workers} worker(s)…',flush=True)
        manage.compose('up','--detach','--no-deps','--wait','--wait-timeout','180','--scale','api=2','--scale',f'worker={workers}','api','worker')
        manage.compose('exec','-T','--index','1','api','python','-m','quarry.loadtest','--workers',str(workers))
        if workers == 1:
            manage.compose('exec','-T','--index','1','api','python','-m','quarry.fairness_probe')
        path=manage.ROOT/f'evaluation/results/load-{workers}.json'
        report=json.loads(path.read_text())
        report['source_sha256']=source
        path.write_text(json.dumps(report,indent=2),encoding='utf-8',newline='\n')
        reports.append(report)
finally:
    stop.set()
    observer.join(16)
    manage.compose('up','--detach','--no-deps','--scale','api=1','--scale','worker=1','api','worker')
    if campaign_running:
        manage.compose('--profile','evaluation','start','evaluation-campaign')
    status='passed' if len(reports)==3 and all(r['status']=='passed' for r in reports) and samples else 'failed'
    groups={}
    units={'B':1,'kB':1000,'KB':1000,'MB':10**6,'GB':10**9,'KiB':1024,'MiB':1024**2,'GiB':1024**3}
    for sample in samples:
        containers=sample['containers']
        count=sum(c['Name'].startswith('quarry-worker-') for c in containers)
        group=groups.setdefault(str(count),{'samples':0,'peak_sampled_total_cpu_percent':0,'peak_sampled_total_memory_bytes':0})
        group['samples']+=1
        group['peak_sampled_total_cpu_percent']=max(group['peak_sampled_total_cpu_percent'],sum(float(c['CPUPerc'].strip('%')) for c in containers))
        memory=0
        for container in containers:
            match=re.match(r'([0-9.]+)([A-Za-z]+)',container['MemUsage'].split('/')[0].strip())
            if match:
                memory+=float(match[1])*units[match[2]]
        group['peak_sampled_total_memory_bytes']=max(group['peak_sampled_total_memory_bytes'],memory)
    resource={'status':status,'source_sha256':source,'method':'Concurrent Docker snapshots with two seconds between commands. Grouped by observed worker count including startup/idle. Sampled maxima, not instantaneous peaks. Campaign paused; other workloads must be run separately.','groups_by_worker_count':groups,'observer_errors':errors,'samples':samples}
    (manage.ROOT/'evaluation/results/load-resources.json').write_text(json.dumps(resource,indent=2),encoding='utf-8',newline='\n')
    (manage.ROOT/'evaluation/results/scaling.json').write_text(json.dumps({'status':status,'source_sha256':source,'configurations':reports,'paid_calls':0},indent=2),encoding='utf-8',newline='\n')
if status != 'passed':
    raise SystemExit('Scale experiment did not complete every configuration/resource observation')
