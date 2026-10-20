"""Real CPU voice and playback through the task watchdog, with a fixed test reply.

The reply is a fixture; synthesis, audio file duration, playback and deadlines
are real. No model/browser task or user memory is changed.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.config import config
from core.task_store import TaskStore
from core.assistant_service import AssistantService
from core.audio_manager import audio_manager


async def main():
    events=[];started=time.monotonic()
    async def broadcast(value):events.append({'seconds':round(time.monotonic()-started,3),**value})
    phrase='Senhor, esta é uma validação da voz local. Vou continuar falando até o fim desta frase, sem cortar o áudio.'
    report={'reply_is_fixture':True,'real_synthesis_and_playback':True,'passed':False}
    with tempfile.TemporaryDirectory(prefix='jarvis-speech-validation-') as folder:
        store=TaskStore(Path(folder)/'tasks.db')
        with patch('core.assistant_service.TaskStore',return_value=store):service=AssistantService(broadcast)
        store.create('speech-test','speech-test','Valide a conclusão da frase de teste')
        async def fixed_reply(*args,**kwargs):return {'response':phrase,'spoken_response':phrase,'usage':{'provider':'test-reply','api_calls':0}}
        service.local_runtime.run=fixed_reply
        try:
            await service.execute('speech-test')
            task=store.get('speech-test')
            report.update(task_state=task['state'],speech_result=task['input'].get('speech_result'),seconds=round(time.monotonic()-started,3),events=events)
            result=report['speech_result'] or {}
            assert result.get('state')=='completed',result
            speaking=next(e['seconds'] for e in events if e.get('state')=='SPEAKING')
            completed=next(e['seconds'] for e in events if e.get('state')=='COMPLETED')
            report['playback_observed_seconds']=round(completed-speaking,3)
            assert completed-speaking>=result['audio_seconds']-.1
            report['passed']=True
        finally:
            audio_manager.stop()
            path=config.DATA_DIR/'speech-completion-validation.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in report.items() if k!='events'},ensure_ascii=True),flush=True)


if __name__=='__main__':asyncio.run(main())
