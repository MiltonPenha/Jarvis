"""Conservative Portuguese media/volume grammar -> normalized parameters.

Vocabulary describes intents, not scripts for sentences. Unconsumed words,
negation, conditions and mixed commands deliberately go to the planner.
"""
from dataclasses import dataclass
import re
import unicodedata


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD',value.casefold()) if unicodedata.category(c)!='Mn')


@dataclass(frozen=True)
class Intent:
    action:str
    operation:str
    scope:str='player'
    value:int|float|None=None
    request:str=''

    def call(self):
        if self.action=='media': return {'action':'media','check':self.operation,**({'query':self.request} if self.request else {})}
        result={'action':'volume','scope':self.scope,'mode':self.operation}
        if self.value is not None: result['value']=self.value
        return result


VERBS={
    'pause':r'paus(?:e|ar|a)', 'resume':r'continu(?:e|ar)|retom(?:e|ar)|despause',
    'stop':r'par(?:e|ar)|interrompa', 'next':r'proxima|proximo|pul(?:e|ar)',
    'previous':r'anterior|retorne|volt(?:e|ar)',
}
FILLER=set('jarvis javis voce pode poderia por favor a o as os um uma pouco para em de da do no na ao som audio volume musica faixa video reproducao youtube player sistema windows computador pc passe passar va modo'.split())


def media_intent(command):
    from core.volume_intent import parse_volume
    volume=parse_volume(command)
    if volume:return volume if not volume.question else None
    from core.music_followup import followup_call
    followup=followup_call(command)
    if followup:return Intent('media',followup['check'],request=followup.get('query',''))
    text=normalize(command)
    if re.fullmatch(r'(?:liste|listar|mostre|mostrar|quais(?: sao)?)\s+(?:as\s+)?(?:sugestoes|recomendacoes)(?:\s+do\s+youtube)?[ .?!]*',text):return Intent('media','suggestions')
    tokens=re.findall(r'\d+|[a-z]+|%',text)
    if not tokens or any(t in tokens for t in ('nao','nunca','se','quando','depois','e','ou','alarme','lembrete')): return None
    # Read-only status is safe only when the complete utterance is consumed.
    status_words=set('qual que o a nome da do musica faixa esta esta tocando atual agora status reproducao em no youtube jarvis javis'.split())
    if set(tokens)<=status_words and ('qual' in tokens or 'que' in tokens or 'status' in tokens) and any(t in tokens for t in ('musica','tocando','reproducao','faixa')):
        return Intent('media','status')
    operations=[];remaining=[]
    for token in tokens:
        found=next((name for name,pattern in VERBS.items() if re.fullmatch(pattern,token)),None)
        if found: operations.append(found)
        else: remaining.append(token)
    if len(set(operations))!=1: return None
    op=operations[0]
    allowed=FILLER|{'%','por','cento'}
    if any(t not in allowed and not t.isdigit() for t in remaining): return None
    numbers=[int(t) for t in remaining if t.isdigit()]
    if len(numbers)>1: return None
    if numbers: return None
    if set(tokens)&{'sistema','windows','computador','pc'}: return None
    return Intent('media',op)
