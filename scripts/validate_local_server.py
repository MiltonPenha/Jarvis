"""Two read-only commands against the running local server; restore audio and remove own probes."""
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from core.config import config
from core.task_store import TaskStore

def main():
    ids=[]; results=[]
    with httpx.Client(base_url=f'http://127.0.0.1:{config.PORT}',timeout=15,trust_env=False) as client:
        client.get('/').raise_for_status()
        selected=client.get('/api/settings').json()
        assert selected['provider']=='local-cpu'
        tasks=client.get('/api/tasks').json()['tasks']
        assert not any(t['state'] in ('queued','running','cancelling') for t in tasks), 'Aguarde a tarefa ativa antes do ensaio.'
        try:
            client.post('/api/settings',json={'speech_enabled':False}).raise_for_status()
            for command in ('Qual o tempo agora?', 'Me mostre os lembretes que estão agendados'):
                identifier='local-probe-'+uuid.uuid4().hex;ids.append(identifier)
                client.post('/api/command',json={'id':identifier,'session':'local-validation','command':command}).raise_for_status()
                deadline=time.monotonic()+125
                while time.monotonic()<deadline:
                    task=client.get('/api/tasks/'+identifier).json()
                    if task['state'] in ('completed','failed','cancelled'): break
                    time.sleep(.25)
                assert task['state']=='completed', task.get('error')
                assert task['usage']['api_calls']==0
                results.append({'command':command,'state':task['state'],'usage':task['usage'],'result':task['result']})
            print(json.dumps({'live_server':results},ensure_ascii=False,indent=2))
        finally:
            client.post('/api/settings',json={'speech_enabled':selected['speech_enabled']}).raise_for_status()
            store=TaskStore()
            with store.connect() as db:
                for identifier in ids:
                    db.execute('DELETE FROM tools WHERE task=?',(identifier,))
                    db.execute("DELETE FROM tasks WHERE id=? AND session='local-validation'",(identifier,))

if __name__=='__main__': main()
