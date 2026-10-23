"""Local, isolated production-mode HTTPS/STARTTLS acceptance; never creates cloud resources."""
import http.cookiejar
import json
import re
import secrets
import ssl
import time
import urllib.error
import urllib.request

from manage import ROOT, compose, docker, read_env, run
from release import fingerprint

ORIGIN = 'https://localhost:3443'


def main():
    folder = ROOT/'.runtime/production-probe'
    tls = folder/'tls'
    tls.mkdir(parents=True, exist_ok=True)
    run([docker(),'run','--rm','--network','none','--mount',f'type=bind,source={tls},target=/out',
         '--mount',f'type=bind,source={ROOT / "scripts/tls_fixture.py"},target=/tool.py,readonly',
         'quarry-backend:local','python','/tool.py'])
    values = read_env()
    password = secrets.token_hex(24)
    values.update(POSTGRES_PASSWORD=secrets.token_hex(24),
                  QUARRY_DATABASE_URL=f'postgresql+psycopg://quarry_runtime:{password}@postgres:5432/quarry',
                  QUARRY_SESSION_SECRET=secrets.token_hex(48), QUARRY_PROXY_SECRET=secrets.token_hex(32),
                  QUARRY_S3_ACCESS_KEY='rehearsal'+secrets.token_hex(8), QUARRY_S3_SECRET_KEY=secrets.token_hex(32),
                  QUARRY_QDRANT_API_KEY=secrets.token_hex(32), QUARRY_ENV='production',
                  QUARRY_APP_ORIGIN=ORIGIN,QUARRY_DEMO_SEED='false',QUARRY_COOKIE_SECURE='true',
                  QUARRY_SIGNUP_MODE='public',QUARRY_SMTP_HOST='mailpit',QUARRY_SMTP_PORT='1025',
                  QUARRY_SMTP_STARTTLS='true',QUARRY_SMTP_USER='',QUARRY_SMTP_PASSWORD='',
                  GROQ_API_KEY='',OPENAI_API_KEY='',QUARRY_ALLOW_PAID_PROVIDERS='false',
                  QUARRY_GROQ_FREE_PLAN_CONFIRMED='false')
    env = folder/'rehearsal.env'
    if not env.exists():
        env.write_text('\n'.join(f'{k}={v}' for k,v in values.items())+'\n')
    project = ['--env-file',str(env),'--project-name','quarry-production-probe',
               '-f','compose.yaml','-f','infra/rehearsal.compose.yaml']
    checks = {}
    report = {'status':'running','checks':checks,'paid_calls':0,
              'source_sha256':fingerprint(),
              'scope':'Isolated loopback production-mode HTTPS and STARTTLS with a private test CA. No public ACME, Internet SMTP or cloud deployment claim.'}
    started = time.monotonic()
    try:
        compose(*project,'up','--no-build','--detach','--wait','--wait-timeout','900')
        context = ssl.create_default_context(cafile=str(tls/'ca.pem'))
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                    urllib.request.HTTPSHandler(context=context),urllib.request.HTTPCookieProcessor(jar))

        def request(path, body=None, headers=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(ORIGIN+path,data=data,
                    headers={'Origin':ORIGIN,'Content-Type':'application/json',**(headers or {})})
            try:
                response = opener.open(req,timeout=30)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                payload = response.read()
                try:
                    value = json.loads(payload) if payload else None
                except json.JSONDecodeError:
                    value = None
                return response.status, value, response.headers

        checks['trusted_https_ready'] = request('/api/health/ready')[0] == 200
        checks['demo_disabled'] = request('/api/v1/auth/login',{'email':'demo@quarry.local','password':'demo'})[0] != 200
        email = 'rehearsal-'+secrets.token_hex(6)+'@example.com'
        checks['public_signup_accepted'] = request('/api/v1/auth/register',{'email':email})[0] == 202
        checks['no_session_before_verification'] = request('/api/v1/auth/me')[0] == 401
        # Token stays inside captured process memory and is never printed or saved to evidence.
        mail_probe = '''import json,urllib.request
with urllib.request.urlopen('http://mailpit:8025/api/v1/messages') as r: m=json.load(r)
ids=[x['ID'] for x in m['messages'] if any(t['Address']==EMAIL for t in x['To'])]
if ids:
 with urllib.request.urlopen('http://mailpit:8025/api/v1/message/'+ids[0]) as r: print(json.load(r)['Text'])
'''.replace('EMAIL',repr(email))
        token = None
        for _ in range(60):
            result = compose(*project,'exec','-T','api','python','-c',mail_probe,capture=True)
            match = re.search(r'/#signup=([A-Za-z0-9_-]+)',result.stdout)
            if match:
                token = match.group(1)
                break
            time.sleep(1)
        checks['starttls_email_delivered'] = bool(token)
        if not token:
            raise RuntimeError('STARTTLS verification message did not arrive')
        credentials = {'token':token,'password':'a rehearsal only passphrase','workspace':'Production rehearsal'}
        checks['verification_single_use'] = (request('/api/v1/auth/redeem',credentials)[0] == 204 and
                                             request('/api/v1/auth/redeem',credentials)[0] == 400)
        status, _, headers = request('/api/v1/auth/login',{'email':email,'password':credentials['password']})
        cookies = ';'.join(headers.get_all('Set-Cookie') or [])
        checks['secure_http_only_session'] = status == 200 and 'Secure' in cookies and 'HttpOnly' in cookies
        checks['authenticated_https_request'] = request('/api/v1/auth/me')[0] == 200
        checks['csrf_rejected'] = request('/api/v1/conversations',{'title':'Rejected'}, {'Origin':'https://attacker.example'})[0] == 403
        checks['production_openapi_private'] = request('/api/openapi.json')[0] == 404
        checks['session_revoked'] = request('/api/v1/auth/logout',{})[0] == 204 and request('/api/v1/auth/me')[0] == 401
        report['status'] = 'passed' if all(checks.values()) else 'failed'
    except BaseException as error:
        report['status'],report['error_type'] = 'failed',type(error).__name__
        raise
    finally:
        report['seconds'] = round(time.monotonic()-started,2)
        (ROOT/'evaluation/results/production-rehearsal.json').write_text(json.dumps(report,indent=2))
        compose(*project,'down',check=False)
    print(json.dumps(report,indent=2))
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
