"""Real CPU inference with labelled page-data fixtures, not a live YouTube claim."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.youtube_suggestions import choose,local_model
from core.config import config


def row(video,title,channel,position):
    return {'id':video,'video_id':video,'url':'https://www.youtube.com/watch?v='+video,'title':title,'channel':channel,'position':position}


async def main():
    snap={'current':{'video_id':'current0001','title':'NX Zero - Razões e Emoções','channel':'Universal Music','artists':[]},
        'recommendations':[row('queen000001','Queen - Somebody To Love','Queen Official',1),
            row('nxzero00001','NX Zero - Cedo ou Tarde (Clipe Oficial)','Universal Music',2),
            row('nxzero00002','NX Zero - Além de Mim (Audio Oficial)','Outra Gravadora',3)]}
    report={'passed':False,'real_cpu_inference':True,'page_data_are_fixtures':True,'cases':[]}
    try:
        for request,expected in [('Toque a primeira sugestão','queen000001'),('Outra deles','nxzero00001'),
            ('Coloque outra do NX Zero pelas sugestões','nxzero00001')]:
            result=await choose(request,snap,{'media_query':'Razões e Emoções do NX Zero'})
            report['cases'].append({'request':request,'result':result});print(json.dumps(report['cases'][-1],ensure_ascii=True),flush=True)
            assert result.get('accepted') and result.get('candidate_id')==expected,result
            assert result['model_usage']['vram_bytes']==0
        snap['recommendations']=snap['recommendations'][:1]
        result=await choose('Mais uma dessa banda',snap,{})
        report['cases'].append({'request':'Mais uma dessa banda sem correspondente','result':result})
        assert not result.get('accepted'),result
        report['passed']=True
    finally:
        local_model.stop()
        (config.DATA_DIR/'suggestions-model-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':asyncio.run(main())
