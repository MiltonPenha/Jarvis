"""Portuguese volume relationships; preserve final targets, deltas and ratios."""
from dataclasses import dataclass
import os
import re
from core.command_text import folded,normalize_command


@dataclass(frozen=True)
class VolumeIntent:
    operation:str=''
    scope:str='player'
    value:int|float|None=None
    question:str=''
    action:str='volume'

    def call(self):
        result={'action':'volume','scope':self.scope,'mode':self.operation}
        if self.value is not None:result['value']=self.value
        return result


NUMBERS={'zero':0,'um':1,'uma':1,'dois':2,'duas':2,'tres':3,'quatro':4,'cinco':5,'seis':6,'sete':7,'oito':8,'nove':9,
    'dez':10,'onze':11,'doze':12,'treze':13,'quatorze':14,'catorze':14,'quinze':15,'dezesseis':16,'dezessete':17,
    'dezoito':18,'dezenove':19,'vinte':20,'trinta':30,'quarenta':40,'cinquenta':50,'sessenta':60,'setenta':70,
    'oitenta':80,'noventa':90,'cem':100,'cento':100,'duzentos':200,'trezentos':300,'quatrocentos':400,
    'quinhentos':500,'seiscentos':600,'setecentos':700,'oitocentos':800,'novecentos':900,'mil':1000}
NUMBER_WORDS='|'.join(sorted(NUMBERS,key=len,reverse=True))


def numbers(text):
    def replace(match):
        words=match[0].split();values=[NUMBERS[word] for word in words if word!='e']
        # Only conventional additive hundreds/tens/units, not two alternatives.
        if len(values)>1 and not all(a>=20 and b<a and (a>=100 or b<10) for a,b in zip(values,values[1:])):return match[0]
        return str(sum(values))
    return re.sub(r'\b(?:'+NUMBER_WORDS+r')(?:\s+(?:e\s+)?(?:'+NUMBER_WORDS+r'))*\b',replace,text)


UP=r'(?:aumente|aumentar|aumenta|suba|eleve)'
DOWN=r'(?:diminua|diminuir|diminu|diminui|abaixe|abaixar|baixe|reduza|reduzir)'
SET=r'(?:coloque|coloca|colocar|ajuste|defina|deixe|mude|ponha|bote)'
NOUN=r'(?:volume|som|audio)'
Q=r'(\d+(?:[.,]\d+)?)\s*%?'


