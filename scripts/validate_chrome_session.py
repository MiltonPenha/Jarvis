"""Live, audible validation through the running JARVIS and authorized Chrome.

Reuses the HUD conversation when available, restores voice/volume settings,
leaves the last requested music playing, and never closes personal tabs.
"""
import json
import argparse
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from core.chrome_session import connection_status
from core.config import config


def main():
    # Use only the production controller. A second diagnostic CDP connection
    # would trigger an unnecessary Chrome permission request.
    parser=argparse.ArgumentParser();parser.add_argument('--session',default='chrome-live-validation')
    session=parser.parse_args().session
    report={'session':session,'commands':[],'connection':None}
    destination=config.DATA_DIR/'chrome-session-validation.json'
    def save():destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with httpx.Client(base_url=f'http://127.0.0.1:{config.PORT}',trust_env=False,timeout=35) as c:
        for attempt in range(50):
            try:c.get('/').raise_for_status();break
            except httpx.ConnectError:
                if attempt==49:raise
                time.sleep(.2)
        assert not any(t['state'] in ('running','queued','cancelling') for t in c.get('/api/tasks').json()['tasks']), 'Tarefa ativa'
        previous=c.get('/api/settings').json()
        original_volume=None;tab=None
        def command(text):
            nonlocal tab
            identifier='chrome-probe-'+uuid.uuid4().hex
            started=time.monotonic()
            c.post('/api/command',json={'id':identifier,'session':session,'command':text}).raise_for_status()
            deadline=time.monotonic()+125
            while time.monotonic()<deadline:
                task=c.get('/api/tasks/'+identifier).json()
                if task['state'] in ('completed','failed','cancelled'):break
                time.sleep(.2)
            results=[json.loads(row['result']) for row in task['tools'] if row.get('result')]
            results=[{key:value for key,value in result.items() if key!='elements'} for result in results]
            row={'command':text,'state':task['state'],'seconds':round(time.monotonic()-started,2),'usage':task['usage'],'tools':results}
            report['commands'].append(row);save()
            print(json.dumps(row,ensure_ascii=True),flush=True)
            assert task['state']=='completed',task.get('error')
            assert results and all(result.get('verified') is True for result in results),results
            assert task['usage']['api_calls']==0
            assert len(results)==(3 if text.startswith('Boa noite') else 1), 'Uma ordem simples gerou efeitos adicionais'
            media=[result for result in results if result.get('tool') in ('play_music','media','volume')]
            for result in media:
                if tab is None:tab=result['tab_id']
                assert result['tab_id']==tab, 'Controle mudou de aba'
                if result.get('tool')=='play_music':assert result.get('youtube_authenticated') is True and result.get('playback_confirmed') is True
            return results[-1]
        try:
            c.post('/api/settings',json={'speech_enabled':False}).raise_for_status()
            connection=c.post('/api/browser/connect',json={});connection.raise_for_status()
            report['connection']=connection.json();save()
            command("Boa noite, Javis. Abra o Google, entra no YouTube e toque uma música do Guns N' Roses.")
            first=command('Qual música está tocando?');original_volume=first['volume_percent']
            command('Pause.');command('Continue.')
            command('Coloque o volume em 30%');command('Aumente o volume');command('Diminua o volume')
            next_track=command('Próxima música')
            assert next_track['video_id']!=first['state']['video_id'], 'Próxima repetiu o vídeo'
            command('Toque outra do mesmo artista')
            command('Toque Bohemian Rhapsody Queen')
            command('Agora coloque uma música do Daft Punk')
            command("Toque uma música do Guns N' Roses")
            command(f'Coloque o volume em {original_volume}%')
            final=command('Qual música está tocando?')
            assert not final['state']['paused'] and not final['state']['ad'] and not final['state']['error']
            report['passed']=True;report['controlled_tab']=tab;save()
        finally:
            if original_volume is not None and not report.get('passed'):
                try:command(f'Coloque o volume em {original_volume}%')
                except Exception:pass
            c.post('/api/settings',json={'speech_enabled':previous['speech_enabled']}).raise_for_status()
            save()
    print('Live Chrome session verified; report: '+str(destination),flush=True)


if __name__=='__main__':main()
