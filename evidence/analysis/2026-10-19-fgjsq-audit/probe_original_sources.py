"""Read-only AST probes of supplied sources; no engine/Motor/model imports.
This is audit evidence, not an implementation or a hardware benchmark.
"""
import ast
import hashlib
import json
import logging
import math
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / 'evidence/source_drops'
PROXY = RAW / 'proxy/g4-20261015/load_balance_proxy_finegrained_p3d_pdhybrid.py'
PKG = RAW / 'slo_patch/g4-20261015/slo_patch'
clock_ms = [1000]
ns = dict(math=math, time=time, logger=logging.getLogger('audit'), urlparse=urlparse)

def extract(path, names):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    assert len(nodes) == len(names), (path, names)
    future = ast.parse('from __future__ import annotations').body
    exec(compile(ast.Module(body=future + nodes, type_ignores=[]), str(path), 'exec'), ns)

extract(PROXY, {'FgRequestInfo', 'FineGrainedTokenJSQ'})
ns['_now_ms'] = lambda: clock_ms[0]
FG = ns['FineGrainedTokenJSQ']
s = FG(default_batch_size=24, role='P', log_every=0)
s.add_instance('P0')
s.add_instance('P1')
assert s.dispatch('r0', 250) == 'P0'
assert s.dispatch('r1', 250) == 'P1'
assert s.compute_inst_load('P0', [24, 1000]) == 1000
assert s.compute_inst_load('P0', [25, 1000]) == 1500
event = dict(request_id='r0', num_prompt_tokens=1000, num_scheduled_tokens=200,
             num_remaining_tokens=600, num_computed_tokens=200, predicted_exec_ms=100)
assert s.on_batch_event('P0', 10, [event]) == 1
assert s.inst_loads['P0'] == [1, 1000]
assert s.req_dispatch_info['r0'].original_load == 1000
values = [s.compute_actual_load(s.req_dispatch_info['r0'], t) for t in (1000, 1050, 2000)]
assert values == [800, 700, 610], values
s.recompute_and_commit(1050)
assert s.inst_loads['P0'] == [1, 700]
assert s.on_batch_event('P0', 9, [event]) == 0
assert s.on_batch_event('P1', 11, [event]) == 0
assert s.reduce_load('r0') is True
assert s.reduce_load('r0') is False
assert s.inst_loads['P0'] == [0, 0]
assert s.on_batch_event('P0', 12, [event]) == 0

# Run the actual original reporter method with network calls replaced by capture.
extract(PKG / 'slo/batch_event_reporter.py', {'BatchEventReporter'})
Reporter = ns['BatchEventReporter']
reporter = Reporter.__new__(Reporter)
reporter._closed = False
reporter._addr = 'P0'
reporter._port = 8000
payloads = []
reporter._send = lambda endpoint, payload: payloads.append((endpoint, payload))
uuid = 'audit-uuid'
engine_id = 'chatcmpl-' + uuid + '-12345678'
req = SimpleNamespace(num_prompt_tokens=1000, num_tokens=1000, num_computed_tokens=400,
                      kv_transfer_params={'metaserver': 'http://example.invalid/some/path'})
out = SimpleNamespace(num_scheduled_tokens={engine_id: 200}, predicted_batch_exec_time=100.0)
reporter._emit(out, {engine_id: req})
req.num_computed_tokens = 600
reporter._emit(out, {engine_id: req})
first = payloads[0][1]['requests'][0]
second = payloads[1][1]['requests'][0]
assert first['request_id'] == 'chatcmpl-' + uuid
s.dispatch(uuid, 250)
assert s.match_request(first['request_id']) is None
assert (first['num_computed_tokens'], first['num_remaining_tokens']) == (200, 600)
assert (second['num_computed_tokens'], second['num_remaining_tokens']) == (400, 400)
assert payloads[0][0] == 'http://example.invalid/update_batch_event'

# Execute original feature arithmetic using a scalar-only replacement for np.clip.
ns['np'] = SimpleNamespace(clip=lambda x, lo, hi: min(max(x, lo), hi))
extract(PKG / 'slo/predictor_impl.py', {'compute_features'})
extract(PKG / 'patch_core.py', {'_predict_batch_exec_time'})
req.num_computed_tokens = 400
req.request_id = engine_id
calls = []
def predict(**kwargs):
    calls.append(kwargs)
    return 100.0
scheduler = SimpleNamespace(predictor=SimpleNamespace(predict=predict), running=[req])
ns['_predict_batch_exec_time'](scheduler, out, 'audit')
features = ns['compute_features'](**calls[0])
assert calls[0] == {'batch_size': 1, 'avg_prompt_length': 1000.0, 'cache_hit_rate': 0.6}
assert features['N_uncached'] == 400.0
assert features['N_cached'] == 600.0
assert out.num_scheduled_tokens[engine_id] == 200

files = sorted(p for p in RAW.rglob('*') if p.is_file() and p.name != '.gitkeep')
manifest = {
    'recorded_date': '2026-10-19',
    'scope': 'raw user source intake; not a claim of onsite byte identity',
    'files': [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size,
               'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
               'provenance': 'user_pasted_chat_archived_by_assistant' if p.name == 'setup.py' else 'user_placed_source_drop'}
              for p in files],
}
results = {
    'status': 'all assertions passed',
    'method': 'original AST classes/functions; stdlib only, synthetic clock and requests, no HTTP, no model or NPU',
    'limitations': ['not an end-to-end Motor or engine test', 'no prediction accuracy or performance claim',
                    'mutable-request probe shows sensitivity to timing, not observed production incidence'],
    'fgjsq': {'tie_order': ['P0', 'P1'], 'score_at_counts_24_25_for_load1000': [1000, 1500],
              'first_event_corrected_original': 1000, 'load_at_elapsed_0_50_1000ms': values,
              'stale_wrong_instance_late_events_ignored': True, 'double_release_idempotent': True},
    'identity': {'proxy_id': uuid, 'engine_id': engine_id, 'reporter_id': first['request_id'], 'matched': False},
    'mutable_reporter_snapshot': {'before': first, 'after_later_schedule': second},
    'features': {'inputs': calls[0], 'current_batch_scheduled_tokens': 200, 'values': features},
}
(ROOT / 'evidence/manifests/g4_source_intake_20261019.json').write_text(json.dumps(manifest, indent=2) + '\n')
Path(__file__).with_name('probe_results.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps({'status': results['status'], 'raw_files': len(files), 'result': str(Path(__file__).with_name('probe_results.json'))}))