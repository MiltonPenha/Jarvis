"""Small local tools shared by direct commands and the constrained local planner."""
import json
from pathlib import Path
import re
import uuid
from core.config import config
from core.browser_control import browser_control, normalized
from core.reminders import reminders
from core.memory_obsidian import obsidian_memory

from core.basic_actions import BASIC_ACTIONS, BASIC_EFFECTS


def project_catalog():
    result={}
    if config.COMMANDS_FILE.exists():
        for macro in json.loads(config.COMMANDS_FILE.read_text(encoding='utf-8')).get('custom_commands',[]):
            if macro.get('action_type')=='open_folder':
                path=Path(macro.get('target','')).resolve()
                result[normalized(macro['trigger'])]=str(path)
                result[normalized(path.name)]=str(path)
    for root in config.WORKSPACE_ROOTS:
        result[normalized(root.name)]=str(root)
        if root.is_dir():
            for path in list(root.iterdir())[:60]:
                if path.is_dir() and not path.name.startswith('.'):
                    result[normalized(path.name)]=str(path)
    return result


def dispatch_basic(args,cancelled=lambda:False):
    action=args['action']; target=args.get('query',args.get('target','')); content=args.get('content','')
    if action.startswith('browser_'):
        return browser_control.execute(action,target,content,cancelled=cancelled)
    if action=='weather':
        from core.weather import weather
        return weather(target)
    if action=='project_open':
        catalog=project_catalog(); key=normalized(target)
        path=catalog.get(key)
        if not path:
            raise ValueError('Projeto não encontrado. Pastas cadastradas: '+', '.join(sorted(catalog)))
        # A configured folder macro is an explicit target, not a new filesystem grant.
        import os
        if not Path(path).is_dir(): raise FileNotFoundError('A pasta cadastrada não existe mais.')
        os.startfile(path)
        return {'verified':True,'launch_requested':True,'message':'Senhor, abertura da pasta solicitada ao Windows: '+path}
    if action=='note_create':
        text=content.strip()
        if not text or len(text)>12000: raise ValueError('Informe o conteúdo da anotação, com até 12000 caracteres.')
        title=re.sub(r'[^\w .-]','',target).strip()[:70] or 'Anotação'
        path=f'Notes/{title}-{uuid.uuid4().hex[:10]}.md'
        result=obsidian_memory.write(path,'# '+title+'\n\n'+text+'\n',source='user_statement')
        return {**result,'message':'Senhor, anotação salva no Obsidian: '+path,'spoken_message':'Senhor, anotação salva.'}
    if action=='note_search':
        results=obsidian_memory.search(target)
        return {'verified':True,'sources':results,'message':('Senhor, encontrei estas notas:\n'+'\n'.join(r['path']+': '+r['excerpt'] for r in results)) if results else 'Senhor, não encontrei notas com esse conteúdo.'}
    if action=='reminder_create':
        return reminders.create(content or 'Alarme',args.get('when',''), 'alarm' if target=='alarm' else 'reminder')
    if action=='reminder_list':
        from datetime import datetime
        rows=reminders.list()
        return {'verified':True,'reminders':rows,'message':'Senhor, '+('\n'.join(f"{r['id'][:8]} · {datetime.fromisoformat(r['due']).astimezone().strftime('%d/%m %H:%M')} · {r['text']} ({r['state']})" for r in rows) if rows else 'nenhum lembrete ou alarme pendente.')}
    if action=='reminder_dismiss':
        rows=reminders.list()
        matches=[r for r in rows if r['id'].startswith(target) or normalized(target)==normalized(r['text'])]
        if target in ('tocando','atual'): matches=[r for r in rows if r['state']=='due']
        if len(matches)!=1: raise ValueError('Informe o código de um único aviso da lista para encerrar.')
        return reminders.dismiss(matches[0]['id'])
    raise ValueError('Ferramenta básica desconhecida.')
