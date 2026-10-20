"""Offline evaluation utilities. Never train, choose a new model, or execute a song."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata

ROOT=Path(__file__).resolve().parent.parent
DATA=ROOT/'evaluations/music'
SOURCE_FILES=('core/music_intent.py','core/music_resolution.py','core/youtube_control.py',
    'core/local_model.py','core/audio_manager.py','core/assistant_service.py','core/local_runtime.py')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tokens(value):
    value=''.join(c for c in unicodedata.normalize('NFD',str(value).casefold()) if unicodedata.category(c)!='Mn')
    return re.findall(r'\w+',value)


def distance(reference,hypothesis):
    previous=list(range(len(hypothesis)+1))
    for index,left in enumerate(reference,1):
        current=[index]
        for j,right in enumerate(hypothesis,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(left!=right)))
        previous=current
    return previous[-1]


def recognition_metrics(reference,hypothesis,entities=()):
    expected=tokens(reference);actual=tokens(hypothesis)
    if not expected:raise ValueError('A referência de transcrição não pode ser vazia.')
    left=' '.join(expected);right=' '.join(actual)
    counts=Counter(actual);entity_words=[word for entity in entities for word in tokens(entity)]
    found=sum(min(count,counts[word]) for word,count in Counter(entity_words).items())
    return {'word_errors':distance(expected,actual),'reference_words':len(expected),
        'wer':distance(expected,actual)/len(expected),'cer':distance(left,right)/max(1,len(left)),
        'content_token_recall':found/len(entity_words) if entity_words else None}


def query_matches(actual,variants):
    # Only structural title/artist connectors may vary. Unlike production
    # evidence, the scorer keeps digits, single letters, and command words.
    canonical=lambda value:Counter(w for w in tokens(value) if w not in ('de','do','da','dos','das'))
    return any(canonical(actual)==canonical(expected) for expected in variants)


def load_suite():
    suite={split:json.loads((DATA/(split+'.json')).read_text(encoding='utf-8')) for split in ('development','holdout')}
    seen=set()
    for split,group in suite.items():
        for case in group['cases']+group['selection']:
            if case['id'] in seen:raise ValueError('ID de caso duplicado: '+case['id'])
            seen.add(case['id'])
        for case in group['selection']:
            ids={row['video_id'] for row in case['rows']}
            if any(not re.fullmatch(r'[\w-]{11}',identifier) for identifier in ids) or not set(case['expected_ids'])<=ids:
                raise ValueError('IDs de seleção inválidos: '+case['id'])
    for field in ('work_id','artist_id'):
        overlap={r[field] for r in suite['development']['cases']} & {r[field] for r in suite['holdout']['cases']}
        if overlap:raise ValueError('Vazamento entre divisões: '+field+' '+str(overlap))
    return suite


def runtime_snapshot():
    from core.config import config,settings
    from core.local_model import MODEL
    selected=settings()
    manifests=config.DATA_DIR/'models/ollama/manifests'
    return {'model':MODEL,'inference_device':'cpu','stt_model':config.WHISPER_PATH.name,'stt_provider':selected['stt_provider'],
        'tts_provider':selected['tts_provider'],'whisper_beam_size':config.WHISPER_BEAM_SIZE,
        'code_hashes':{name:digest(ROOT/name) for name in SOURCE_FILES},
        'dataset_hashes':{name:digest(DATA/(name+'.json')) for name in ('development','holdout','integration')},
        'evaluation_hashes':{name:digest(ROOT/name) for name in ('core/music_evaluation.py','scripts/evaluate_music.py','scripts/validate_music_request.py')},
        'model_manifests':{str(p.relative_to(manifests)):digest(p) for p in manifests.rglob('*') if p.is_file()} if manifests.exists() else {},
        'training_performed':False}


def summarize(rows):
    groups=defaultdict(list)
    for row in rows:groups[(row['split'],row['stage'],row['environment'])].append(row)
    result=[]
    for (split,stage,environment),cases in groups.items():
        counts=Counter(row['status'] for row in cases);seconds=sorted(row.get('seconds',0) for row in cases if row['status'] in ('passed','failed'))
        entry={'split':split,'stage':stage,'environment':environment,'counts':dict(counts),'total':len(cases),
            'evaluated':counts['passed']+counts['failed'],'coverage':(counts['passed']+counts['failed'])/len(cases),
            'pass_rate':counts['passed']/(counts['passed']+counts['failed']) if counts['passed']+counts['failed'] else None,
            'p50_seconds':seconds[len(seconds)//2] if seconds else None,'p95_seconds':seconds[min(len(seconds)-1,int(len(seconds)*.95))] if seconds else None}
        scored=[r['metrics'] for r in cases if r.get('metrics',{}).get('reference_words')]
        if scored:
            entry['corpus_wer']=sum(r['word_errors'] for r in scored)/sum(r['reference_words'] for r in scored)
            entry['mean_cer']=sum(r['cer'] for r in scored)/len(scored)
        result.append(entry)
    return result


def write_report(report,path):
    report['summary']=summarize(report['results']);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,suffix='.tmp',delete=False) as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2);temporary=Path(stream.name)
    try:
        # Windows indexers/AV can briefly hold a just-written report. Keep the
        # previous complete JSON readable, retry the replace, never truncate it.
        for attempt in range(8):
            try:temporary.replace(path);break
            except PermissionError:
                if attempt==7:raise
                time.sleep(.05*(attempt+1))
    finally:
        if temporary.exists():temporary.unlink()


async def evaluate_offline(report,path,suite,splits,modes,recordings=None,sealed=False):
    from core.music_intent import interpret,requested
    from core.music_resolution import select_result
    from core.local_model import local_model
    async def add(case,split,stage,environment,operation):
        start=time.monotonic()
        try:result=await operation();result={'status':'passed' if result.pop('passed') else 'failed',**result}
        except Exception as exc:result={'status':'blocked','reason':type(exc).__name__+': '+str(exc)[:300]}
        report['results'].append({'id':case['id'],'split':split,'stage':stage,'environment':environment,
            'tags':case.get('tags',[]),'seconds':round(time.monotonic()-start,3),**result})
        write_report(report,path)
        if split!='holdout' or not sealed:print(json.dumps({k:report['results'][-1][k] for k in ('id','stage','status')},ensure_ascii=True),flush=True)
    for split in splits:
        if 'text' in modes:
            for case in suite[split]['cases']:
                state={}
                async def intention():
                    routed=requested(case['request'])
                    result=await interpret(case['request'],{}) if routed else {'accepted':False,'reason':'not_routed'}
                    state.update(result)
                    blocked=result.get('reason')=='model_unavailable'
                    if blocked:raise RuntimeError('IA local indisponível: '+result.get('error_type','unknown'))
                    positive=case['action']=='play'
                    return {'passed':routed and bool(result.get('accepted'))==positive,
                        'request':case['request'],'expected_action':case['action'],'routed_to_music':routed,'intent':result}
                await add(case,split,'intent','real_cpu_text',intention)
                async def assembly():
                    positive=case['action']=='play';query=state.get('query','')
                    return {'passed':query_matches(query,case['queries']) if positive else not state.get('accepted') and not query,
                        'query':query,'expected_queries':case['queries'],'conditional_on_intent':bool(state.get('accepted'))}
                await add(case,split,'query','text_contract',assembly)
        if 'selection' in modes:
            for case in suite[split]['selection']:
                async def selection():
                    goal={**case.get('goal',{}),'query':case['query']}
                    result=await select_result(case['query'],case['rows'],goal)
                    if result.get('reason')=='model_unavailable':raise RuntimeError('IA local indisponível: '+result.get('error_type','unknown'))
                    accepted=bool(result.get('accepted'));expected=case['expected_ids']
                    good=accepted and result.get('candidate_id') in expected if expected else not accepted
                    if case.get('reason'):good=good and result.get('reason')==case['reason']
                    return {'passed':good,'query':case['query'],'expected_ids':expected,'selection':result,
                        'model_is_mocked':False,'candidate_rows_are_fixtures':True}
                await add(case,split,'selection','real_cpu_fixture_results',selection)
    if 'contracts' in modes:
        for scenario in ('playing','navigation_failure','player_failure','wrong_video','advertisement'):
            async def execution():return execution_probe(scenario)
            await add({'id':'execution-'+scenario},'contract','playback','simulated_player',execution)
        for scenario in ('success','failure','clarification','output_failure'):
            async def feedback():return await feedback_probe(scenario)
            await add({'id':'feedback-'+scenario},'contract','feedback','simulated_audio_output',feedback)
    if 'stt' in modes:
        await evaluate_recordings(report,path,recordings,suite,splits,add)


def execution_probe(scenario):
    from types import SimpleNamespace
    from unittest.mock import patch,Mock
    from core.youtube_control import play_youtube
    clock=SimpleNamespace(elapsed=0.)
    page=Mock();page.url='https://www.youtube.com/results';navigations=[]
    def goto(url,**kwargs):
        navigations.append(url)
        if '/watch?' in url and scenario=='navigation_failure':raise TimeoutError('controlled navigation failure')
        page.url=url
    page.goto.side_effect=goto
    page.wait_for_timeout.side_effect=lambda ms:setattr(clock,'elapsed',clock.elapsed+ms/1000)
    page.locator.return_value.first.count.return_value=0
    row={'video_id':'evalsong001','title':'Example Artist - Example Song','channel':'Example Artist','position':1}
    def player(_):
        if scenario=='player_failure':raise RuntimeError('controlled player failure')
        return {'exists':True,'video_id':'another0001' if scenario=='wrong_video' else row['video_id'],
            'time':clock.elapsed,'ready':3,'paused':False,'ad':scenario=='advertisement','volume':.3,'muted':False,'title':row['title']}
    with patch('core.youtube_control.time',SimpleNamespace(monotonic=lambda:clock.elapsed,time=time.time)),patch('core.youtube_control._candidates',return_value=[row]),patch('core.youtube_control.player_state',side_effect=player):
        result=play_youtube(page,'Example Song Example Artist',select_result=lambda *args:{'accepted':True,'candidate_id':row['video_id']},goal={'task_id':'eval-contract'})
    expected=scenario=='playing'
    return {'passed':bool(result.get('verified'))==expected and len(navigations)==2 and result.get('stage') not in ('no_results','no_matching_result'),
        'scenario':scenario,'outcome':result.get('stage'),'verified':result.get('verified'),'search_count':sum('/results?' in url for url in navigations),
        'player_is_mocked':True,'browser_is_mocked':True}


async def feedback_probe(scenario):
    import tempfile
    from unittest.mock import AsyncMock,patch
    from core.assistant_service import AssistantService
    from core.task_store import TaskStore
    from core.audio_manager import audio_manager
    messages={'success':'Senhor, reprodução confirmada.','failure':'Senhor, o vídeo abriu, mas a reprodução falhou.',
        'clarification':'Senhor, qual artista deseja ouvir?','output_failure':'Senhor, reprodução confirmada.'}
    with tempfile.TemporaryDirectory() as folder:
        service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db');service.store.create('eval','evaluation',messages[scenario])
        reply={'state':'failed','delivered':False,'error':'controlled disconnected output'} if scenario=='output_failure' else {'state':'completed','delivered':True}
        with patch('core.assistant_service.settings',return_value={'speech_enabled':True}),patch.object(audio_manager,'speak',return_value=reply) as speak:
            await service.finish('eval','failed' if scenario=='failure' else 'completed',messages[scenario]);await service.finish('eval','completed','Duplicate')
        trace=service.store.get('eval')['input'];delivered=trace['final_feedback']['delivered']
        return {'passed':speak.call_count==1 and delivered==(scenario!='output_failure'),
            'spoken_text':speak.call_args.args[0],'deliveries':speak.call_count,'reported_delivered':delivered,
            'speech_is_mocked':True,'voice_quality_evaluated':False}


async def evaluate_recordings(report,path,manifest,suite,splits,add):
    from core.audio_manager import AudioManager
    from core.config import settings
    audio=AudioManager();cases={row['id']:row for split in splits for row in suite[split]['cases']}
    records=json.loads(Path(manifest).read_text(encoding='utf-8'))['recordings'] if manifest and Path(manifest).is_file() else []
    relevant=[row for row in records if row['case_id'] in cases]
    if not relevant:
        report['results'].append({'id':'recordings','split':'audio','stage':'transcription','environment':'not_executed',
            'status':'blocked','reason':'Nenhuma gravação com referência disponível para a divisão escolhida.'});write_report(report,path);return
    for record in relevant:
        case=cases[record['case_id']];split=next(s for s in splits if case in suite[s]['cases'])
        async def transcribe():
            if settings()['stt_provider']!='whisper-local':raise RuntimeError('Selecione Whisper local; a avaliação não muda o provedor.')
            if record.get('reference_status')!='confirmed':raise RuntimeError('Referência humana ainda não confirmada.')
            import soundfile as sf
            location=(Path(manifest).parent/record['path']).resolve()
            if digest(location)!=record['sha256']:raise RuntimeError('A gravação mudou desde a anotação.')
            waveform,rate=sf.read(location,dtype='float32',always_2d=True)
            # Never pass the expected answer/reference as recognition vocabulary.
            hypothesis=audio.transcribe_audio(waveform.mean(axis=1),rate,vocabulary=record.get('observed_context','')) or ''
            metrics=recognition_metrics(record['reference'],hypothesis,case['queries'])
            return {'passed':metrics['wer']<=.2 and (metrics['content_token_recall'] is None or metrics['content_token_recall']==1),
                'reference':record['reference'],'hypothesis':hypothesis,'metrics':metrics,'recognition':audio.last_capture.get('recognition'),
                'audio_sha256':record['sha256'],'source':record['source'],'microphone':record.get('microphone'),
                'recording_id':record['id'],'thresholds':{'wer_max':.2,'content_token_recall_min':1.}}
        await add(case,split,'transcription','real_recording_cpu_stt' if record['source']=='human' else 'synthetic_recording_cpu_stt',transcribe)


def compare_reports(before,after):
    if before['snapshot']['dataset_hashes']!=after['snapshot']['dataset_hashes']:raise ValueError('O corpus mudou; os resultados não são diretamente comparáveis.')
    if before['snapshot']['model_manifests']!=after['snapshot']['model_manifests'] or before['snapshot']['model']!=after['snapshot']['model']:
        raise ValueError('O modelo mudou; esta comparação exige o mesmo modelo.')
    if before.get('recordings_manifest_hash')!=after.get('recordings_manifest_hash'):raise ValueError('As gravações ou referências mudaram entre as passagens.')
    keys=lambda report:{(r['split'],r['stage'],r['environment'],r['id']) for r in report['results']}
    if keys(before)!=keys(after):raise ValueError('As passagens não cobrem os mesmos casos/etapas. Não compare uma execução parcial como completa.')
    def index(report):return {(r['split'],r['stage'],r['environment']):r for r in summarize(report['results'])}
    left=index(before);right=index(after);rows=[]
    for key in sorted(left.keys()|right.keys()):
        a=left.get(key,{});b=right.get(key,{})
        rows.append({'split':key[0],'stage':key[1],'environment':key[2],
            'before':a,'after':b,'delta_pass_rate':b['pass_rate']-a['pass_rate'] if a.get('pass_rate') is not None and b.get('pass_rate') is not None else None})
    return {'same_model':True,'same_dataset':True,'training_performed':False,'stages':rows,
        'changed_sources':[name for name,value in before['snapshot']['code_hashes'].items() if after['snapshot']['code_hashes'].get(name)!=value]}
