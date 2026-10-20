"""Reusable music evaluation. See docs/MUSIC_EVALUATION.md for provenance and limits."""
import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import socket
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.music_evaluation import DATA,load_suite,runtime_snapshot,write_report,evaluate_offline,compare_reports,digest
from core.config import config


def server_running():
    with socket.socket() as connection:
        connection.settimeout(.5);return connection.connect_ex(('127.0.0.1',config.PORT))==0


def offline_only():
    if server_running():raise SystemExit('Encerre somente o backend ocioso do JARVIS antes do ensaio offline; o runtime privado não será compartilhado nem duplicado. Veja a documentação.')


async def run(options):
    offline_only()
    from core.local_model import local_model
    suite=load_suite();splits=['development','holdout'] if options.split=='all' else [options.split]
    modes=options.modes.split(',')
    if not set(modes)<={'text','selection','contracts','stt'}:raise SystemExit('Modo de avaliação desconhecido.')
    if options.phase=='before' and 'holdout' in splits and not options.seal_holdout:raise SystemExit('Use --seal-holdout na linha de base para não orientar ajustes pela reserva.')
    report={'schema_version':1,'run_id':uuid.uuid4().hex,'phase':options.phase,'created_at':datetime.now(timezone.utc).isoformat(),
        'snapshot':runtime_snapshot(),'sealed_holdout':options.seal_holdout,'results':[],
        'recordings_manifest_hash':digest(options.recordings) if options.recordings and options.recordings.is_file() else None,
        'provenance':{'real_microphone_capture':False,'browser_executed':False,'candidate_rows':'fixtures',
            'playback':'simulated player observations','feedback':'simulated audio delivery','text_and_selection_model':'real local CPU',
            'audio_replay':bool(options.recordings),'weights_modified':False}}
    if options.output.exists():raise SystemExit('O relatório já existe. Escolha outro caminho; linhas de base não são sobrescritas.')
    started=time.monotonic();write_report(report,options.output)
    try:await evaluate_offline(report,options.output,suite,splits,modes,options.recordings,options.seal_holdout)
    finally:
        local_model.stop();report['seconds']=round(time.monotonic()-started,3);report['snapshot_after']=runtime_snapshot()
        report['weights_unchanged']=report['snapshot']['model_manifests']==report['snapshot_after']['model_manifests']
        write_report(report,options.output)
    visible=[r for r in report['summary'] if r['split']!='holdout' or not options.seal_holdout]
    print(json.dumps({'summary':visible,'report':str(options.output),'weights_unchanged':report['weights_unchanged']},ensure_ascii=True),flush=True)
    return 1 if any(r['status']=='failed' for r in report['results'] if r['split']!='holdout' or not options.seal_holdout) else 2 if any(r['status']=='blocked' for r in report['results']) else 0


def record(options):
    offline_only()
    import soundfile as sf
    import winsound
    from core.audio_manager import AudioManager
    suite=load_suite();case=next((c for s in suite.values() for c in s['cases'] if c['id']==options.case),None)
    if not case:raise SystemExit('Caso desconhecido.')
    folder=options.manifest.parent.resolve();folder.mkdir(parents=True,exist_ok=True)
    data=json.loads(options.manifest.read_text(encoding='utf-8')) if options.manifest.is_file() else {'version':1,'recordings':[]}
    audio=AudioManager()
    print(json.dumps({'case':case['id'],'read_after_beep':case['request'],'reference_status':'unverified'},ensure_ascii=True),flush=True)
    def state(value):
        if value=='LISTENING':
            print('LISTENING - fale agora',flush=True);winsound.Beep(880,120)
    audio.on_state_change=state
    waveform=audio.record_phrase(max_seconds=16,silence_limit=1.5)
    if waveform is None:raise SystemExit('Nenhuma fala capturada. Nenhuma gravação adicionada.')
    identifier=uuid.uuid4().hex;path=folder/(identifier+'.wav')
    sf.write(path,waveform,audio.last_capture['sample_rate'],subtype='PCM_16')
    entry={'id':identifier,'case_id':case['id'],'source':'human','speaker':options.speaker,'path':path.name,'sha256':digest(path),
        'reference':case['request'],'reference_status':'unverified','observed_context':'',
        'microphone':audio.last_capture,'created_at':datetime.now(timezone.utc).isoformat()}
    data['recordings'].append(entry);options.manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'saved':str(path),'recording_id':identifier,'diagnostics':audio.last_capture,'reference_confirmation_required':True},ensure_ascii=True),flush=True)


def confirm(options):
    data=json.loads(options.manifest.read_text(encoding='utf-8'))
    matches=[r for r in data['recordings'] if r['id'] in options.ids]
    if len(matches)!=len(set(options.ids)):raise SystemExit('Uma das gravações não foi encontrada.')
    if options.reference and len(matches)!=1:raise SystemExit('Uma referência corrigida exige uma única gravação.')
    for row in matches:
        if options.reference:row['reference']=options.reference
        row.update(reference_status='confirmed',reference_confirmed_by=options.confirmed_by,
            reference_confirmed_at=datetime.now(timezone.utc).isoformat())
    options.manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Referências confirmadas:',len(matches))


