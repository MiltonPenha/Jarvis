"""Bounded CPU-only speech benchmark. No microphone, playback, or model API calls.

Run with .venv/Scripts/python.exe scripts/benchmark_voice.py --engine piper
The qwen experiment additionally needs the pinned ONNX assets in .runtime/voice-lab.
This script does not change the active voice or other application settings.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TEXT = 'Às suas ordens, Senhor. Estou pronto para ajudar, com calma e atenção.'


def emit(**values):
    print(json.dumps(values, ensure_ascii=True), flush=True)


def worker(args):
    import psutil
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[-args.threads:])
    if os.name == 'nt':
        process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    os.environ.update(OMP_NUM_THREADS=str(args.threads), OPENBLAS_NUM_THREADS=str(args.threads),
                      MKL_NUM_THREADS=str(args.threads), TOKENIZERS_PARALLELISM='false',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', USE_TORCH='0',
                      CUDA_VISIBLE_DEVICES='-1')
    # Only local prepared files are permitted in the inference worker.
    import socket
    def offline(*a, **k):
        raise RuntimeError('Network disabled in voice benchmark.')
    socket.socket.connect = offline
    socket.create_connection = offline

    started = time.monotonic()
    if args.engine == 'qwen':
        lab = ROOT/'.runtime/voice-lab'
        sys.path.insert(0, str(lab/'packages'))
        sys.path.insert(0, str(lab))
        import onnxruntime as ort
        original_session = ort.InferenceSession
        sessions = []
        def limited_session(path, *a, **k):
            options = ort.SessionOptions()
            options.intra_op_num_threads = args.threads
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
            options.enable_cpu_mem_arena = False
            options.enable_mem_pattern = False
            options.log_severity_level = 3
            session = original_session(path, sess_options=options, providers=['CPUExecutionProvider'])
            sessions.append(session)
            emit(stage='loaded_component', name=Path(path).name, rss_mib=round(process.memory_info().rss/2**20, 2))
            return session
        ort.InferenceSession = limited_session
        from inference import Pipeline, SR
        from transformers import AutoTokenizer
        pipe = Pipeline(str(lab/'model'), tts_dir=str(lab/'model'))
        pipe._tok = AutoTokenizer.from_pretrained(str(lab/'model'), local_files_only=True, trust_remote_code=False)
        def synthesize(text, path):
            import numpy as np
            import soundfile as sf
            codes = pipe.generate(text, language='Portuguese', ref_audio=str(lab/'reference.wav'),
                ref_text=(lab/'reference-short-text.txt').read_text(encoding='utf-8'),
                max_new_tokens=96, seed=42, verbose=True)
            if len(codes) == 0:
                raise RuntimeError('No audio generated.')
            if len(codes) >= 96:
                raise RuntimeError('Generation reached the safety limit; incomplete speech rejected.')
            wave = pipe.decode_chunked(codes[None]).reshape(-1)
            if not np.isfinite(wave).all():
                raise RuntimeError('Invalid audio.')
            sf.write(str(path), wave, SR)
        emit(stage='providers', providers=sorted({p for s in sessions for p in s.get_providers()}))
    else:
        from core.neural_voice import neural_voice
        neural_voice.prepare()
        synthesize = neural_voice.synthesize
        emit(stage='providers', providers=neural_voice.prepare().session.get_providers())
    emit(stage='ready', load_seconds=round(time.monotonic()-started, 3),
         rss_mib=round(process.memory_info().rss/2**20, 2), cpu_seconds=round(time.process_time(), 3))
    for i in range(args.iterations):
        target = ROOT/'.data/validation'/f'{args.engine}-resource-sample-{i+1}.wav'
        begin = time.monotonic()
        cpu_begin = time.process_time()
        synthesize(TEXT if args.engine == 'piper' else 'Às suas ordens, Senhor.', target)
        import soundfile as sf
        info = sf.info(str(target))
        emit(stage='synthesis', iteration=i+1, seconds=round(time.monotonic()-begin, 3),
             audio_seconds=round(info.duration, 3), path=str(target),
             cpu_seconds=round(time.process_time()-cpu_begin, 3),
             rss_mib=round(process.memory_info().rss/2**20, 2))
    emit(stage='completed', cpu_seconds=round(time.process_time(), 3),
         rss_mib=round(process.memory_info().rss/2**20, 2))


def gpu_snapshot():
    try:
        return subprocess.check_output(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total',
            '--format=csv,noheader,nounits'], text=True, timeout=5,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def benchmark(args):
    import psutil
    folder = ROOT/'.data/validation'
    folder.mkdir(parents=True, exist_ok=True)
    baseline = [psutil.cpu_percent(interval=.5) for _ in range(10)]
    baseline_memory = psutil.virtual_memory()
    result = {'engine': args.engine, 'logical_cpus': psutil.cpu_count(),
        'limits': {'threads': args.threads, 'rss_mib': args.rss_limit_mib,
                   'min_available_gib': args.minimum_free_gib, 'timeout_seconds': args.timeout,
                   'priority': 'below-normal', 'device': 'CPU only'},
        'baseline': {'cpu_mean_percent': round(statistics.mean(baseline), 2),
                     'cpu_peak_percent': max(baseline),
                     'available_ram_gib': round(baseline_memory.available/2**30, 2),
                     'gpu': gpu_snapshot()},
        'microphone_recorded': False, 'audio_played': False, 'samples': []}
    if baseline_memory.available < (args.minimum_free_gib+1)*2**30:
        raise RuntimeError('Insufficient free RAM for the bounded benchmark.')
    env = {k:v for k,v in os.environ.items() if not any(w in k.upper() for w in ('API_KEY','TOKEN','SECRET','PASSWORD'))}
    env['PYTHONIOENCODING'] = 'utf-8'
    log_path = folder/f'{args.engine}-resource-worker.log'
    started = time.monotonic()
    with log_path.open('w', encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', '--engine', args.engine,
            '--threads', str(args.threads), '--iterations', str(args.iterations)], cwd=str(ROOT), env=env,
            stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        process = psutil.Process(child.pid)
        previous_cpu = 0.
        previous_time = time.monotonic()
        def stop_tree():
            # Windows venv python.exe may be a launcher with the real worker below it.
            for owned in process.children(recursive=True)+[process]:
                try:owned.terminate()
                except psutil.NoSuchProcess:pass
        try:
            while child.poll() is None:
                memory = psutil.virtual_memory()
                try:
                    owned = process.children(recursive=True)+[process]
                    rss = 0.; cpu_seconds = 0.
                    for member in owned:
                        try:
                            rss += member.memory_info().rss/2**20
                            times=member.cpu_times();cpu_seconds += times.user+times.system
                        except psutil.NoSuchProcess:
                            pass
                    now = time.monotonic()
                    cpu_percent=max(0.,cpu_seconds-previous_cpu)/max(now-previous_time,.001)/psutil.cpu_count()*100
                    previous_cpu=cpu_seconds;previous_time=now
                    sample = {'time': round(time.monotonic()-started, 3), 'process_rss_mib': round(rss, 2),
                        'process_cpu_percent_total': round(cpu_percent, 2),
                        'system_cpu_percent': psutil.cpu_percent(), 'available_ram_gib': round(memory.available/2**30, 2)}
                    result['samples'].append(sample)
                    reason = ('memory_limit' if rss > args.rss_limit_mib else 'low_free_memory'
                              if memory.available < args.minimum_free_gib*2**30 else 'time_limit'
                              if time.monotonic()-started > args.timeout else None)
                    if reason:
                        result['stopped_reason'] = reason
                        stop_tree()
                        break
                except psutil.NoSuchProcess:
                    break
                time.sleep(.1)
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                stop_tree()
                child.wait()
    result.update(exit_code=child.returncode, wall_seconds=round(time.monotonic()-started, 3),
                  gpu_after=gpu_snapshot())
    events=[]
    for line in log_path.read_text(encoding='utf-8').splitlines():
        try:
            event=json.loads(line)
            if isinstance(event,dict):events.append(event)
        except json.JSONDecodeError:
            pass
    result['events']=events
    samples=result['samples']
    if samples:
        result['summary']={'peak_rss_mib':max(s['process_rss_mib'] for s in samples),
            'mean_process_cpu_percent_total':round(statistics.mean(s['process_cpu_percent_total'] for s in samples[1:] or samples),2),
            'peak_process_cpu_percent_total':max(s['process_cpu_percent_total'] for s in samples),
            'minimum_available_ram_gib':min(s['available_ram_gib'] for s in samples)}
    target=folder/f'{args.engine}-resources.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    emit(report=str(target), **{k:v for k,v in result.items() if k not in ('samples',)})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--engine', choices=('piper','qwen'), required=True)
    parser.add_argument('--threads', type=int, choices=(1,2), default=2)
    parser.add_argument('--iterations', type=int, choices=range(1,6), default=3)
    parser.add_argument('--rss-limit-mib', type=int, default=2300)
    parser.add_argument('--minimum-free-gib', type=float, default=1.5)
    parser.add_argument('--timeout', type=int, default=120)
    args=parser.parse_args()
    worker(args) if args.worker else benchmark(args)


if __name__ == '__main__':
    main()
