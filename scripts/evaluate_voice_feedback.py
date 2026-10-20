"""Same phrases, local synthesis, no playback/mic. Network blocked in this process.

python scripts/evaluate_voice_feedback.py --phase before --engine qwen-local
python scripts/evaluate_voice_feedback.py --phase after --engine piper
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['before','after'],required=True)
    parser.add_argument('--engine',choices=['qwen-local','piper'],required=True)
    parser.add_argument('--case',help='Optional corpus id for a bounded supplemental measurement')
    parser.add_argument('--tag',default='',help='Separate supplemental output directory')
    args=parser.parse_args()
    os.environ.update(CUDA_VISIBLE_DEVICES='-1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    original_connect=socket.socket.connect
    def offline(sock,address):
        # Windows asyncio uses loopback sockets for its internal wake-up pipe.
        if isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'):return original_connect(sock,address)
        raise RuntimeError('External network disabled for voice evaluation')
    socket.socket.connect=offline
    import psutil
    import numpy as np
    import soundfile as sf
    from core.audio_manager import audio_manager,speech_text
    from core.qwen_voice import qwen_voice
    from core.neural_voice import neural_voice
    process=psutil.Process()
    if os.name=='nt':process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    output=ROOT/'.data/evaluation/voice-feedback'/args.phase/(args.engine+args.tag)
    output.mkdir(parents=True,exist_ok=True)
    rows=[];peak=[0];stop=threading.Event()
    def monitor():
        while not stop.wait(.15):
            try:peak[0]=max(peak[0],sum(p.memory_info().rss for p in [process]+process.children(recursive=True) if p.is_running()))
            except psutil.Error:pass
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try:
        for case in json.loads((ROOT/'evaluations/voice_feedback.json').read_text(encoding='utf-8')):
            if args.case and case['id']!=args.case:continue
            path=output/(case['id']+'.wav');started=time.monotonic()
            def cpu_seconds():
                total=0
                for p in [process]+process.children(recursive=True):
                    try:values=p.cpu_times();total+=values.user+values.system
                    except psutil.Error:pass
                return total
            cpu_before=cpu_seconds()
            # The baseline reproduces the old effective Qwen limit (including its
            # appended suffix), independent of subsequent source edits.
            text=case['text'] if args.phase=='before' else speech_text(case['text'])
            if args.phase=='before' and args.engine=='qwen-local' and len(text)>220:
                shortened=text[:220];point=max(shortened.rfind('.'),shortened.rfind('!'),shortened.rfind('?'))
                text=(shortened[:point+1] if point>110 else shortened.rsplit(' ',1)[0]+'.')+' Os detalhes completos estão na tela.'
            try:
                if args.phase=='before':
                    if args.engine=='qwen-local':qwen_voice.synthesize(text,path)
                    else:neural_voice.synthesize(text,path)
                else:asyncio.run(audio_manager.synthesize(text,path,args.engine,profile='natural' if args.engine=='piper' else None))
                data,rate=sf.read(path,dtype='float32')
                row={**case,'spoken_text':text,'generation_seconds':round(time.monotonic()-started,3),
                     'audio_seconds':round(len(data)/rate,3),'sample_rate':rate,'peak':float(np.max(np.abs(data))),
                     'clipped_fraction':float(np.mean(np.abs(data)>=.9999)),'finite':bool(np.isfinite(data).all()),'path':str(path)}
                row['cpu_seconds']=round(cpu_seconds()-cpu_before,3)
                row['cpu_percent_machine_average']=round(100*row['cpu_seconds']/max(.001,row['generation_seconds'])/psutil.cpu_count(),2)
            except Exception as exc:row={**case,'error':str(exc),'generation_seconds':round(time.monotonic()-started,3)}
            rows.append(row)
            report={'phase':args.phase,'engine':args.engine,'network_blocked':True,'providers':['CPUExecutionProvider'],
                    'peak_tree_rss_mib':round(peak[0]/2**20,1),'cases':rows,'naturalness':'requires human listening'}
            (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k not in ('text','spoken_text')},ensure_ascii=True),flush=True)
    finally:stop.set();thread.join();qwen_voice.close()

if __name__=='__main__':main()