def compare(options):
    before=json.loads(options.before.read_text(encoding='utf-8'));after=json.loads(options.after.read_text(encoding='utf-8'))
    result=compare_reports(before,after)
    result.update(before_report=str(options.before),after_report=str(options.after),
        holdout_policy='Reserved results are inspected after freezing runtime adjustments. Inspecting individual failures retires this version for future tuning.')
    options.output.parent.mkdir(parents=True,exist_ok=True)
    if options.output.exists():raise SystemExit('A comparação já existe. Escolha outro caminho.')
    options.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for stage in result['stages']:
        print(json.dumps({'split':stage['split'],'stage':stage['stage'],'environment':stage['environment'],
            'before':stage['before'].get('counts'),'after':stage['after'].get('counts')},ensure_ascii=True))


def live(options):
    import subprocess
    if options.output.exists():raise SystemExit('O relatório já existe.')
    raw=options.output.with_name(options.output.stem+'-raw.json')
    snapshot=runtime_snapshot()
    call=subprocess.run([sys.executable,str(config.BASE_DIR/'scripts/validate_music_request.py'),'--scenario','evaluation',
        '--session',options.session,'--voice','--report',str(raw)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    data=json.loads(raw.read_text(encoding='utf-8')) if raw.exists() else {'commands':[],'passed':False}
    report={'schema_version':1,'phase':options.phase,'snapshot':snapshot,'results':[],
        'provenance':{'real_browser':True,'real_cpu_model':True,'real_microphone_capture':False,'raw_report':str(raw),'process_exit':call.returncode}}
    cases=json.loads((DATA/'integration.json').read_text(encoding='utf-8'))['cases']
    from core.music_evaluation import query_matches,tokens
    for case in cases:
        command=next((r for r in data['commands'] if r['request']==case['request']),None)
        if not command:
            for stage in ('intent','query','selection','playback','feedback'):
                report['results'].append({'id':case['id'],'split':'integration','stage':stage,'environment':'real_youtube',
                    'status':'blocked','reason':'A bateria não alcançou este pedido.'})
            continue
        trace=command['input'];music=next((r for r in command['results'] if r.get('tool')=='play_music'),{})
        candidate=music.get('selected_candidate',{});observed=set(tokens(candidate.get('title','')+' '+candidate.get('channel','')))
        content_ok=set(tokens(case['content']))-{'de','do','da','dos','das'} <= observed
        checks={'intent':bool(trace.get('music_intent',{}).get('accepted')),
            'query':query_matches(trace.get('final_search_query',''),[case['content']]) and len(trace.get('music_search_queries',[]))==1,
            'selection':bool(music.get('music_selection',{}).get('decision',{}).get('accepted')) and content_ok,
            'playback':bool(music.get('verified') and music.get('playback_confirmed') and music.get('video_id')==candidate.get('video_id')),
            'feedback':bool(trace.get('final_feedback',{}).get('delivered'))}
        for stage,passed in checks.items():
            report['results'].append({'id':case['id'],'split':'integration','stage':stage,'environment':'real_youtube',
                'status':'skipped' if stage=='feedback' and not case['speech'] else 'passed' if passed else 'failed',
                'task_id':command['task'],'seconds':command['usage'].get('speech_seconds',0) if stage=='feedback' else command['usage'].get('total_seconds',0),
                'video_id':music.get('video_id'),'query':trace.get('final_search_query'),
                'speech':trace.get('speech_result') if stage=='feedback' else None})
    report['passed']=data.get('passed',False) and not any(r['status'] in ('failed','blocked') for r in report['results'])
    write_report(report,options.output);print('Live report:',options.output)
    return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    offline=sub.add_parser('run');offline.add_argument('--phase',choices=['before','after'],required=True);offline.add_argument('--split',choices=['development','holdout','all'],default='development')
    offline.add_argument('--modes',default='text,selection,contracts,stt');offline.add_argument('--seal-holdout',action='store_true');offline.add_argument('--recordings',type=Path);offline.add_argument('--output',type=Path,required=True)
    capture=sub.add_parser('record');capture.add_argument('--case',required=True);capture.add_argument('--speaker',default='user');capture.add_argument('--manifest',type=Path,default=config.DATA_DIR/'evaluation/music/recordings/manifest.json')
    annotate=sub.add_parser('confirm-reference');annotate.add_argument('--manifest',type=Path,required=True);annotate.add_argument('--ids',nargs='+',required=True);annotate.add_argument('--reference');annotate.add_argument('--confirmed-by',required=True)
    comparison=sub.add_parser('compare');comparison.add_argument('--before',type=Path,required=True);comparison.add_argument('--after',type=Path,required=True);comparison.add_argument('--output',type=Path,required=True)
    integration=sub.add_parser('live');integration.add_argument('--phase',choices=['before','after'],required=True);integration.add_argument('--session',required=True);integration.add_argument('--output',type=Path,required=True)
    options=parser.parse_args()
    if options.command=='run':raise SystemExit(asyncio.run(run(options)))
    if options.command=='record':record(options)
    if options.command=='confirm-reference':confirm(options)
    if options.command=='compare':compare(options)
    if options.command=='live':raise SystemExit(live(options))


if __name__=='__main__':main()
