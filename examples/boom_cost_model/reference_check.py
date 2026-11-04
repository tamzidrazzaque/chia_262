"""Paired held-out reference validation on both verified physical F2 workers.

Reference results are stored separately and must never enter train proposals.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import threading
import traceback

import ray

from chia.chipyard.spec_validation import relative_speedup
from chia.cluster.loopback import driver_options, require_guard
from examples.boom_cost_model.focused_campaign import import_baseline_cache, measure, prepare
from examples.boom_cost_model.optimize import Experiment, save, verified_workers


def run(source, root, baseline_cache_dirs=()):
    """Recheck test artifacts, then compare original and selected compiler per worker."""
    config = json.loads((source / 'config.json').read_text())
    report = json.loads((source / 'result.json').read_text())
    selected = report.get('selected_train_proposal') or report.get('best_train_proposal')
    if not report.get('complete') or not selected or not selected.get('success'):
        raise ValueError('reference check requires a complete, selected validated compiler')
    specification = {'source':str(source), 'result_sha256':hashlib.sha256((source / 'result.json').read_bytes()).hexdigest(),
        'compiler_id':selected['compiler']['compiler_id'], 'inputs':'ref', 'benchmarks':config['benchmarks']}
    if baseline_cache_dirs:
        specification['extra_baseline_cache_dirs'] = [str(p) for p in baseline_cache_dirs]
    if (root / 'check.json').exists() and json.loads((root / 'check.json').read_text()) != specification:
        raise ValueError('reference-check specification changed')
    save(root / 'check.json',specification)
    if (root / 'result.json').exists():
        return
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_:stop.set())
    signal.signal(signal.SIGTERM, lambda *_:stop.set())
    initial = Experiment(config,root / 'preflight')
    workers = verified_workers(config, initial.hardware)
    if len(workers) != 2:
        raise ValueError('reference check requires two verified workers')
    original = prepare(config,source / 'baseline-prepared')
    winner = prepare(config,source / f"candidate-{selected['index']:03d}",selected['index'],selected['proposal'])
    if winner['compiler'] != selected['compiler']:
        raise ValueError('reference compiler identity changed')
    artifacts = {}
    for name,item in (('original',original),('selected',winner)):
        if stop.is_set():
            save(root / 'stopped.json',{'drained':True})
            return
        artifacts[name] = {**item,'workload':initial.workload(item['compiler'],'ref',root / 'prepared' / name)}
    def worker(index):
        ex = Experiment(config,root / f'worker-{index}')
        ex.workers = [workers[index]]
        import_baseline_cache(ex.directory / 'measurement-cache',
            config.get('baseline_cache_dirs', []) + [str(p) for p in source.glob('worker-*/measurement-cache')]
            + [str(p) for p in baseline_cache_dirs],
            allowed_labels=('baseline-f2','baseline-heldout','original'))
        samples = {}
        # Order balancing preserves paired controls on EACH physical worker.
        order = ('original','selected') if index == 0 else ('selected','original')
        for name in order:
            if stop.is_set():
                return None
            samples[name] = measure(ex,artifacts[name],name,inputs='ref',stop=stop)
        return {'instance_id':workers[index]['instance_id'], 'order':order,'samples':samples,
            'reference_speedup':relative_speedup(samples['original']['times'],samples['selected']['times'])}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(worker,i):i for i in range(2)}
        results = [None,None]
        try:
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        except Exception:
            stop.set()
            raise
    if stop.is_set() or any(r is None for r in results):
        save(root / 'stopped.json',{'drained':True})
        return
    save(root / 'result.json',{'complete':True, 'reference_checked':True,
        'compiler_id':selected['compiler']['compiler_id'], 'benchmarks':config['benchmarks'],
        'workers':results,'SPEC_reportable_score':False,
        'interpretation':'Paired reference research estimate per physical worker; cache reuses are not new independent samples. Excluded from proposal feedback.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--baseline-cache',type=Path,action='append',default=[],
        help='Extra validated original-compiler cache; full keys/raw/native checks still apply')
    args = parser.parse_args()
    os.umask(0o077)
    args.run_dir.mkdir(parents=True,exist_ok=True)
    with (args.run_dir / 'controller.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_guard()
        ray.init(**driver_options(os.environ['RAY_ADDRESS']))
        try:
            run(args.source.resolve(),args.run_dir.resolve(),args.baseline_cache)
        except Exception:
            save(args.run_dir / 'failure.json',{'traceback':traceback.format_exc()})
            raise
        finally:
            ray.shutdown()


if __name__ == '__main__':
    main()
