"""Read-only local diagnostics. --providers makes two catalog requests, no generation."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.config import config
from core.hermes_runtime import HermesRuntime,list_models
from core.safety import redact

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--providers',action='store_true')
    args=parser.parse_args()
    result=await HermesRuntime().run({'operation':'diagnostics'},timeout=45)
    import importlib.util
    result['dependencies_host']={name:importlib.util.find_spec(name) is not None for name in ('pypdf','docx','ddgs','sounddevice','edge_tts')}
    result['dependency_note']='Documentos, busca web, Windows e áudio são executados pelo host. Esses pacotes não precisam estar no worker Hermes.'
    result['vault']={'path':config.OBSIDIAN_VAULT_PATH,'exists':Path(config.OBSIDIAN_VAULT_PATH).is_dir()}
    result['workspaces']=[{'path':str(p),'exists':p.is_dir()} for p in config.WORKSPACE_ROOTS]
    if args.providers:
        result['catalogs']={}
        for provider in ('openai-api','gemini'):
            try:result['catalogs'][provider]={'models':await list_models(provider)}
            except Exception as exc:result['catalogs'][provider]={'error':redact(str(exc))}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
