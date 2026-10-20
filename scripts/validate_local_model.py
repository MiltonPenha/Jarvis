"""Real CPU inference benchmark. Plans only: no apps, notes, timers or browser effects."""
import asyncio
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import psutil
from core.local_runtime import Plan, SYSTEM, ACTIONS, ground_plan, planner_prompt, planner_schema
from core.local_model import local_model

CASES=[
    ('Dá para deixar a calculadora aberta para mim?', 'open_target'),
    ('Dá uma olhada no clima de onde estou agora', 'weather'),
    ('Guarde uma anotação: comprar café amanhã', 'note_create'),
    ('Pode me avisar de beber água daqui a 20 minutos?', 'reminder_create'),
    ('Preciso de um alarme para amanhã às 9:30', 'reminder_create'),
    ('Quero procurar no Google informações sobre jardinagem', 'browser_search'),
    ('Acesse o endereço https://www.wikipedia.org', 'browser_open'),
    ('Me mostre os lembretes que estão agendados', 'reminder_list'),
    ('Desça um pouco a página para eu ver mais', 'browser_scroll'),
    ('Agora entre no link chamado Contato', 'browser_click'),
]

async def main():
    report={'cases':[],'peak_rss_mib':0,'peak_cpu_percent_machine':0,'vram_bytes':0}
    before=psutil.virtual_memory().available; running=True
    async def monitor():
        tracked={}
        while running:
            if local_model.process:
                try:
                    parent=psutil.Process(local_model.process.pid); processes=[parent]+parent.children(recursive=True)
                    rss=0; cpu=0
                    for process in processes:
                        rss+=process.memory_info().rss
                        tracked.setdefault(process.pid,process)
                        cpu+=tracked[process.pid].cpu_percent()
                    report['peak_rss_mib']=max(report['peak_rss_mib'],round(rss/2**20,1))
                    report['peak_cpu_percent_machine']=max(report['peak_cpu_percent_machine'],round(cpu/psutil.cpu_count(),1))
                except psutil.Error: pass
            await asyncio.sleep(.4)
    monitor_task=asyncio.create_task(monitor())
    try:
        schema=planner_schema()
        prompt=await asyncio.to_thread(planner_prompt)
        for text, expected in CASES:
            started=time.monotonic()
            try:
                raw=await local_model.plan((prompt,text),schema);plan=ground_plan(Plan.model_validate(raw),text)
                actual=plan.steps[0].action if plan.steps else 'question'
                correct=actual==expected
                if expected=='browser_open' and correct: correct=plan.steps[0].target=='https://www.wikipedia.org'
                if expected=='browser_scroll' and correct: correct=plan.steps[0].target=='baixo'
                if expected=='browser_click' and correct: correct=plan.steps[0].target.casefold()=='contato'
                if expected=='reminder_create' and correct:
                    correct=plan.steps[0].target==('alarm' if 'alarme' in text else 'reminder') and bool(plan.steps[0].when)
                    correct=correct and plan.steps[0].content==('Alarme' if 'alarme' in text else 'beber água')
                if expected=='note_create' and correct: correct=plan.steps[0].content=='comprar café amanhã'
                row={'text':text,'expected':expected,'actual':actual,'pass':correct,'plan':plan.model_dump(),
                     'seconds':round(time.monotonic()-started,2),**local_model.last_metrics}
            except Exception as exc:
                row={'text':text,'expected':expected,'pass':False,'error':str(exc)}
            report['cases'].append(row); print(json.dumps(row,ensure_ascii=False),flush=True)
        report['passed']=sum(row['pass'] for row in report['cases'])
        report['available_ram_before_gib']=round(before/2**30,2)
        report['available_ram_after_gib']=round(psutil.virtual_memory().available/2**30,2)
        from core.config import config
        path=config.DATA_DIR/'local-model-validation.json'
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:value for key,value in report.items() if key!='cases'}),flush=True)
    finally:
        running=False;await monitor_task
        await asyncio.to_thread(local_model.stop)

if __name__=='__main__': asyncio.run(main())
