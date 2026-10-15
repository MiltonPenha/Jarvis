"""Real deterministic tool smoke check in an isolated validation workspace/vault."""
import asyncio
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
ROOT=Path(__file__).resolve().parent.parent/'.data/validation/tools'
os.environ.update(JARVIS_DATA_DIR=str(ROOT/'data'),JARVIS_HERMES_HOME=str(ROOT/'hermes'),
                  OBSIDIAN_VAULT_PATH=str(ROOT/'vault'),JARVIS_WORKSPACE_ROOTS=str(ROOT/'workspace'))
(ROOT/'workspace').mkdir(parents=True,exist_ok=True)
from core.task_store import TaskStore
from core.hermes_runtime import HermesRuntime
from core.safety import atomic_write
from core.memory_obsidian import obsidian_memory

async def main():
    store=TaskStore();bridge=HermesRuntime()
    requests=[('web',{'action':'web_search','query':'site.hermes-agent.nousresearch.com/docs/guides/python-library Hermes'}),
              ('vault',{'action':'vault_write','path':'Knowledge/Validation.md','content':'Conhecimento de teste verificável.','source':'observed'}),
              ('vault-search',{'action':'vault_search','query':'verificável'})]
    if (obsidian_memory.vault_dir/'Knowledge/Validation.md').exists():
        requests[1][1]['expected_hash']=obsidian_memory.read('Knowledge/Validation.md')['sha256']
    results={}
    import uuid
    for label,args in requests:
        task='validation-'+uuid.uuid4().hex;store.create(task,'validation',label)
        result=await bridge.run({'operation':'tool','id':task,'args':args},timeout=45)
        results[label]=result
    atomic_write(ROOT/'results.json',json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False,indent=2))
    if not results['web'].get('sources') or not results['vault'].get('verified') or not results['vault-search'].get('sources'):
        raise SystemExit('Uma verificação real de ferramenta falhou; consulte os resultados.')

if __name__=='__main__':asyncio.run(main())
