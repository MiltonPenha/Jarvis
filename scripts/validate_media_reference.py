"""Real CPU inference with controlled result lists. No browser, mic or speech.

The private model worker must be free (stop the idle backend before running).
This script owns its worker and always stops it; it never attaches to another one.
"""
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.config import config
from core.local_model import local_model,MODEL
from core.music_intent import interpret
from core.music_followup import candidate_rows


async def main():
    rows=candidate_rows([
        {'video_id':'gbS7o0F8eNs','title':'TAUZ - MADARA | DROP NOSTALGICZ','channel':'Tauz','position':2},
        {'video_id':'ZbZSe6N_BXs','title':'Pharrell Williams - Happy (Official Video)','channel':'Pharrell Williams','position':1}])
    async def run():
        cases=[
          ('problem','Quero que você toque exatamente essa mídia que você encontrou.','presented','play_existing','gbS7o0F8eNs'),
          ('short','Toque essa.','presented','play_existing','gbS7o0F8eNs'),
          ('found','Pode tocar a que você encontrou.','presented','play_existing','gbS7o0F8eNs'),
          ('title_ack','É essa mesmo.','presented','confirm_title','gbS7o0F8eNs'),
          ('insistent','Mesmo assim, toque essa.','presented','play_existing','gbS7o0F8eNs'),
          ('first','Toque a primeira dessas opções.','list','select_position','ZbZSe6N_BXs'),
          ('second','Reproduza a segunda opção.','list','select_position','gbS7o0F8eNs'),
          ('artist','Toque a do TAUZ.','list','play_existing','gbS7o0F8eNs'),
          ('ambiguous','Toque essa.','list','clarify',''),
          ('new','Agora toque a música Essa Menina.','presented','search_and_play','Essa Menina'),
          ('literal','Toque a música "Essa mídia que você encontrou".','presented','search_and_play','Essa mídia que você encontrou'),
          ('absent','Reproduza exatamente essa mídia.','empty','clarify',''),
          ('reproduce','Reproduza exatamente essa mídia que você encontrou.','presented','play_existing','gbS7o0F8eNs'),
          ('reproduce_three','Reproduza exatamente essa mídia que você encontrou.','three','play_existing','gbS7o0F8eNs'),
        ]
        report={'model':MODEL,'real_inference':True,'controlled_context':True,'real_browser':False,'cases':[]}
        output=config.DATA_DIR/'validation/media-reference-model.json';output.parent.mkdir(parents=True,exist_ok=True)
        for name,text,mode,expected,target in cases:
            candidates=candidate_rows([{'video_id':'gbS7o0F8eNs','title':'TAUZ - MADARA | 15/31 | DROP NOSTALGICZ','channel':'Tauz','position':1},
                {'video_id':'ziJdf7bCQzI','title':'Rap do Madara (Naruto) | Tauz RapTributo 11','channel':'Nerd Raps','position':2},
                {'video_id':'LVMHYzVS9Y4','title':'Rap do Minecraft | Tauz RapGame 06','channel':'Tauz','position':3}]) if mode=='three' else rows
            snapshot={'id':'observed-list','source_task_id':'source','created_at':time.time(),'query':'rap uma dara',
                'candidates':candidates if mode!='empty' else [],'presented_candidate_id':'gbS7o0F8eNs' if mode in ('presented','three') else '',
                'selected_candidate_id':'','pending_confirmation':{'state':'pending','question_kind':'title_hypothesis'}}
            context={'music_goal':{'query':'rap uma dara','result_set':snapshot}}
            result=await interpret(text,context)
            operation=result.get('action');accepted=result.get('accepted',False)
            passed=(not accepted and not result.get('query') and result.get('reason')!='model_unavailable') if expected=='clarify' else (
                accepted and operation==expected and (result.get('query') if expected=='search_and_play' else result.get('candidate_id'))==target)
            record={'case':name,'request':text,'expected':expected,'passed':bool(passed),'result':result}
            report['cases'].append(record);report['passed']=all(row['passed'] for row in report['cases'])
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'case':name,'passed':bool(passed),'action':operation,'accepted':accepted,
                'reason':result.get('reason'),'candidate':result.get('candidate_id'),'query':result.get('query'),
                'seconds':result.get('model_usage',{}).get('seconds')},ensure_ascii=True),flush=True)
        return report['passed']
    try:return await run()
    finally:await asyncio.to_thread(local_model.stop)


if __name__=='__main__':sys.exit(0 if asyncio.run(main()) else 1)
