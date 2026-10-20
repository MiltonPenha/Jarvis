"""Live music interpretation through the existing authorized JARVIS controller."""
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from core.config import config


def main():
    report={'passed':False,'real_browser':True,'commands':[]}
    path=config.DATA_DIR/'music-interpretation-live.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with httpx.Client(base_url=f'http://127.0.0.1:{config.PORT}',trust_env=False,timeout=15) as c:
        c.get('/').raise_for_status()
        assert c.get('/api/browser').json().get('connected'),'Conecte o Chrome no HUD antes do teste.'
        assert not any(t['state'] in ('running','queued','cancelling') for t in c.get('/api/tasks').json()['tasks']),'Tarefa ativa'
        settings=c.get('/api/settings').json()
        try:
            c.post('/api/settings',json={'speech_enabled':False}).raise_for_status()
            for command in ('Abra o YouTube e toque uma música do Gunner Rose.','Qual música está tocando?'):
                identifier='music-interpretation-'+uuid.uuid4().hex
                c.post('/api/command',json={'id':identifier,'session':'45359654-49a3-4d70-8a08-368be40fa1a5','command':command}).raise_for_status()
                deadline=time.monotonic()+125
                while time.monotonic()<deadline:
                    task=c.get('/api/tasks/'+identifier).json()
                    if task['state'] in ('completed','failed','cancelled'):break
                    time.sleep(.25)
                results=[json.loads(row['result']) for row in task['tools'] if row.get('result')]
                report['commands'].append({'command':command,'id':identifier,'state':task['state'],'usage':task['usage'],
                    'resolution':task['input'].get('music_resolution'),'results':[{k:v for k,v in row.items() if k!='elements'} for row in results]})
                save();print(json.dumps(report['commands'][-1],ensure_ascii=True),flush=True)
                assert task['state']=='completed',task.get('error')
                if len(report['commands'])==1:
                    music=next(row for row in results if row.get('tool')=='play_music')
                    assert music.get('verified') and music.get('playback_confirmed') and music.get('youtube_authenticated'),music
                    assert music.get('music_resolution',{}).get('accepted'),music
                else:
                    state=results[-1]['state']
                    assert not state['paused'] and not state['ad'] and not state.get('error'),state
                assert task['usage']['api_calls']==0
            report['passed']=True
        finally:
            c.post('/api/settings',json={'speech_enabled':settings['speech_enabled']}).raise_for_status()
            save()


if __name__=='__main__':main()
