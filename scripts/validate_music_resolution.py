"""Real CPU inference on labelled candidate fixtures; no browser/playback claim."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.music_resolution import resolve,local_model
from core.config import config


async def main():
    report={'candidates_are_fixtures':True,'real_cpu_inference':True,'passed':False,'cases':[]}
    cases=[('Gunner Rose',"Guns N' Roses",['Welcome To The Jungle','Paradise City','Patience']),
           ('Lincoln Park','Linkin Park',['Numb','In The End','Faint']),
           ('Dancing Elephants',"Guns N' Roses",['Patience','Paradise City','November Rain'])]
    try:
        for query,artist,titles in cases:
            result=await resolve(query,[{'channel':artist,'title':title} for title in titles])
            report['cases'].append({'query':query,'result':result})
            print(json.dumps(report['cases'][-1],ensure_ascii=True),flush=True)
        assert report['cases'][0]['result'].get('query')==cases[0][1],report
        assert not report['cases'][2]['result']['accepted'],report
        assert all(row['result'].get('model_usage',{}).get('vram_bytes',0)==0 for row in report['cases'])
        report['passed']=True
    finally:
        local_model.stop()
        (config.DATA_DIR/'music-resolution-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':asyncio.run(main())
