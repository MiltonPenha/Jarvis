"""Child process for the explicitly scripted Hermes integration test."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from run_agent import AIAgent
from hermes_state import SessionDB
from tools.registry import registry
from core.jarvis_tools import ToolService,SCHEMA
from core.hermes_runtime import ensure_hermes_config

ensure_hermes_config()
tools=ToolService('hermes-scripted')
registry.register(name='jarvis',toolset='jarvis',schema=SCHEMA,handler=lambda args,**kwargs:json.dumps(tools.execute(args)))
db=SessionDB()
agent=AIAgent(model='jarvis-scripted-test',provider='custom',api_mode='chat_completions',base_url=os.environ['JARVIS_PROBE_URL'],api_key='scripted-test-key',
    enabled_toolsets=['jarvis'],quiet_mode=True,skip_context_files=True,skip_background_review=True,
    max_iterations=3,max_tokens=200,run_budget_seconds=45,session_id='hermes-session',session_db=db,
    ephemeral_system_prompt='Use a ferramenta jarvis para criar o arquivo solicitado e verifique o resultado.')
try:
    assert [t['function']['name'] for t in agent.tools]==['jarvis'],str(agent.tools)[:500]
    result=agent.run_conversation('Crie o arquivo de prova.',task_id='hermes-scripted')
    assert 'verificado' in result['final_response'],str(result)
    messages=db.get_messages_as_conversation('hermes-session')
    assert any(m.get('role')=='tool' for m in messages),str(messages)
    print(json.dumps({'result':result['final_response'],'messages':len(messages),'calls':tools.calls}))
finally:
    agent.close();db.close()
