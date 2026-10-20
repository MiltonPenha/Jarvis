"""Isolated headless Chrome UI regression. Content/media events are fixtures.

Never connects to the user's Chrome profile, plays media, records, or saves settings.
"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.config import config
from playwright.sync_api import sync_playwright,expect

def main():
    output=config.DATA_DIR/'evaluation/voice-feedback';output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':900},reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{config.PORT}')
        expect(page.locator('#status-text')).to_have_text('PRONTO',timeout=15000)
        page.evaluate('clearInterval(jarvis.poll); jarvis.reconcile=async()=>{};')
        page.wait_for_function('!window.jarvis.reconciling',timeout=15000)
        # Stop test-page polling and deliver controlled events through the same
        # public websocket message reducer. No production task/effect is created.
        page.evaluate("""() => {
          clearInterval(jarvis.poll); jarvis.reconcile=async()=>{};
          jarvis.activeTask='hud-fixture';jarvis.finishedTasks.delete('hud-fixture');
          const send=event=>jarvis.message({...event,session:jarvis.session,task_id:'hud-fixture'});
          send({type:'user_command',text:'Teste de interface — dados simulados: Jarvis, toque Happy.'});
          send({type:'state',state:'EXECUTING'});
          send({type:'progress',data:{message:'Resultado observado no ensaio controlado.'},presentation:{stage:'selected',title:'Pharrell Williams — Happy',channel:'Artista observado no teste'}});
          send({type:'speech',data:{phase:'generating',chunk:1,chunks:2}});
          jarvis.showMedia({state:'paused',observed:true,exists:true,title:'Player simulado',volume:.47});
        }""")
        expect(page.locator('#content-phase')).to_have_text('Selecionado')
        expect(page.locator('#media-phase')).to_have_text('Pausada')
        expect(page.locator('#speech-phase')).to_have_text('Gerando áudio')
        page.screenshot(path=str(output/'hud-desktop.png'),full_page=True)
        page.evaluate("""() => {
          jarvis.message({type:'jarvis_response',task_id:'hud-fixture',session:jarvis.session,response:'Senhor, qual versão prefere?',meta:{outcome:'clarification'}});
          jarvis.message({type:'speech',task_id:'hud-fixture',session:jarvis.session,data:{phase:'completed'}});
          jarvis.message({type:'tool',task_id:'stale',session:jarvis.session,presentation:{stage:'confirmed',title:'STALE'}});
        }""")
        expect(page.locator('#request-phase')).to_have_text('AGUARDANDO INFORMAÇÃO')
        expect(page.locator('#content-title')).to_have_text('Pharrell Williams — Happy')
        expect(page.locator('#media-phase')).to_have_text('Pausada')
        page.set_viewport_size({'width':390,'height':844})
        page.locator('.request-feedback').scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
        assert page.evaluate("getComputedStyle(document.body).overflowY != 'hidden'")
        assert page.evaluate("document.querySelector('#send-cmd-btn').getBoundingClientRect().right <= document.querySelector('#command-form').getBoundingClientRect().right")
        page.screenshot(path=str(output/'hud-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1000,'height':800})
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
        page.screenshot(path=str(output/'hud-tablet.png'),full_page=True)
        page.get_by_role('button',name='CONFIGURAÇÕES',exact=True).click()
        expect(page.locator('#voice-preview')).to_be_visible()
        expect(page.locator('#setting-tts_provider')).to_have_value('qwen-local')
        page.screenshot(path=str(output/'hud-settings.png'),full_page=True)
        assert not errors,errors
        browser.close()
    report={'passed':True,'real_rendering':True,'events_are_fixtures':True,'personal_chrome_used':False,
            'viewport_sizes':[[1440,900],[390,844],[1000,800]],'page_errors':errors}
    (output/'hud-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
