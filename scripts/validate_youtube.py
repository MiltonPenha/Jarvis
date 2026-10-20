"""Real search/playback in a muted hidden browser; closes only its own profile."""
import json
from pathlib import Path
import sys
import tempfile
import time
import asyncio
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.browser_control import BrowserControl
from core.youtube_control import player_state
from core.local_runtime import LocalRuntime
from core.task_store import TaskStore


def main():
    results={}
    with tempfile.TemporaryDirectory(prefix='jarvis-youtube-validation-') as folder:
        browser=BrowserControl(Path(folder),headless=True,mute_audio=True)
        try:
            results['google']=browser.execute('browser_open','google')['title']
            # Simulate the window being closed between two voice commands.
            browser.executor.submit(lambda:browser.context.close()).result(10)
            results['reopened_after_close']=browser.execute('browser_open','https://www.youtube.com')['title']
            started=time.monotonic()
            played=browser.execute('youtube_play','Guns and Roses')
            results['playback']={**played,'seconds':round(time.monotonic()-started,2)}
            if played.get('playback_confirmed'):
                first=browser.executor.submit(player_state,browser.page).result(5)
                time.sleep(2)
                last=browser.executor.submit(player_state,browser.page).result(5)
                results['progress_at_idle_seconds']=round(last['time']-first['time'],2)
                assert results['progress_at_idle_seconds']>.5, 'A mídia parou entre comandos.'
            async def sequence():
                store=TaskStore(Path(folder)/'sequence.sqlite3')
                command='Javis, abro o Google, entre no YouTube e toque uma música do Guns and Roses.'
                store.create('sequence','validation',command)
                async def event(value): pass
                with patch('core.basic_tools.browser_control',browser),patch('core.browser_control.browser_control',browser):
                    result=await LocalRuntime(store).run({'id':'sequence','command':command},event)
                effects=store.get('sequence')['tools']
                music=[json.loads(item['result']) for item in effects if item['name']=='play_music']
                assert result['usage']['local_model_calls']==0 and result['usage']['api_calls']==0
                assert music and music[0]['playback_confirmed'], result
                return {'response':result['response'],'usage':result['usage'],
                    'checkpoints':[{'action':item['name'],'state':item['state']} for item in effects]}
            results['full_sequence']=asyncio.run(sequence())
            import psutil
            flags=[arg for process in psutil.process_iter(['name','cmdline'])
                if process.info['name']=='chrome.exe' and any(str(browser.profile) in arg for arg in (process.info['cmdline'] or []))
                for arg in process.info['cmdline'] or [] if arg=='--no-sandbox']
            assert not flags, 'Chrome iniciado com sandbox desabilitado.'
            results['no_sandbox_flag_absent']=True
        finally:
            browser.close();browser.executor.shutdown(wait=True)
    from core.config import config
    (config.DATA_DIR/'youtube-validation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
