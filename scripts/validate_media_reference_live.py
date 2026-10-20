"""Real YouTube integration, through the backend's existing Chrome controller.

No second CDP client, browser/profile launch, microphone or synthetic player.
Speech is temporarily disabled and restored; this checks playback, not acoustics.
"""
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from core.config import config


def main():
    session='media-reference-live-'+uuid.uuid4().hex
    output=config.DATA_DIR/'validation/media-reference-live.json'
    report={'session':session,'real_browser':True,'real_model':True,'microphone_used':False,'speech_tested':False,'passed':False,'tasks':[]}
    output.parent.mkdir(parents=True,exist_ok=True)
    def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with httpx.Client(base_url=f'http://127.0.0.1:{config.PORT}',trust_env=False,timeout=15) as client:
        client.get('/').raise_for_status()
        assert client.get('/api/browser').json()['connected'],'Chrome is not connected'
        assert not any(row['state'] in ('queued','running','cancelling') for row in client.get('/api/tasks').json()['tasks']),'Backend is busy'
        speech=client.get('/api/settings').json()['speech_enabled']
        def command(text):
            identifier='ref-live-'+uuid.uuid4().hex
            client.post('/api/command',json={'session':session,'id':identifier,'command':text}).raise_for_status()
            for _ in range(600):
                task=client.get('/api/tasks/'+identifier).json()
                if task['state'] in ('completed','failed','cancelled'):break
                time.sleep(.25)
            report['tasks'].append(task);save()
            print(json.dumps({'id':identifier,'state':task['state'],'result':task.get('result'),'intent':task.get('input',{}).get('music_intent',{}).get('action')},ensure_ascii=True),flush=True)
            return task
        try:
            client.post('/api/settings',json={'speech_enabled':False}).raise_for_status()
            first=command('Toque a música TAUZ MADARA no YouTube.')
            result_set=first['input'].get('music_goal',{}).get('result_set',{})
            selected=result_set.get('presented_candidate_id') or result_set.get('selected_candidate_id')
            assert selected,'No single presented/selected candidate; do not arbitrarily pick a result'
            task=command('Quero que você toque exatamente essa mídia que você encontrou.')
            assert task['state']=='completed',task.get('error')
            assert task['input']['music_intent']['action']=='play_existing',task['input']['music_intent']
            assert not task['input'].get('music_search_queries'),'Reference was searched again'
            results=[json.loads(row['result']) for row in task['tools'] if row.get('result')]
            playback=next(row for row in results if row.get('playback_confirmed'))
            assert playback.get('verified') and playback.get('video_id')==selected,playback
            report['authorized_video_id']=selected;report['playback']=playback
            status=command('Qual música está tocando?')
            states=[json.loads(row['result']) for row in status['tools'] if row.get('result')]
            state=states[-1]['state']
            assert state['video_id']==selected and not state['paused'] and not state.get('ad') and state.get('time',0)>0,state
            report['observed_player']=state;report['passed']=True
        except Exception as exc:
            report['error']=str(exc)[:1000];raise
        finally:
            client.post('/api/settings',json={'speech_enabled':speech}).raise_for_status();save()


if __name__=='__main__':main()
