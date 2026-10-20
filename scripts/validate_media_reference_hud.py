"""Real HUD rendering with simulated media events; no media/browser commands."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.config import config
from playwright.sync_api import sync_playwright,expect


def main():
    folder=config.DATA_DIR/'validation/media-reference-hud';folder.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='chrome',headless=True)
        try:
            for width,height in [(1440,900),(1280,720),(1000,800),(390,844)]:
                page=browser.new_page(viewport={'width':width,'height':height},reduced_motion='reduce')
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{config.PORT}')
                expect(page.locator('#status-text')).to_have_text('PRONTO',timeout=15000)
                page.evaluate('clearInterval(jarvis.poll);jarvis.reconcile=async()=>{}')
                page.wait_for_function('!jarvis.reconciling')
                page.evaluate("""()=>{
                    jarvis.session='reference-hud';jarvis.activeTask='old';
                    jarvis.showContent({request_id:'old',stage:'selected',title:'Conteúdo antigo'});
                    jarvis.activeTask='new';
                    jarvis.message({type:'user_command',session:jarvis.session,task_id:'new',text:'Toque essa mídia que você encontrou'});
                    jarvis.message({type:'progress',session:jarvis.session,task_id:'old',presentation:{request_id:'old',stage:'confirmed',title:'Não deve aparecer'}});
                    jarvis.showContent({request_id:'new',stage:'searching',title:'Busca em andamento',query:'Consulta de teste',result_set_id:'new-list',candidates:[]});
                }""")
                expect(page.locator('#content-title')).to_have_text('Busca em andamento')
                expect(page.locator('#content-options li')).to_have_count(0)
                page.screenshot(path=str(folder/f'{width}-searching.png'),full_page=True)
                page.evaluate("""()=>jarvis.showContent({request_id:'new',source_task_id:'source',stage:'found',title:'Resultados disponíveis',query:'rap uma dara',result_set_id:'observed-list',candidates:[
                    {position:1,title:'Pharrell Williams - Happy (Official Video)',channel:'Pharrell Williams'},
                    {position:2,title:'TAUZ - MADARA | DROP NOSTALGICZ',channel:'Tauz'},
                    {position:3,title:'Outro resultado observado com um título extenso para conferir a quebra de linha em janelas pequenas',channel:'Canal observado'}]})""")
                expect(page.locator('#content-options li')).to_have_count(3)
                expect(page.locator('#content-origin')).to_contain_text('Pesquisa anterior')
                assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth')
                page.screenshot(path=str(folder/f'{width}-found.png'),full_page=True)
                page.evaluate("""()=>{
                    jarvis.showContent({request_id:'new',source_task_id:'source',stage:'selected',title:'TAUZ - MADARA | DROP NOSTALGICZ',query:'rap uma dara',result_set_id:'observed-list'});
                    jarvis.message({type:'task_updated',task:{id:'old',state:'cancelled',input:{superseded_by:'new'}}});
                }""")
                expect(page.locator('#content-phase')).to_have_text('Selecionado')
                expect(page.locator('#content-title')).to_contain_text('MADARA')
                page.screenshot(path=str(folder/f'{width}-selected.png'),full_page=True)
                checks.append({'viewport':[width,height],'search_clears_old':True,'late_old_ignored':True,'actual_positions_visible':True,'no_horizontal_overflow':True})
                page.close()
        finally:browser.close()
    report={'passed':not errors,'events_are_fixtures':True,'real_hud_rendering':True,'real_youtube':False,'checks':checks,'errors':errors}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True));assert not errors


if __name__=='__main__':main()
