"""Real active player through JARVIS; restore voice/volume, never change Windows."""
import json
from pathlib import Path
import sys
import time
import uuid
import argparse
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from core.config import config
from core.system_audio import endpoint_volume


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--session');session=parser.parse_args().session
    report={'passed':False,'real_playback':True,'commands':[]}
    path=config.DATA_DIR/'volume-live-validation.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with httpx.Client(base_url=f'http://127.0.0.1:{config.PORT}',trust_env=False,timeout=15) as client:
        client.get('/').raise_for_status()
        assert client.get('/api/browser').json().get('connected'),'Conecte no Chrome antes do teste.'
        tasks=client.get('/api/tasks').json()['tasks']
        assert not any(t['state'] in ('running','queued','cancelling') for t in tasks),'Tarefa ativa'
        if not session:
            user=next((t for t in tasks if not t['id'].startswith(('volume-probe-','music-interpretation-','chrome-probe-','local-probe-'))),None)
            assert user,'Informe --session da conversa a validar.'
            session=user['session']
        report['session']=session
        selected=client.get('/api/settings').json();original=None
        system_before=endpoint_volume();report['system_before']={k:system_before[k] for k in ('volume_percent','muted')}
        def command(text,value=None,muted=None,identifier=None):
            identifier=identifier or 'volume-probe-'+uuid.uuid4().hex
            body={'id':identifier,'session':session,'command':text}
            client.post('/api/command',json=body).raise_for_status()
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                task=client.get('/api/tasks/'+identifier).json()
                if task['state'] in ('completed','failed','cancelled'):break
                time.sleep(.1)
            results=[json.loads(row['result']) for row in task['tools'] if row.get('result')]
            assert task['state']=='completed',(text,task.get('error'))
            assert len(results)==1,(text,results)
            result=results[0]
            assert result.get('verified'),result
            assert task['usage'].get('api_calls')==0 and task['usage'].get('local_model_calls')==0,task['usage']
            if value is not None:assert result['volume_percent']==value,(text,result)
            if muted is not None:assert result['state']['muted']==muted,(text,result)
            row={'command':text,'id':identifier,'volume_percent':result['volume_percent'],'muted':result['state']['muted'],
                'change':result.get('volume_change'),'tab_id':result.get('tab_id')}
            report['commands'].append(row);save();print(json.dumps(row,ensure_ascii=True),flush=True)
            return result
        try:
            client.post('/api/settings',json={'speech_enabled':False}).raise_for_status()
            first=command('Qual música está tocando?');original=first
            assert not first['state']['paused'] and not first['state']['ad'],'A reprodução precisa estar ativa para este ensaio.'
            command('Coloque o volume em 48%',48,False)
            identifier='volume-probe-'+uuid.uuid4().hex
            command('JARVIS, diminua o volume para 10%',10,False,identifier)
            command('JARVIS, diminua o volume para 10%',10,False,identifier)
            repeat=command('JARVIS, diminua o volume para 10%',10,False)
            assert not repeat['volume_change']['applied']
            command('Coloque o volume em trinta por cento',30,False)
            command('Dobre o volume',60,False)
            command('Reduza à metade do que está',30,False)
            command('Aumente 10%',40,False)
            command('Reduza em 50% do volume atual',20,False)
            command('Silencie o som',20,True)
            command('Volume mínimo',1,False)
            command('Volume zero',0,True)
            command('Coloque o volume em 10%',10,False)
            final=command('Qual música está tocando?')
            assert final['state']['time']>first['state']['time'] and not final['state']['paused'] and not final['state']['ad']
            assert final['state']['video_id']==first['state']['video_id']
            assert all(row['tab_id']==first['tab_id'] for row in report['commands'])
            system_after=endpoint_volume();report['system_after']={k:system_after[k] for k in ('volume_percent','muted')}
            assert report['system_before']==report['system_after'],'Volume do Windows mudou durante o teste.'
            report['passed']=True
        finally:
            try:
                if original:
                    command(f"Coloque o volume em {original['volume_percent']}%",original['volume_percent'])
                    if original['state']['muted']:command('Silencie o som',muted=True)
                    report['restored']=True
            finally:
                client.post('/api/settings',json={'speech_enabled':selected['speech_enabled']}).raise_for_status();save()


if __name__=='__main__':main()
