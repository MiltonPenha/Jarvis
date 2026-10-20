"""Real local output, interruption and recovery. Fixed replies, no microphone/tools.

Run only with the production voice output idle. Saves evidence to .data.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.audio_manager import audio_manager
from core.assistant_service import AssistantService
from core.task_store import TaskStore
from core.config import config

async def main():
    events=[];started=time.monotonic();playing=asyncio.Event()
    async def broadcast(event):
        events.append({'seconds':round(time.monotonic()-started,3),**event})
        if event.get('type')=='speech' and event.get('data',{}).get('phase')=='playing':playing.set()
    with tempfile.TemporaryDirectory(prefix='jarvis-feedback-') as folder:
        service=AssistantService(broadcast);service.store=TaskStore(Path(folder)/'tasks.db')
        cases=json.loads((config.BASE_DIR/'evaluations/voice_feedback.json').read_text(encoding='utf-8'))
        phrase=next(row['text'] for row in cases if row['id']=='long')
        service.store.create('interrupt','validation','Interromper uma fala de teste')
        task=asyncio.create_task(service._say('interrupt',phrase,provider='piper',profile='natural'))
        await asyncio.wait_for(playing.wait(),30)
        assert audio_manager._mic_lock.locked() and audio_manager._speech_lock.locked()
        await asyncio.sleep(.7)
        cancelled_at=time.monotonic();service.cancelled.add('interrupt')
        result=await asyncio.wait_for(task,8)
        interruption_latency=time.monotonic()-cancelled_at
        assert result['state']=='cancelled',result
        assert not audio_manager._mic_lock.locked() and not audio_manager._speech_lock.locked()
        service.store.create('corrected','validation','Retomar após correção')
        corrected=await service._say('corrected','Senhor, recebi a correção. Vou aguardar sua escolha.',provider='piper',profile='natural')
        assert corrected['delivered'] and corrected['state']=='completed',corrected
        assert not audio_manager._mic_lock.locked() and not audio_manager._speech_lock.locked()
        report={'passed':True,'real_synthesis_and_playback':True,'replies_are_fixtures':True,'microphone_used':False,
                'interrupted':result,'interruption_latency_seconds':round(interruption_latency,3),
                'correction':corrected,'events':events,'human_listening':'pending'}
        path=config.DATA_DIR/'evaluation/voice-feedback/output-validation.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='events'},ensure_ascii=True))
        audio_manager.stop()

if __name__=='__main__':asyncio.run(main())
