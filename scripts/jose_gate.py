"""Verify the exact gateway's locally backported JOSE implementation; never hide findings."""
import hashlib
import json
import subprocess
import time

from manage import ROOT, docker


def json_stream(source):
    decoder = json.JSONDecoder()
    while source.strip():
        value, end = decoder.raw_decode(source.lstrip())
        yield value
        source = source.lstrip()[end:]


def validate_test_graph(source):
    # Consume the complete artifact before looking for the target package;
    # a matching early object must not hide a truncated trailing record.
    packages = list(json_stream(source))
    if not any(item.get('ImportPath') == 'github.com/go-jose/go-jose/v3'
               and 'quarry_regression_test.go' in item.get('TestGoFiles', [])
               for item in packages):
        raise ValueError('JOSE regression test is absent from the compiled test graph')


def finding_disposition(report, exit_code, image_id):
    """Only this exact legacy finding is eligible after separate patch verification."""
    if (report.get('SchemaVersion') != 2 or report.get('ArtifactType') != 'container_image'
            or report.get('Metadata', {}).get('ImageID') != image_id
            or not isinstance(report.get('Results'), list)):
        return False
    findings = {(row['Target'], item['VulnerabilityID'], item['PkgName'], item['InstalledVersion'])
                for row in report.get('Results', []) for item in row.get('Vulnerabilities', [])}
    expected = {(target, 'CVE-2026-116587', 'github.com/go-jose/go-jose/v3', 'v3.0.5')
                for target in ('usr/bin/caddy', 'usr/bin/quarry-jose-regression')}
    return ((exit_code == 0 and not findings)
            or (exit_code == 1 and bool(findings) and findings <= expected))


def verify(image):
    def command(*args, timeout=60):
        # Argument arrays contain only Docker operations assembled below; no shell.
        result = subprocess.run([docker(), *args], cwd=ROOT, capture_output=True,  # noqa: S603
                                text=True, encoding='utf-8', errors='replace', timeout=timeout)
        if result.returncode:
            raise ValueError('JOSE verification command failed: ' + result.stderr[-1000:])
        return result.stdout

    image_id = command('image', 'inspect', '--format', '{{.Id}}', image).strip()
    expected = (ROOT/'security/jose-v3-backport.json').read_bytes()
    record = json.loads(expected)
    prefix = '/usr/share/quarry/caddy/'

    def read(path):
        return command('run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                       '--security-opt', 'no-new-privileges:true', '--entrypoint', 'cat', image_id, path)

    # Text checkout line endings are normalized, like the release source fingerprint.
    manifest = read(prefix+'jose-v3-backport.json')
    if manifest.replace('\r\n','\n') != expected.decode().replace('\r\n','\n'):
        raise ValueError('Gateway backport manifest differs from reviewed source')
    regression_source = read(prefix+'jose_regression_test.go').replace('\r\n','\n')
    if regression_source != (ROOT/'infra/jose_regression_test.go').read_text(encoding='utf-8'):
        raise ValueError('Gateway regression source differs from reviewed source')
    checks = []
    for item in record['files']:
        content = read(prefix+'jose-v3/'+item['path']).encode()
        if hashlib.sha256(content).hexdigest() != item['patched_sha256']:
            raise ValueError('Gateway patched source mismatch: '+item['path'])
        checks.append({'path':item['path'], 'sha256':item['patched_sha256']})
    info = command('run', '--rm', '--network', 'none', '--entrypoint', 'caddy', image_id, 'build-info')
    if ('github.com/go-jose/go-jose/v4\tv4.1.6' not in info
            or '=>\t./quarry-jose-v3\t(devel)' not in info):
        raise ValueError('Gateway binary does not bind the expected JOSE module graph')
    graph = read(prefix+'jose-selected-modules.json')
    modules = {item['Path']:item for item in json_stream(graph)}
    expected_versions = {'github.com/go-jose/go-jose/v3':'v3.0.5',
                         'github.com/go-jose/go-jose/v4':'v4.1.6',
                         'golang.org/x/crypto':'v0.57.0', 'gopkg.in/yaml.v3':'v3.0.1'}
    if any(modules.get(name,{}).get('Version') != version for name,version in expected_versions.items()):
        raise ValueError('JOSE probe dependency graph does not match the reviewed Caddy graph')
    if modules['github.com/go-jose/go-jose/v3'].get('Replace',{}).get('Path') != './quarry-jose-v3':
        raise ValueError('JOSE probe graph lacks the patched replacement')
    imports = read(prefix+'jose-test-deps.json')
    validate_test_graph(imports)
    tests = read(prefix+'jose-upstream-tests.log')
    required = ['github.com/go-jose/go-jose/v3', 'github.com/go-jose/go-jose/v3/cipher',
                'github.com/go-jose/go-jose/v3/cryptosigner', 'github.com/go-jose/go-jose/v3/json',
                'github.com/go-jose/go-jose/v3/jwt']
    passed = {line.split()[1] for line in tests.splitlines() if line.startswith('ok\t') or line.startswith('ok ')}
    if not set(required) <= passed or 'FAIL' in tests:
        raise ValueError('Full upstream JOSE module test evidence is incomplete')
    started = time.monotonic()
    probe = command('run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges:true', '--memory', '256m', '--cpus', '1',
                    '--entrypoint', '/usr/bin/quarry-jose-regression', image_id,
                    '-test.run', '^TestQuarry', '-test.v', '-test.timeout', '30s', timeout=50)
    for name in ['RSABounds', 'StandaloneKeys', 'EmbeddedPrivateKeys', 'GeneralUnprotectedHeader',
                 'EncryptedPrivateHeaders', 'CryptoRoundTrips']:
        if '--- PASS: TestQuarry'+name not in probe:
            raise ValueError('Missing executed JOSE regression: '+name)
    return {'status':'passed', 'image_id':image_id, 'policy':record['policy'],
            'advisory':record['advisory'], 'source_files':checks,
            'manifest_sha256':hashlib.sha256(expected.replace(b'\r\n',b'\n')).hexdigest(),
            'selected_module_versions':expected_versions,
            'selected_module_graph_sha256':hashlib.sha256(graph.encode()).hexdigest(),
            'test_import_graph_sha256':hashlib.sha256(imports.encode()).hexdigest(),
            'upstream_tests_log_sha256':hashlib.sha256(tests.encode()).hexdigest(),
            'regression_output_sha256':hashlib.sha256(probe.encode()).hexdigest(),
            'regression_output':probe, 'regression_seconds':round(time.monotonic()-started,3),
            'scope':'Exact image, module graph, patched source hashes, build-time full module tests and current sandboxed executable regressions. Local v3 backport, not an upstream release.'}


if __name__ == '__main__':
    print(json.dumps(verify('quarry-gateway:local'), indent=2))
