"""Local HUD rendering and interaction regression; task/media events are fixtures.

No microphone, synthesis, personal Chrome session, application or media effects.
"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.config import config
from playwright.sync_api import sync_playwright,expect

def geometry(page):
    return page.evaluate("""Object.fromEntries(['.system-strip','.center-stage','.arc-reactor-wrapper','.content-feedback','.terminal-panel'].map(s=>{const r=document.querySelector(s).getBoundingClientRect();return [s,{width:r.width,height:r.height,x:r.x,y:r.y}]}))""")

def main():
    root=config.DATA_DIR/'validation/layout-reorganization';output=root/'after';output.mkdir(parents=True,exist_ok=True)
    results=[];errors=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='chrome',headless=True)
        for width,height in [(1440,900),(1280,720),(1000,800),(390,844)]:
            context=browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce')
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{config.PORT}')
            expect(page.locator('#status-text')).to_have_text('PRONTO',timeout=15000)
            page.evaluate('clearInterval(jarvis.poll);jarvis.reconcile=async()=>{};')
            page.wait_for_function('!jarvis.reconciling')
            page.wait_for_function('window.jarvis.settings')
            expect(page.locator('#system-details')).not_to_have_attribute('open','')
            expect(page.locator('[data-action="music"]')).not_to_be_visible()
            expect(page.locator('#task-content')).not_to_have_attribute('open','')
            initial=geometry(page)
            assert initial['.system-strip']['height']<110
            assert initial['.content-feedback']['height']<90
            page.screenshot(path=str(output/f'{width}-idle.png'),full_page=True)
            for index,state in enumerate(['LISTENING','PROCESSING','EXECUTING','COMPLETED','FAILED','WAITING']):
                page.evaluate("""({state,index})=>{
                  jarvis.activeTask='layout-'+index;
                  const send=event=>jarvis.message({...event,session:jarvis.session,task_id:jarvis.activeTask});
                  send({type:'user_command',text:'Teste visual — dados simulados ('+state+'): reproduza a música selecionada.'});
                  send({type:'state',state});
                  if(state==='LISTENING')send({type:'transcription',text:'Teste visual — transcrição parcial',final:false});
                  if(['EXECUTING','COMPLETED','FAILED','WAITING'].includes(state)) {
                    send({type:'progress',data:{message:'Etapa do ensaio de interface.'},presentation:{stage:state==='COMPLETED'?'confirmed':state==='EXECUTING'?'opening':state==='WAITING'?'awaiting_choice':'unconfirmed',title:'Pharrell Williams — Happy (resultado simulado)',channel:'Informação controlada para testar o layout'}});
                    send({type:'jarvis_response',response:state==='COMPLETED'?'Resposta de sucesso simulada.':state==='FAILED'?'Não consegui confirmar a execução.':state==='WAITING'?'Senhor, qual versão prefere?':'Abrindo o conteúdo selecionado.'});
                  }
                }""",{'state':state,'index':index})
                assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth'),(width,state)
                assert page.locator('#status-text').inner_text()
                expect(page.locator('.current-request')).not_to_be_visible()
                page.locator('#cmd-input').scroll_into_view_if_needed()
                assert page.locator('#send-cmd-btn').is_visible()
                assert page.evaluate("document.querySelector('#send-cmd-btn').getBoundingClientRect().right<=document.querySelector('#command-form').getBoundingClientRect().right")
                page.screenshot(path=str(output/f'{width}-{state.lower()}.png'),full_page=True)
                results.append({'viewport':[width,height],'state':state,'passed':True})
            # Native disclosures: user choices survive metric and content updates.
            page.locator('#system-details summary').click()
            page.locator('#quick-actions summary').click()
            expect(page.locator('#cpu-sub')).to_be_visible()
            expect(page.locator('[data-action="music"]')).to_be_visible()
            assert page.evaluate("""()=>{
              const cpu=document.querySelector('#cpu-val'),request=document.querySelector('#recognized-request');
              jarvis.updateTelemetry({cpu_percent:47,ram_percent:63,disk_percent:75,cpu_cores:16,cpu_ghz:3.7,ram_used_gb:20,ram_total_gb:32,disk_free_gb:100,disk_total_gb:400,uptime:'2h',hostname:'Estação de teste'});
              return cpu===document.querySelector('#cpu-val')&&request===document.querySelector('#recognized-request')&&document.querySelector('#system-details').open&&document.querySelector('#quick-actions').open;
            }""")
            page.screenshot(path=str(output/f'{width}-auxiliaries.png'),full_page=True)
            page.locator('#cmd-input').scroll_into_view_if_needed()
            assert page.locator('#cmd-input').bounding_box()['y']+page.locator('#cmd-input').bounding_box()['height']<=height
            # Capture shortcut dispatch; reject effects by replacing only the
            # action boundary on this isolated test page.
            page.evaluate("""()=>{
              window.shortcutCalls=[];window.savedApi=jarvis.api;window.savedCommand=jarvis.sendCommand;
              jarvis.api=async(path,body)=>{if(path==='actions'){shortcutCalls.push(body.action);return {id:'shortcut-fixture',state:'completed'};}return savedApi.call(jarvis,path,body);};
              jarvis.sendCommand=async text=>shortcutCalls.push(text);
            }""")
            for button in page.locator('#quick-actions button').all():button.click()
            calls=page.evaluate('shortcutCalls')
            assert calls==['status','music','browser','pesquisar sobre novidades de inteligência artificial','vault','screenshot','macro:modo trabalho'],calls
            page.evaluate('()=>{jarvis.api=savedApi;jarvis.sendCommand=savedCommand;}')
            page.locator('#system-details summary').click();page.locator('#quick-actions summary').click()
            page.evaluate("jarvis.showContent({stage:'selected',title:'Resultado com título longo. '.repeat(20),channel:'Detalhes da seleção'});")
            page.locator('#task-content summary').click()  # collapse
            page.evaluate("jarvis.showContent({stage:'confirmed',title:'Título atualizado do mesmo conteúdo',channel:'Detalhes da seleção'});")
            assert not page.locator('#task-content').evaluate('(element)=>element.open')
            page.locator('#task-content summary').click()  # expand
            expect(page.locator('#content-channel')).to_be_visible()
            page.screenshot(path=str(output/f'{width}-content-expanded.png'),full_page=True)
            context.close()
            if width==1440:(output/'metrics.json').write_text(json.dumps(initial,indent=2))
        browser.close()
    assert not errors,errors
    before=json.loads((root/'before/metrics.json').read_text()) if (root/'before/metrics.json').is_file() else None
    report={'passed':True,'rendering':'real isolated headless Chrome','task_events':'simulated','real_actions_executed':False,
            'states':results,'shortcuts_checked':7,'errors':errors,'before':before,'after':json.loads((output/'metrics.json').read_text())}
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'state_viewport_checks':len(results),'shortcuts_checked':7,'errors':errors}))

if __name__=='__main__':main()
