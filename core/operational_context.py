"""Small volatile session context; the existing TaskStore is the effect ledger.

Live page identities deliberately do not survive a browser/server restart.
"""
from dataclasses import dataclass,field
import threading


@dataclass
class OperationalContext:
    session:str
    tab_id:str=''
    media_tab_id:str=''
    media_identity:str=''
    media_invalid:bool=False
    media_query:str=''
    pending_music_query:str=''
    resolve_music:object=field(default=None,repr=False,compare=False)
    select_music:object=field(default=None,repr=False,compare=False)
    music_intent:dict=field(default_factory=dict,repr=False,compare=False)
    interpret_music:object=field(default=None,repr=False,compare=False)
    record_music_query:object=field(default=None,repr=False,compare=False)
    record_music_confirmation:object=field(default=None,repr=False,compare=False)
    music_goal:dict=field(default_factory=dict)
    music_source:str=''
    music_task:str=''
    music_revision:int=0
    select_music_result:object=field(default=None,repr=False,compare=False)
    application:str=''
    task:str=''
    last_action:str=''
    last_result:dict=field(default_factory=dict)
    report:object=field(default=lambda value:None,repr=False,compare=False)

    def observe(self,action,result):
        self.last_action=action
        self.last_result={k:result[k] for k in ('status','verified','title','url','message','error') if k in result}
        if len(str(self.last_result.get('message','')))>500: self.last_result['message']=self.last_result['message'][:500]

    def compact(self):
        return {'tab':self.tab_id,'media_tab':self.media_tab_id,'media_identity':self.media_identity,
            'media_invalid':self.media_invalid,
            'media_query':self.media_query,
            'pending_music_query':self.pending_music_query,
            'music_goal':self.music_goal,'music_source':self.music_source[:1000],
            'application':self.application,'task':self.task[:200],'last_action':self.last_action,'last_result':self.last_result}

    def recognition_hints(self):
        values=[self.music_goal.get('resolved_query') or self.music_goal.get('query',''),self.music_goal.get('confirmed_title','')]
        return ' '.join(dict.fromkeys(value[:180] for value in values if value))[:600]


_contexts={}
_lock=threading.Lock()
def context_for(session):
    with _lock:
        if session not in _contexts:
            if len(_contexts)>=100: _contexts.pop(next(iter(_contexts)))
            _contexts[session]=OperationalContext(session)
        return _contexts[session]


def browser_tool(args,cancelled,context):
    from core.browser_control import browser_control
    return browser_control.tool(args,context,cancelled,progress=context.report)
