"""Real CPU extraction only: does not open a browser or capture a microphone."""
import asyncio
import json
from pathlib import Path
import sys
import argparse
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.music_intent import interpret,local_model
from core.config import config
from core.music_resolution import select_result
from core.music_resolution import terms

CASES=[('Toca pra mim a música TAUZ MADARA','TAUZ MADARA'),
 ('JARVIS, por favor, coloca TAUZ MADARA no YouTube','TAUZ MADARA'),
 ('Quero ouvir Razões e Emoções do NX Zero','Razões e Emoções NX Zero'),
 ('Boa tarde, JARVIS, consegue tocar uma música do Guns N’ Roses pra mim?','Guns N’ Roses'),
 ('Pesquisa por TAUZ MADARA e coloca pra tocar','TAUZ MADARA'),
 ('Toque a música “Pra Mim”','Pra Mim'),
 ('Boa noite, Javis. Toca pra mim a música TAUS MADARA.','TAUS MADARA'),
 ('Toque a música "Toca"','Toca'),
 ('Quero ouvir "Música Para Mim"','Música Para Mim'),
 ('Coloca a música "Outra Deles"','Outra Deles'),
 ('Quero ouvir Toca Pra Mim','Toca Pra Mim'),
 ('Toque a música Pra Mim','Pra Mim'),
 ('Toca pra mim uma música','')]
CASES.extend([('Toque Rap do Minecraft do TAUZ','Rap do Minecraft TAUZ'),
 ('Toca pra mim a música happy do Minecraft do Taus','happy do Minecraft do Taus')])

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--flow-only',action='store_true');options=parser.parse_args()
    report={'passed':False,'real_cpu_inference':True,'real_browser':False,'real_microphone':False,'cases':[]}
    path=config.DATA_DIR/('music-flow-model-validation.json' if options.flow_only else 'music-intent-model-validation.json')
    try:
        for source,expected in ([] if options.flow_only else CASES):
            result=await interpret(source,{})
            matched=result.get('query')==expected or 'Minecraft' in expected and terms(result.get('query',''))==terms(expected)
            case={'request':source,'expected':expected,'result':result,'passed':matched and bool(result.get('accepted'))==bool(expected)}
            report['cases'].append(case)
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(case,ensure_ascii=True),flush=True)
        previous={'accepted':True,'query':'happy do Minecraft do Taus','title':'happy do Minecraft','artist':'Taus'}
        for source,expected in [('É rap, não happy','rap do Minecraft do Taus'),('A música é do Minecraft','happy do Minecraft do Taus'),
            ('Não, eu disse Rap do Minecraft do TAUZ','Rap do Minecraft TAUZ')]:
            result=await interpret(source,{'music_goal':previous})
            passed=result.get('accepted') and terms(result.get('query',''))==terms(expected)
            report['cases'].append({'request':source,'expected':expected,'result':result,'passed':passed});print(json.dumps(report['cases'][-1],ensure_ascii=True),flush=True)
        rows=[{'video_id':'other000001','title':'Outro - Rap do Minecraft','channel':'Outro','position':1},
            {'video_id':'right000001','title':'Rap do Minecraft | Tauz RapGame 06 (Oficial)','channel':'TAUZ','position':2},
            {'video_id':'cover000001','title':'Rap do Minecraft Cover TAUZ','channel':'Cover','position':3}]
        result=await select_result(previous['query'],rows,previous)
        report['cases'].append({'request':'Choose observed Rap do Minecraft despite happy/Taus','result':result,'passed':result.get('accepted') and result.get('candidate_id')=='right000001'})
        print(json.dumps(report['cases'][-1],ensure_ascii=True),flush=True)
        source='Jarvis, toque rápido Minecraft do Tauz'
        extracted=await interpret(source,{})
        resolved=await select_result(extracted.get('query',''),rows,extracted) if extracted.get('accepted') else {}
        report['cases'].append({'request':source,'extraction':extracted,'result':resolved,
            'passed':extracted.get('accepted') and 'rápido' in extracted.get('query','') and resolved.get('accepted') and resolved.get('candidate_id')=='right000001'})
        print(json.dumps(report['cases'][-1],ensure_ascii=True),flush=True)
        report['passed']=all(case['passed'] for case in report['cases'])
    finally:
        local_model.stop();path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':asyncio.run(main())
