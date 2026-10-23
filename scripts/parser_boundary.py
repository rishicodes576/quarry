"""Inspect the actual parser container and run harmless isolation negatives; no model calls."""
import json
from manage import ROOT, compose, docker, run
from release import fingerprint


def main():
    container = compose('ps', '-q', 'parser', capture=True).stdout.strip()
    if not container:
        raise SystemExit('Start the parser service first')
    value = json.loads(run([docker(), 'inspect', container], capture=True).stdout)[0]
    config, host = value['Config'], value['HostConfig']
    names = {item.split('=', 1)[0] for item in config['Env']}
    forbidden = {'GROQ_API_KEY', 'OPENAI_API_KEY', 'QUARRY_DATABASE_URL', 'QUARRY_PROXY_SECRET',
                 'QUARRY_QDRANT_API_KEY', 'QUARRY_S3_SECRET_KEY', 'QUARRY_SMTP_PASSWORD'}
    checks = {
        'separate_uid': config['User'] == '10002:10001',
        'no_network': host['NetworkMode'] == 'none',
        'read_only_root': host['ReadonlyRootfs'],
        'capabilities_dropped': 'ALL' in host['CapDrop'],
        'no_new_privileges': 'no-new-privileges:true' in host['SecurityOpt'],
        'bounded_processes': 0 < host['PidsLimit'] <= 32,
        'bounded_memory': 0 < host['Memory'] <= 1200 * 1024 * 1024,
        'no_application_credentials': not bool(forbidden & names),
        'only_private_socket_volume': all(m['Destination'] == '/parser' for m in value['Mounts'] if m['Type'] != 'tmpfs'),
    }
    probe = '''import json,socket,pathlib
checks={}
try:
 s=socket.create_connection(('1.1.1.1',443),timeout=1); s.close(); checks['egress_denied']=False
except OSError: checks['egress_denied']=True
try:
 pathlib.Path('/app/parser-boundary-probe').write_text('inert'); checks['root_write_denied']=False
except OSError: checks['root_write_denied']=True
checks['private_volumes_absent']=not pathlib.Path('/models').exists() and not list(pathlib.Path('/data').iterdir())
print(json.dumps(checks))'''
    actual = compose('exec', '-T', 'parser', 'python', '-c', probe, capture=True)
    checks.update(json.loads(actual.stdout))
    report = {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
              'source_sha256': fingerprint(),
              'image_id': value['Image'], 'paid_calls': 0,
              'scope': 'Local container configuration and inert negative probes; not a parser RCE or kernel escape test.'}
    (ROOT/'evaluation/results/parser-boundary.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
