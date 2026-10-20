"""Live G522 -> final transcript -> JARVIS tools -> verified YouTube playback.

User speaks only after the beep. Uses the running app's WebSocket capture path,
preserves speech settings, and saves text/metrics without recording audio.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
import websockets
from core.config import config


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--session',default='voice-chain-validation')
    args=parser.parse_args()
    report={'session':args.session,'passed':False,'events':[],'audio_retained':False,
            'real_microphone':True,'real_browser':True,'real_cpu_inference':True}
    destination=config.DATA_DIR/'voice-chain-validation.json'
    identifier='voice-probe-'+uuid.uuid4().hex
    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{config.PORT}',trust_env=False,timeout=35) as client:
        await client.get('/')
        selected=(await client.get('/api/settings')).json()
        assert selected['speech_enabled'],'Habilite a fala para validar a cadeia completa.'
        browser=(await client.get('/api/browser')).json()
        assert browser['connected'],'Conecte o Chrome autorizado antes de iniciar a captura.'
        audio=(await client.get('/api/audio/devices')).json()
        assert not audio['microphone_busy'] and not audio['speech_busy'] and not audio['task_busy'],'Aguarde o estado PRONTO.'
        headers={'Cookie':'; '.join(f'{key}={value}' for key,value in client.cookies.items())}
        started=time.monotonic()
        try:
            async with websockets.connect(f'ws://127.0.0.1:{config.PORT}/ws',additional_headers=headers,proxy=None) as ws:
                await ws.recv()
                await ws.send(json.dumps({'action':'listen_trigger','id':identifier,'session':args.session}))
                deadline=time.monotonic()+180;beeped=False
                while time.monotonic()<deadline:
                    message=json.loads(await asyncio.wait_for(ws.recv(),60))
                    if message.get('session') not in (None,args.session):continue
                    if message.get('type') in ('transcription','notice','audio_diagnostics','progress','state','voice_finished'):
                        report['events'].append(message)
                        if message.get('type')!='state' or message.get('state') in ('LISTENING','SPEAKING','FAILED','COMPLETED'):
                            print(json.dumps(message,ensure_ascii=True),flush=True)
                    if message.get('type')=='state' and message.get('state')=='LISTENING' and not beeped:
                        import winsound
                        winsound.Beep(880,150);beeped=True
                    if message.get('type')=='task_updated' and message.get('task',{}).get('id')==identifier and message['task']['state'] in ('completed','failed','cancelled'):
                        report['task']=(await client.get('/api/tasks/'+identifier)).json();break
                    if message.get('type')=='voice_finished' and not any(e['type']=='transcription' for e in report['events']):
                        raise AssertionError('Captura terminou sem transcrição final.')
                assert 'task' in report,'A tarefa não terminou no prazo.'
                task=report['task'];assert task['state']=='completed',task.get('error')
                results=[json.loads(row['result']) for row in task['tools'] if row.get('result')]
                playback=[row for row in results if row.get('tool')=='play_music']
                assert len(playback)==1 and playback[0].get('playback_confirmed') and playback[0].get('youtube_authenticated'),results
                assert all(row.get('verified') for row in results),results
                assert len([e for e in report['events'] if e['type']=='transcription'])==1
                trace=task['input']
                assert trace.get('final_feedback',{}).get('delivered'),trace.get('speech_result')
                assert trace.get('speech_result',{}).get('state')=='completed',trace.get('speech_result')
                assert 'minecraft' in trace.get('final_search_query','').lower(),trace
                from core.music_resolution import evidence
                chosen=playback[0].get('selected_candidate',{})
                assert chosen and evidence('Rap Minecraft TAUZ',chosen,{'artist':'TAUZ'})['eligible'],chosen
                report['voice_output']=trace['speech_result']
                status=(await client.get('/api/audio/devices')).json()
                assert not status['task_busy'] and not status['speech_busy'] and not status['microphone_busy'],status
                report['passed']=True;report['playback']=playback[0];report['input']=task['input']
        finally:
            report['seconds']=round(time.monotonic()-started,3)
            destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print('Report: '+str(destination),flush=True)


if __name__=='__main__':asyncio.run(main())
