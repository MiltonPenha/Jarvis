"""Real production controller; typed voice-like command, not a new microphone capture."""
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
    parser=argparse.ArgumentParser();parser.add_argument('--session',required=True);parser.add_argument('--scenario',choices=['madara','minecraft','confirmation','selection','evaluation'],default='madara');parser.add_argument('--voice',action='store_true');parser.add_argument('--report',type=Path);args=parser.parse_args()
    report={'passed':False,'real_browser':True,'real_cpu_inference':True,'real_microphone':False,'commands':[]}
    path=args.report or config.DATA_DIR/('music-selection-live.json' if args.scenario=='selection' else 'music-confirmation-live.json' if args.scenario=='confirmation' else 'music-flow-live.json' if args.scenario=='minecraft' else 'music-request-live.json')
    if args.report:
        if path.exists():raise SystemExit('O relatório já existe. Escolha outro caminho.')
        path.parent.mkdir(parents=True,exist_ok=True)
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with httpx.Client(base_url=f'http://127.0.0.1:{config.PORT}',trust_env=False,timeout=15) as client:
        client.get('/').raise_for_status();assert client.get('/api/browser').json().get('connected')
        assert not any(row['state'] in ('queued','running','cancelling') for row in client.get('/api/tasks').json()['tasks'])
        previous=client.get('/api/settings').json()
        def command(text):
            identifier='music-request-'+uuid.uuid4().hex
            client.post('/api/command',json={'id':identifier,'session':args.session,'command':text}).raise_for_status()
            deadline=time.monotonic()+125
            while time.monotonic()<deadline:
                task=client.get('/api/tasks/'+identifier).json()
                if task['state'] in ('completed','failed','cancelled'):break
                time.sleep(.2)
            results=[json.loads(row['result']) for row in task['tools'] if row.get('result')]
            report['commands'].append({'request':text,'task':identifier,'state':task['state'],'input':task['input'],'usage':task['usage'],'results':results,'response':task.get('result'),'error':task.get('error')});save()
            print(json.dumps({'request':text,'state':task['state'],'query':task['input'].get('final_search_query'),'title':results[-1].get('title') if results else None,'error':task.get('error')},ensure_ascii=True),flush=True)
            assert task['state']=='completed',task.get('error');assert task['usage'].get('api_calls')==0
            return task,results
        try:
            client.post('/api/settings',json={'speech_enabled':args.voice}).raise_for_status()
            if args.scenario in ('selection','evaluation'):
                cases=['Jarvis, toca música 7 de Jungkook.',
                    'toque a música acúpula de Hariel, Cadu, Don Juan, Tutu, Kaka, João, Zinho, VT, Max, Pereira, DJ, DJBoi e DJBbr.',
                    'Jarvis toca a música acúpula de Hariel.']
                evaluation=json.loads((config.BASE_DIR/'evaluations/music/integration.json').read_text(encoding='utf-8'))['cases'] if args.scenario=='evaluation' else []
                if evaluation:cases=[row['request'] for row in evaluation]
                failures=[]
                for source in cases:
                    # Keep repeated diagnostics quiet; exercise actual speech
                    # on the final complete music request when requested.
                    spoken_case=args.voice and source==cases[-1]
                    client.post('/api/settings',json={'speech_enabled':spoken_case}).raise_for_status()
                    try:
                        task,results=command(source)
                        music=next(r for r in results if r['tool']=='play_music')
                        if evaluation:
                            from core.music_evaluation import query_matches,tokens
                            expected=next(row for row in evaluation if row['request']==source)
                            assert query_matches(task['input']['final_search_query'],[expected['content']]),task['input']['final_search_query']
                            observed=set(tokens(music.get('selected_candidate',{}).get('title','')+' '+music.get('selected_candidate',{}).get('channel','')))
                            assert set(tokens(expected['content']))-{'de','do','da','dos','das'} <= observed,{'expected':expected['content'],'candidate':music.get('selected_candidate')}
                        assert music.get('verified') and music.get('playback_confirmed') and music.get('youtube_authenticated'),music
                        assert len(task['input']['music_search_queries'])==1,task['input']['music_search_queries']
                        assert music['selected_candidate']['video_id']==music['video_id']==music['music_selection']['decision']['candidate_id']
                        assert music['music_pipeline']['task_id']==task['id']
                        assert any(r['video_id']==music['video_id'] for r in music['observed_results'])
                        assert task['usage'].get('vram_bytes',0)==0
                        if spoken_case:assert task['input']['final_feedback']['delivered'],task['input'].get('speech_result')
                        # Retry the same UI event ID: durable task admission must not
                        # dispatch a second search or restart the selected video.
                        client.post('/api/command',json={'id':task['id'],'session':args.session,'command':source}).raise_for_status()
                        duplicate=client.get('/api/tasks/'+task['id']).json()
                        assert duplicate['input']['music_search_queries']==task['input']['music_search_queries'] and len(duplicate['tools'])==len(task['tools'])
                        client.post('/api/settings',json={'speech_enabled':False}).raise_for_status()
                        status,status_results=command('Qual música está tocando?')
                        state=status_results[-1]['state']
                        assert state['video_id']==music['video_id'] and state['time']>music['position_seconds']
                        assert not state['paused'] and not state['ad'] and not state['error']
                    except (AssertionError,StopIteration,KeyError) as exc:
                        if not evaluation:raise
                        # Independent evaluation cases continue after terminal
                        # failures, while uncertain in-flight effects stop here.
                        if report['commands'] and report['commands'][-1]['state'] not in ('completed','failed','cancelled'):raise
                        failures.append({'request':source,'reason':str(exc)[:1200] or type(exc).__name__})
                        report['case_failures']=failures;save()
                report['passed']=not failures
                return
            if args.scenario=='confirmation':
                from core.task_store import TaskStore
                from core.music_followup import confirmation_pending
                pending=TaskStore().last_music_goal(args.session).get('confirmation',{})
                assert confirmation_pending(pending),'Faça um pedido que apresente uma escolha específica antes do ensaio de confirmação.'
                report['offered']=pending
                task,results=command('e isso Jarvis, exatamente esta música.')
                selected=next(row for row in results if row.get('selection_source')=='user_confirmation')
                assert selected.get('playback_confirmed') and selected.get('verified') and selected.get('youtube_authenticated'),selected
                assert selected['video_id']==pending['candidate']['video_id'] and selected['confirmation_id']==pending['id']
                assert not task['input'].get('music_search_queries') and task['usage'].get('local_model_calls')==0
                assert task['input']['music_goal']['confirmation']['state']=='consumed'
                if args.voice:assert task['input']['final_feedback']['delivered'],task['input']['speech_result']
                client.post('/api/settings',json={'speech_enabled':False}).raise_for_status()
                task,results=command('Sim')
                assert not results and task['usage'].get('local_model_calls')==0
                assert 'você quis dizer' not in (task.get('result') or '').lower()
                task,results=command('Qual música está tocando?')
                state=results[-1]['state']
                assert state['video_id']==selected['video_id'] and state['time']>selected['position_seconds']
                assert not state['paused'] and not state['ad'] and not state['error']
                report['passed']=True
                return
            first=('Boa tarde, Jarvis. Toca pra mim a música happy do Minecraft do Taus.' if args.scenario=='minecraft' else 'Boa tarde, Jarvis. Toca pra mim a música TAUZ MADARA.')
            task,results=command(first)
            if args.scenario=='madara':
                assert task['input']['music_intent']['query']=='TAUZ MADARA'
                assert task['input']['final_search_query']=='TAUZ MADARA'
            else:
                assert 'minecraft' in task['input']['final_search_query'].lower()
                assert task['input'].get('music_selection',{}).get('decision',{}).get('accepted')
            music=next(row for row in results if row['tool']=='play_music')
            assert music.get('playback_confirmed') and music.get('verified') and music.get('youtube_authenticated'),music
            if args.voice:assert task['input']['final_feedback']['delivered'],task['input']['speech_result']
            if args.scenario=='madara':assert music['effective_query']=='TAUZ MADARA'
            else:
                first_tab=music['tab_id']
                task,results=command('É rap, não happy')
                corrected=next(row for row in results if row['tool']=='play_music')
                assert corrected['tab_id']==first_tab and corrected.get('playback_confirmed'),corrected
                assert 'minecraft' in task['input']['final_search_query'].lower() and 'happy' not in task['input']['final_search_query'].lower()
                assert task['input']['music_intent']['artist'].lower()=='taus'
                if args.voice:assert task['input']['final_feedback']['delivered']
                music=corrected
            task,results=command('Qual música está tocando?');state=results[-1]['state']
            assert state['video_id']==music['video_id'] and state['time']>music['position_seconds']
            assert not state['paused'] and not state['ad'] and not state['error']
            task,results=command('Toca pra mim uma música')
            assert not results and task['input']['music_intent']['accepted'] is False
            assert not task['input'].get('final_search_query')
            if args.voice:assert task['input']['final_feedback']['delivered']
            report['passed']=True
        finally:
            client.post('/api/settings',json={'speech_enabled':previous['speech_enabled']}).raise_for_status()
            report['real_cpu_inference']=any(row['usage'].get('local_model_calls',0)>0 for row in report['commands'])
            report['real_speech_output']=any(row['input'].get('speech_result',{}).get('delivered') for row in report['commands'])
            save()

if __name__=='__main__':main()
