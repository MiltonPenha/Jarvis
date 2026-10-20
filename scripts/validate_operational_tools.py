"""Live CPU model, network and Chrome validation. No cloud calls or audible media.

Uses an isolated browser profile; never attaches personal Chrome/HUD windows.
Writes observations (not mock results) to .data/tools-validation.json.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.browser_control import BrowserControl
from core.local_runtime import LocalRuntime
from core.local_model import local_model
from core.task_store import TaskStore
from core.config import config
from core.system_audio import endpoint_volume
sys.stdout.reconfigure(encoding="utf-8")


async def validate_live(browser,folder):
    store=TaskStore(Path(folder)/'tasks.db');engine=LocalRuntime(store);results=[]
    async def event(value):pass
    async def run(command):
        identifier=str(len(results));store.create(identifier,'live-tools-validation',command)
        result=await engine.run({'id':identifier,'session':'live-tools-validation','command':command},event)
        effects=[{'action':row['name'],'state':row['state'],'result':json.loads(row['result']) if row['result'] else {}}
            for row in store.get(identifier)['tools']]
        record={'command':command,'result':result,'effects':effects};results.append(record)
        print(json.dumps(record,ensure_ascii=False),flush=True)
        assert not result.get('error'),result
        return record
    original=local_model.plan
    async def observed_plan(*args,**kwargs):
        result=await original(*args,**kwargs)
        print(json.dumps({'observed_model_plan':result},ensure_ascii=False),flush=True)
        return result
    with patch('core.browser_control.browser_control',browser),patch.object(local_model,'plan',observed_plan):
        # New wording goes to the real model; no dedicated task script/router.
        novel=await run('Visite o endereço https://example.com; em seguida mostre o texto da página')
        assert novel['result']['usage']['local_model_calls']==1,novel
        assert any(row['action']=='browser_open' for row in novel['effects']),novel
        sequence=await run('Boa noite, Javis. Abra o Google, entre no YouTube, toque uma música do Guns and Rolls.')
        assert [row['action'] for row in sequence['effects']]==['browser_open','browser_open','play_music'],sequence
        playback=sequence['effects'][-1]['result'];assert playback.get('playback_confirmed'),playback
        for command in ('Aumente um pouco o som.','Diminua para 30%.','Pause a música.','Continue.',
            'Passe para a próxima.','Qual música está tocando?','Volte para a faixa anterior.'):
            record=await run(command)
            assert record['result']['usage']['local_model_calls']==0,record
            assert record['effects'][-1]['result']['verified'],record
            if command.startswith('Diminua'):assert record['effects'][-1]['result']['volume_percent']==30
            if command.startswith('Passe'):assert record['effects'][-1]['result']['video_id']!=playback['video_id']
        await run('Abra https://example.com')
        record=await run('Pause a música')
        assert record['effects'][-1]['result']['state']['video_id']==playback['video_id']
        record=await run('Qual música está tocando?')
        assert record['effects'][-1]['result']['origin']=='https://www.youtube.com'
    before=endpoint_volume();changed=None
    try:
        # Reduce one percentage point, verify and restore the user's endpoint.
        changed=endpoint_volume('absolute',max(0,before['volume_percent']-1));assert changed['verified']
    finally:
        restored=endpoint_volume('absolute',before['volume_percent'])
        if before['muted']:restored=endpoint_volume('mute')
        assert restored['verified'] and restored['muted']==before['muted']
    return {'live':True,'cloud_api_calls':0,'model_last_metrics':local_model.last_metrics,
        'system_volume':{'before':before,'changed':changed,'restored':restored},'tasks':results}


def main():
    with tempfile.TemporaryDirectory(prefix='jarvis-live-tools-') as folder:
        browser=BrowserControl(Path(folder)/'browser',headless=True,mute_audio=True)
        try:results=asyncio.run(validate_live(browser,folder))
        finally:
            local_model.stop();browser.close();browser.executor.shutdown(wait=True)
    output=config.DATA_DIR/'tools-validation.json'
    output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Validação real concluída: '+str(output))


if __name__=='__main__':main()
