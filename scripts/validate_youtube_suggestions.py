"""Live production controller + CPU inference; no second CDP client or search."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from core.config import config


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--session',required=True);parser.add_argument('--video');parser.add_argument('--inspect',action='store_true');parser.add_argument('--back',type=int,choices=range(0,4),default=0);options=parser.parse_args();session=options.session
    report={'passed':False,'real_browser':True,'real_cpu_inference':True,'session':session,'commands':[]}
    destination=config.DATA_DIR/'youtube-suggestions-live.json'
    def save():destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with httpx.Client(base_url=f'http://127.0.0.1:{config.PORT}',trust_env=False,timeout=15) as c:
        c.get('/').raise_for_status();assert c.get('/api/browser').json().get('connected'),'Chrome não conectado'
        assert not any(t['state'] in ('queued','running','cancelling') for t in c.get('/api/tasks').json()['tasks']),'Tarefa ativa'
        selected=c.get('/api/settings').json();tab=None
        def command(text,tool='media'):
            nonlocal tab
            identifier='suggestions-probe-'+uuid.uuid4().hex
            c.post('/api/command',json={'id':identifier,'session':session,'command':text}).raise_for_status()
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                task=c.get('/api/tasks/'+identifier).json()
                if task['state'] in ('completed','failed','cancelled'):break
                time.sleep(.2)
            results=[json.loads(row['result']) for row in task['tools'] if row.get('result')]
            report['commands'].append({'request':text,'state':task['state'],'error':task.get('error'),'usage':task['usage'],'results':results});save()
            result=results[-1] if results else {}
            print(json.dumps({'request':text,'state':task['state'],'stage':result.get('stage'),
                'recommendations':len(result.get('snapshot',{}).get('recommendations',[])),'selected':result.get('selected_candidate'),
                'title':result.get('title'),'selection':result.get('music_selection'),'error':task.get('error')},ensure_ascii=True),flush=True)
            assert len(results)==1 and results[0].get('tool')==tool,results
            assert task['usage']['api_calls']==0
            if result.get('tab_id'):
                if tab is None:tab=result['tab_id']
                assert result['tab_id']==tab,'A seleção mudou de aba'
            return task,result
        try:
            c.post('/api/settings',json={'speech_enabled':False}).raise_for_status()
            if options.video:
                task,selection=command('Selecione a aba '+options.video,'browser_select')
                assert task['state']=='completed' and selection.get('verified'),selection
            for _ in range(options.back):
                task,selection=command('Voltar página','browser_back');assert task['state']=='completed'
            task,initial=command('Liste as sugestões do YouTube');assert task['state']=='completed'
            if options.inspect:
                report['inspection_only']=True;save();return
            assert initial['snapshot']['recommendations'],'Nenhuma sugestão elegível observada'
            task,same=command('Toque a primeira sugestão da mesma banda')
            report['same_artist_passed']=task['state']=='completed' and same.get('playback_confirmed') is True
            if not report['same_artist_passed']:
                assert not same.get('playback_confirmed'),'Falha anunciada como sucesso'
                from core.youtube_suggestions import artist_match,artist_refs
                refs=artist_refs(initial['snapshot']['current'],[],'same_artist')
                assert refs and not any(artist_match(row,ref['name']) for row in initial['snapshot']['recommendations'] for ref in refs),'Havia correspondência de artista, mas a troca falhou'
                report['no_match_passed']=True
            else:
                from core.youtube_suggestions import artist_match
                artist=same['music_selection']['decision']['artist']
                expected_same=next(row for row in initial['snapshot']['recommendations'] if artist_match(row,artist))
                assert same['video_id']==expected_same['video_id'],'A escolha pulou a primeira correspondência de artista'
            task,state=command('Liste as sugestões do YouTube');assert task['state']=='completed'
            assert state['snapshot']['recommendations'],'As recomendações seguintes não carregaram no prazo'
            expected=state['snapshot']['recommendations'][0]['video_id']
            task,result=command('Toque a primeira sugestão')
            assert task['state']=='completed' and result.get('playback_confirmed'),result
            assert result['video_id']==expected and result['video_id']!=result['previous_video_id'],result
            task,current=command('Qual música está tocando?')
            assert current['state']['video_id']==result['video_id'] and not current['state']['paused'] and not current['state']['ad']
            assert current['state']['time']>result['position_seconds']
            report['passed']=True;save()
        finally:
            c.post('/api/settings',json={'speech_enabled':selected['speech_enabled']}).raise_for_status();save()


if __name__=='__main__':main()
