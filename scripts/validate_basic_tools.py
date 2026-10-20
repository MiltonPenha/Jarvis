"""Live weather and headless browser navigation; isolated fixture notes/alarms."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.browser_control import BrowserControl
from core.weather import weather


def main():
    results={}
    with tempfile.TemporaryDirectory(prefix='jarvis-browser-check-') as directory:
        browser=BrowserControl(Path(directory),headless=True)
        try:
            def fixture():
                browser._start()
                def serve(route):
                    if '/second' in route.request.url:
                        body='<html lang="pt-BR"><title>Segunda página</title><body><h1>Navegação confirmada</h1><a href="https://example.com/jarvis-check/first">Voltar ao início</a></body></html>'
                    else:
                        body='<html lang="pt-BR"><title>Página de teste JARVIS</title><body><h1>Controle real do navegador</h1><a href="https://example.com/jarvis-check/second">Contato</a><input aria-label="Pesquisar" type="search"><p>Texto de teste observável.</p></body></html>'
                    route.fulfill(status=200,content_type='text/html; charset=utf-8',body=body)
                browser.context.route('https://example.com/jarvis-check/**',serve)
            browser.executor.submit(fixture).result(30)
            opened=browser.execute('browser_open','https://example.com/jarvis-check/first')
            assert opened['title']=='Página de teste JARVIS'
            filled=browser.execute('browser_fill','Pesquisar','receitas de café');assert filled['verified']
            clicked=browser.execute('browser_click','Contato');assert clicked['title']=='Segunda página'
            backed=browser.execute('browser_back');assert backed['title']=='Página de teste JARVIS'
            read=browser.execute('browser_read');assert 'Texto de teste observável' in read['message']
            browser.execute('browser_scroll','baixo')
            results['headless_browser']={'open':True,'fill':True,'click_and_navigate':True,'back':True,'read':True,'scroll':True}
            # Real Google search, with bot/consent behavior recorded honestly.
            try:
                search=browser.execute('browser_search','site:python.org Python documentação')
                results['google']={'title':search['title'],'url':search['url'],'elements':len(search['elements'])}
                if not search['elements']: results['google']['manual_verification_may_be_required']=True
            except Exception as exc: results['google']={'error':str(exc)[:300]}
        finally:
            browser.close();browser.executor.shutdown(wait=True)
    try:
        observed=weather()
        results['weather']={key:observed[key] for key in ('verified','location','approximate','observed_at')}
    except Exception as exc: results['weather']={'error':str(exc)[:300]}
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
