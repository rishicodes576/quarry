"""The local JOSE disposition never accepts unrelated, stale or malformed findings."""
import copy
import importlib
import json

import pytest


@pytest.mark.parametrize('mutation,expected', [
    ('exact', True), ('exact-probe', True), ('both-executables', True),
    ('clean', True), ('extra-advisory', False),
    ('wrong-package', False), ('wrong-version', False), ('wrong-target', False),
    ('wrong-image', False), ('scanner-error', False), ('missing-results', False),
    ('missing-schema', False), ('wrong-artifact', False), ('unclean-success', False),
])
def test_jose_disposition(monkeypatch, mutation, expected):
    monkeypatch.syspath_prepend('/opt/quarry-operator')
    gate = importlib.import_module('jose_gate')
    finding = {'VulnerabilityID':'CVE-2026-116587',
               'PkgName':'github.com/go-jose/go-jose/v3', 'InstalledVersion':'v3.0.5'}
    report = {'SchemaVersion':2, 'ArtifactType':'container_image',
              'Metadata':{'ImageID':'sha256:tested-image'},
              'Results':[{'Target':'usr/bin/caddy', 'Vulnerabilities':[finding]}]}
    code = 1
    if mutation == 'exact-probe':
        report['Results'][0]['Target'] = 'usr/bin/quarry-jose-regression'
    elif mutation == 'both-executables':
        report['Results'].append({'Target':'usr/bin/quarry-jose-regression',
                                  'Vulnerabilities':[copy.deepcopy(finding)]})
    elif mutation == 'clean':
        code = 0
        report['Results'][0]['Vulnerabilities'] = []
    elif mutation == 'extra-advisory':
        extra = copy.deepcopy(finding)
        extra['VulnerabilityID'] = 'CVE-OTHER'
        report['Results'][0]['Vulnerabilities'].append(extra)
    elif mutation == 'wrong-package':
        finding['PkgName'] = 'github.com/go-jose/go-jose/v4'
    elif mutation == 'wrong-version':
        finding['InstalledVersion'] = 'v3.0.4'
    elif mutation == 'wrong-target':
        report['Results'][0]['Target'] = 'another-binary'
    elif mutation == 'wrong-image':
        report['Metadata']['ImageID'] = 'sha256:stale-image'
    elif mutation == 'scanner-error':
        code = 2
    elif mutation == 'missing-results':
        del report['Results']
    elif mutation == 'missing-schema':
        del report['SchemaVersion']
    elif mutation == 'wrong-artifact':
        report['ArtifactType'] = 'filesystem'
    elif mutation == 'unclean-success':
        code = 0
    assert gate.finding_disposition(report, code, 'sha256:tested-image') is expected


def test_security_recheck_invalidates_old_success(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend('/opt/quarry-operator')
    scanner = importlib.import_module('security_scan')
    target = tmp_path/'scan'
    target.mkdir()
    (target/'summary.json').write_text(json.dumps({'status':'passed','source_sha256':'same-source'}))
    scanner.invalidate_previous_gate(target, 'same-source')
    result = json.loads((target/'summary.json').read_text())
    assert result['status'] == 'incomplete'
    assert result['source_sha256'] == 'same-source'


def test_module_graph_json_stream_and_truncation(monkeypatch):
    monkeypatch.syspath_prepend('/opt/quarry-operator')
    gate = importlib.import_module('jose_gate')
    assert list(gate.json_stream(' \n{"Path":"one"}\n{"Path":"two"} \n')) == [
        {'Path':'one'}, {'Path':'two'}]
    with pytest.raises(json.JSONDecodeError):
        list(gate.json_stream('{"Path":"one"}\n{"Path":'))
    matching = json.dumps({'ImportPath':'github.com/go-jose/go-jose/v3',
                           'TestGoFiles':['quarry_regression_test.go']})
    gate.validate_test_graph(matching)
    with pytest.raises(json.JSONDecodeError):
        gate.validate_test_graph(matching+'\n{"ImportPath":')
    with pytest.raises(ValueError, match='absent'):
        gate.validate_test_graph('{"ImportPath":"another-package"}')
