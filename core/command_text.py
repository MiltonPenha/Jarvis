"""Conservative utterance normalization; never rewrites artists or note payloads."""
import re
import unicodedata
from difflib import SequenceMatcher


def folded(text):
    return ''.join(c for c in unicodedata.normalize('NFD',str(text).casefold()) if unicodedata.category(c)!='Mn')


ACTION=r'(?:abra|abre|abro|abrir|acesse|entre|entra|entrar|toque|toca|tocar|coloque|coloca|reproduza|reproduzir|pause|continue|aumente|diminua|anote|pesquise|busque|leia|clique)'
MUSIC=r'(?:toque|toca|tocar|coloque|coloca|colocar|reproduza|reproduzir|bote|bota|ouvir|ouça|escutar)'


def is_vocative(word):
    value=folded(word)
    return value.startswith('jar') and 4<=len(value)<=7 and SequenceMatcher(None,value,'jarvis').ratio()>=.65


def normalize_command(command):
    value=command.strip()
    prefix=r'(?i)^(?:jarvis|javis|por favor|bom dia|boa tarde|boa noite|olá|ola|oi|agora)(?:[\s,.!?:;]+|$)'
    for _ in range(8):
        cleaned=re.sub(prefix,'',value,count=1).strip()
        if cleaned==value:break
        value=cleaned
    # Approximation is confined to a short address before an explicit action.
    # Unknown greeting words are removed only with evidence of that vocative.
    action=re.search(r'(?i)\b'+ACTION+r'\b',value)
    if action and action.start()>0:
        before=value[:action.start()]
        words=re.findall(r'\w+',before)
        if 1<=len(words)<=5 and is_vocative(words[-1]) and not set(map(folded,words))&{'nao','nunca','se','quando','anote','chamado','nome'}:
            value=value[action.start():]
    return value


def music_request(command,context=None):
    """Extract an explicit start/search request; relative requests keep context."""
    from core.music_followup import followup_call
    if followup_call(command):return None
    value=normalize_command(command)
    match=re.search(r'(?i)\b'+MUSIC+r'\s+(.+)',value)
    if not match:return None
    before=folded(value[:match.start()])
    if re.search(r'\b(?:nao|nunca|se|quando)\b',before):return None
    if before.strip() and not re.search(r'(?:[,;]|\be(?:\s+depois)?)\s*$',before) and not re.fullmatch(r'\s*(?:eu quero|quero|gostaria de|voce pode|pode|poderia)\s+',before):return None
    payload=re.split(r'(?i)(?:[,;]\s*|\s+e\s+(?:depois\s+)?)(?='+ACTION+r'\b)',match[1])[0]
    if re.match(r'(?i)^(?:o\s+)?(?:volume|alarme|lembrete|aviso|nota|anotação)\b',payload):return None
    query=re.sub(r'(?i)^(?:(?:uma?|alguma|a|minha|meu|no meu|na minha)\s+)?(?:música|musica|som|canção|cancao)\s*(?:(?:do|da|de|dos|das)\s+)?','',payload).strip(' .?!,')
    query=re.sub(r'(?i)\s+no\s+you\s*tube\s*$','',query).strip()
    relative=bool(re.fullmatch(r'(?:uma?\s+)?(?:outra\s+)?(?:(?:musica|cancao)\s+)?(?:dessa|desta|da mesma|do mesmo|desse|deste)\s+(?:banda|artista|cantor|cantora)',folded(query)))
    if relative:
        query=getattr(context,'media_query','') if context else ''
    return {'query':query,'relative':relative,'source_query':payload.strip()}


def music_correction(command,context=None):
    if not context or not context.pending_music_query:return None
    value=normalize_command(command)
    match=re.fullmatch(r'(?i)(?:(?:na verdade|corrigindo|correção|correcao)[, :]*\s*)?(?:o artista(?: que estou procurando| correto)?|a banda(?: que estou procurando| correta)?|a música(?: que estou procurando| correta)?)\s+(?:é|e)\s+(.+?)\s*[.!?]*',value)
    if not match:match=re.fullmatch(r'(?i)(?:eu disse|quis dizer|o nome correto é)\s+(.+?)\s*[.!?]*',value)
    return match[1].strip() if match and len(match[1])<=400 else None