def parse_volume(command):
    text=folded(normalize_command(command)).strip(' .?!,')
    for _ in range(5):
        text=re.sub(r'^(?:de novo|novamente|por favor|(?:eu )?quero que (?:voce )?|(?:eu )?quero |gostaria que (?:voce )?|voce pode |pode |poderia )[, ]*','',text).strip()
        text=re.sub(r'[, ]+(?:jarvis|javis|por favor)$','',text).strip(' .?!,')
    # A compound belongs to the existing sequential planner, not a single volume.
    if re.search(r'\b(?:e|depois)\s+(?:abra|toque|pause|continue|aumente|diminua|reduza|coloque|anote)\b',text):return None
    start=r'(?:'+UP+'|'+DOWN+'|'+SET+r'|dobre|duplicar|duplique|mute|mutar|silencie|silenciar|silencia|desmute|desmutar|reative|tire|desative|volume|som|audio|qual|quanto|no minimo|nao|nunca|se|quando)\b'
    if not re.match(start,text):return None
    relevant=bool(re.search(r'\b(?:volume|som|audio|minimo|maximo|mudo|mute|mutar|silencie|silenciar|silencia|desmute|desmutar|metade|dobro|pouco)\b',text) or re.match(r'(?:'+UP+'|'+DOWN+r')\s+(?:para |em )?(?:\d+(?:[.,]\d+)?|'+NUMBER_WORDS+r')\b',text) or re.match(r'(?:'+UP+'|'+DOWN+r'|silencie|mute|desmute)\b.*\bmusica\b',text))
    if not relevant:return None
    scope='system' if re.search(r'\b(?:sistema|windows|computador|pc)\b',text) else 'player'
    ask=lambda:VolumeIntent(scope=scope,question='Senhor, quer definir o volume para qual valor, ajustar quantos pontos ou usar qual proporção?')
    if re.search(r'\b(?:nunca|se|quando|nao)\b',text):return ask()
    text=re.sub(r'\bpor cento\b','%',text)
    text=re.sub(r'\bum pouco\b','pouco',text)
    text=numbers(text)
    text=re.sub(r'\s+(?:do|da|no|na)\s+(?:sistema|windows|computador|pc|player|musica|youtube|reproducao)\b','',text)
    # Removing the audio noun leaves the relation between verb and value intact.
    text=re.sub(r'\b(?:o |a )?'+NOUN+r'\b','',text)
    text=re.sub(r'\b(?:a |o )?(?:musica|reproducao)\b','',text)
    text=re.sub(r'\s+',' ',text).strip(' ,')
    if not text and relevant:return ask()
    if text in ('qual','quanto esta','qual esta','qual e'):return VolumeIntent('status',scope)
    if re.fullmatch(r'(?:mute|mutar|silencie|silenciar|silencia|ative (?:o )?mudo)',text):return VolumeIntent('mute',scope)
    if re.fullmatch(r'(?:desmute|desmutar|reative|(?:tire|desative) (?:o )?(?:modo )?mudo)',text):return VolumeIntent('unmute',scope)
    if re.fullmatch(r'(?:(?:'+SET+r') )?(?:no |ao |em |para (?:o )?)?minimo(?:,? mas sem (?:mutar|silenciar))?',text):
        from core.volume_control import minimum
        return VolumeIntent('absolute',scope,minimum())
    if re.fullmatch(r'(?:(?:'+SET+r') )?(?:no |ao |em |para (?:o )?)?maximo',text):return VolumeIntent('absolute',scope,100)
    if re.fullmatch(r'(?:dobre|duplique|duplicar)|(?:'+UP+r') (?:para )?(?:o )?dobro(?: do que esta| do atual)?',text):return VolumeIntent('multiply',scope,2)
    if re.fullmatch(r'(?:'+DOWN+r') (?:a|pela|para a|em) metade(?: do que esta| do atual)?',text):return VolumeIntent('multiply',scope,.5)
    proportional=re.fullmatch(r'('+UP+'|'+DOWN+r') em '+Q+r' (?:do (?:volume )?atual|do que esta)',text)
    if proportional:
        amount=float(proportional[2].replace(',','.'))/100
        return VolumeIntent('multiply',scope,1+amount if re.fullmatch(UP,proportional[1]) else max(0,1-amount))
    if re.fullmatch(r'(?:'+SET+r') (?:pela|em|na|para a) metade',text):return VolumeIntent('absolute',scope,50)
    absolute=re.fullmatch(r'(?:(?:'+UP+'|'+DOWN+'|'+SET+r') )?(?:(?:para|em|nos|no|a) )?'+Q,text)
    # A direction plus a bare/em quantity is a delta; para/nos specifies a target.
    directional=re.match('('+UP+'|'+DOWN+r')\b',text)
    final=bool(re.search(r'\b(?:para|nos|no)\s+\d',text))
    if absolute and (not directional or final):return VolumeIntent('absolute',scope,float(absolute[1].replace(',','.')))
    relative=re.fullmatch(r'('+UP+'|'+DOWN+r')(?: (?:em )?'+Q+r'|(?: pouco)?)',text)
    if relative:
        value=float(relative[2].replace(',','.')) if relative[2] else max(1,min(100,int(os.getenv('JARVIS_VOLUME_STEP','5'))))
        return VolumeIntent('relative',scope,value if re.fullmatch(UP,relative[1]) else -value)
    return ask()
