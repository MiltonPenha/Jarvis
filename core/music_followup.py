"""Route continuation requests to the existing media controller, preserving words."""
import re
import time
import uuid
import hashlib
from core.command_text import normalize_command,folded


def confirmation_reply(command):
    """Short conversational answers only; new content/actions are not consent."""
    if command.rstrip().endswith('?'):return None
    text=folded(normalize_command(command))
    words=re.findall(r'\w+',text)
    words=[word for word in words if word not in ('jarvis','javis','jervis')]
    allowed=set('sim nao e eh isso exatamente esta essa este esse aquela aquele a o as os musica cancao faixa video mesmo mesma correto correta certo certa confirmo confirmado confirmada pode ser tocar toque toca reproduza reproduzir por favor obrigado obrigada perfeito afirmativo negativo nao quero'.split())
    if not words or len(words)>30 or any(word not in allowed for word in words):return None
    if 'nao' in words or 'negativo' in words:return 'reject'
    if any(word in words for word in ('sim','isso','exatamente','confirmo','confirmado','confirmada','correto','correta','certo','certa','perfeito','afirmativo')):
        return 'accept'
    if any(word in words for word in ('essa','esta','esse','este')) and any(word in words for word in ('mesmo','mesma','tocar','toque','reproduza')):return 'accept'
    return None


def confirmation_pending(pending,now=None):
    return bool(pending and pending.get('state')=='pending' and 0<=(time.time() if now is None else now)-pending.get('created_at',0)<=900)


def offer_confirmation(candidate,query,source_task,search_url,question_kind='play_candidate'):
    """Bind a single explicitly named proposal to an observed video, not a query."""
    return {'id':uuid.uuid4().hex,'state':'pending','created_at':time.time(),'source_task_id':source_task,'question_kind':question_kind,
            'query':query,'search_url':search_url,
            'candidate':{key:candidate.get(key,'') for key in ('video_id','title','channel','position','duration')}}


def confirmation_plan(command,context=None):
    if reference_request(command,context):return None
    reply=confirmation_reply(command)
    if reply is None:return None
    goal=getattr(context,'music_goal',{}) or {};pending=goal.get('confirmation',{})
    if not pending and not re.search(r'\b(?:musica|faixa|video|cancao)\b',folded(command)):return None
    if pending.get('state')=='superseded' and not re.search(r'\b(?:musica|faixa|video|cancao)\b',folded(command)):return None
    if confirmation_pending(pending):
        return {'steps':[{'action':'media','target':'confirm_music' if reply=='accept' else 'reject_music',
                         'arguments':{'query':pending['id']}}],'question':''}
    if pending.get('state')=='consumed':message='Senhor, essa escolha já foi confirmada. Não iniciei outra reprodução.'
    else:message='Senhor, não há uma escolha de música aguardando confirmação. Qual música deseja ouvir?'
    return {'steps':[],'question':message}


def reference_request(command,context=None):
    """Admission to the existing CPU interpreter, not a reference resolution."""
    from core.music_intent import quotes
    if quotes(command):return False
    if followup_call(command):return False
    goal=(context.get('music_goal',{}) if isinstance(context,dict) else getattr(context,'music_goal',{})) or {}
    pending=goal.get('confirmation',{})
    reply=confirmation_reply(command)
    if pending and reply is not None:
        return pending.get('question_kind')=='title_hypothesis' and reply=='accept'
    text=folded(normalize_command(command))
    if re.match(r'^(?:anote|lembre|me lembre|alarme|pesquise o tempo)\b',text):return False
    deictic=re.search(r'\b(?:essa|esse|esta|este|aquela|aquele|dessas|desses|encontrou|apresentou|mostrou|opcoes|opcao|primeir[ao]|segund[ao]|terceir[ao]|quart[ao]|quint[ao]|sext[ao]|setim[ao]|oitav[ao]|non[ao]|decim[ao])\b',text)
    action=re.search(r'\b(?:toque|toca|tocar|reproduza|reproduz|reproduzir|coloque|coloca|ouvir|ouca|e essa|e esta)\b',text)
    return bool(deictic and action or goal and re.search(r'^(?:a|o)\s+(?:do|da|de)\s+|\b(?:toque|toca|reproduza|coloque)\s+(?:a|o)\s+(?:do|da|de)\s+',text))


def candidate_rows(rows):
    """Canonical video identities and stable displayed positions, no model URLs."""
    from urllib.parse import urlparse,parse_qs
    result=[];seen=set()
    for index,row in enumerate(rows[:14],1):
        if row.get('ad') or row.get('mix'):continue
        video=row.get('video_id','');url=row.get('url','')
        if not re.fullmatch(r'[\w-]{11}',video) or not row.get('title') or video in seen:continue
        if url:
            parsed=urlparse(url)
            if parsed.hostname not in ('youtube.com','www.youtube.com') or parsed.path!='/watch' or parse_qs(parsed.query).get('v')!=[video]:continue
        position=row.get('position',index)
        if not isinstance(position,int) or isinstance(position,bool) or position<1:position=index
        result.append({'video_id':video,'url':'https://www.youtube.com/watch?v='+video,
            'title':str(row['title'])[:250],'channel':str(row.get('channel',''))[:120],
            'position':position,'duration':row.get('duration','')})
        seen.add(video)
    return sorted(result,key=lambda row:row['position'])


def reference_context(context):
    """A compact, serializable result list; a list alone is not a selection."""
    if isinstance(context,dict) and context.get('reference_context') is not None:return context['reference_context']
    goal=(context.get('music_goal',{}) if isinstance(context,dict) else getattr(context,'music_goal',{})) or {}
    pending=goal.get('confirmation',{});result=dict(goal.get('result_set') or {})
    rows=candidate_rows(result.get('candidates') or goal.get('observed') or [])
    proposed=pending.get('candidate') if confirmation_pending(pending) else None
    selected=goal.get('selected_candidate')
    if not rows and (proposed or selected):rows=candidate_rows([proposed or selected])
    if not result and rows:
        digest=hashlib.sha256((str(goal.get('task_id',''))+str(goal.get('last_search_query') or goal.get('query',''))+','.join(row['video_id'] for row in rows)).encode()).hexdigest()[:24]
        result={'id':digest,'source_task_id':goal.get('task_id',''),'query':goal.get('last_search_query') or goal.get('query',''),
            'search_url':pending.get('search_url') or goal.get('tab_url',''),'tab_id':pending.get('tab_id',''),'created_at':pending.get('created_at',goal.get('observed_at',time.time()))}
    identities={row['video_id'] for row in rows}
    presented=(proposed or {}).get('video_id') or result.get('presented_candidate_id','')
    selected_id=(selected or {}).get('video_id') or result.get('selected_candidate_id','')
    return {**result,'candidates':rows,'presented_candidate_id':presented if presented in identities else '',
        'selected_candidate_id':selected_id if selected_id in identities else '',
        'pending_confirmation':{k:pending.get(k) for k in ('id','state','question_kind')},
        'original_query':goal.get('query','')}


def reference_question(snapshot,reason='ambiguous_reference'):
    rows=snapshot.get('candidates',[])
    if reason=='model_unavailable':return 'Senhor, a IA local não concluiu a referência. Mantive os resultados, sem iniciar outra busca.'
    if reason=='expired_context':return 'Senhor, essa lista é antiga. Deseja refazer a pesquisa anterior?'
    if reason=='reference_executing':return 'Senhor, essa escolha já está em execução. Aguarde a confirmação do player.'
    if not rows:return 'Senhor, não tenho uma mídia identificável nesta conversa. Qual conteúdo deseja ouvir?'
    choices='; '.join(f"{row['position']}: {row['title']}" for row in rows[:3])
    return 'Senhor, qual destas opções deseja reproduzir? '+choices+'. Pode dizer o número ou o nome.'


def reference_positions(original):
    text=folded(normalize_command(original))
    ordinals={'primeiro':1,'primeira':1,'segundo':2,'segunda':2,'terceiro':3,'terceira':3,'quarto':4,'quarta':4,'quinto':5,'quinta':5,'sexto':6,'sexta':6,'setimo':7,'setima':7,'oitavo':8,'oitava':8,'nono':9,'nona':9,'decimo':10,'decima':10}
    return [ordinals[word] for word in re.findall(r'\w+',text) if word in ordinals]+[int(value) for value in re.findall(r'\b(?:opcao|numero|resultado)\s*(\d+)\b',text)]


def validate_reference(decision,original,snapshot):
    """Membership and unique grounding. A valid ID alone never resolves 'essa'."""
    action=decision.get('action');rows=snapshot.get('candidates',[])
    failure=lambda reason:{**decision,'accepted':False,'query':'','reason':reason,'reference_context':snapshot}
    if action not in ('play_existing','select_position','confirm_title'):return failure('ambiguous_reference')
    if not rows:return failure('missing_reference_context')
    if time.time()-snapshot.get('created_at',time.time())>900:return failure('expired_context')
    if decision.get('result_set_id')!=snapshot.get('id'):return failure('unknown_result_set')
    matches=[row for row in rows if row['video_id']==decision.get('candidate_id')]
    if len(matches)!=1:return failure('unknown_candidate')
    candidate=matches[0];text=folded(normalize_command(original))
    if re.search(r'\b(?:nao|nunca)\s+(?:(?:quero|pode)\s+)?(?:que voce\s+)?(?:toque|toca|tocar|reproduza|reproduzir|coloque|coloca)\b',text):return failure('negated_request')
    if decision.get('service')=='unsupported':return failure('unsupported_service')
    # Acknowledging a title hypothesis alone never grants playback consent,
    # even if the model mistakenly labels the affirmative as play_existing.
    if snapshot.get('pending_confirmation',{}).get('question_kind')=='title_hypothesis' and confirmation_reply(original)=='accept' and not re.search(r'\b(?:toque|toca|tocar|reproduza|reproduzir|coloque|coloca|ouvir)\b',text):
        action='confirm_title';decision={**decision,'action':action}
    elif action=='confirm_title' and re.search(r'\b(?:toque|toca|reproduza|reproduz|coloque|coloca|pode tocar|pode reproduzir|quero ouvir)\b',text):
        action='play_existing';decision={**decision,'action':action}
    positions=reference_positions(original)
    if action=='select_position' or positions:
        position=decision.get('position')
        if not positions or len(set(positions))!=1 or position!=positions[0] or candidate['position']!=position:return failure('ungrounded_position')
        action='select_position';decision={**decision,'action':action}
    else:
        span=decision.get('reference_span','').strip()
        if span and folded(normalize_command(span)) not in text:return failure('ungrounded_reference')
        ignored=set('a o as os de do da dos das essa esse esta este aquela aquele musica midia video faixa opcao exatamente mesmo mesma que voce encontrou apresentou mostrou toque toca tocar reproduza reproduzir coloca coloque quero eu pode por favor sim e assim pra para mim agora jarvis javis jervis boa bom dia tarde noite ola oi consegue poderia desejo ouvir ouca'.split())
        terms=[word for word in re.findall(r'\w+',folded(span)) if word not in ignored]
        if terms:
            identities=[row['video_id'] for row in rows if all(term in re.findall(r'\w+',folded(row['title']+' '+row['channel'])) for term in terms)]
            if not identities:return failure('unknown_reference_content')
            if identities!=[candidate['video_id']]:return failure('ambiguous_reference')
        else:
            unique=snapshot.get('presented_candidate_id') or snapshot.get('selected_candidate_id') or (rows[0]['video_id'] if len(rows)==1 else '')
            if candidate['video_id']!=unique:return failure('ambiguous_reference')
    if snapshot.get('pending_confirmation',{}).get('state')=='executing':return failure('reference_executing')
    return {**decision,'accepted':True,'query':'','candidate':candidate,'result_set_id':snapshot['id'],
        'source_task_id':snapshot.get('source_task_id'),'reference_context':snapshot,'source':'local-cpu-media-reference'}


def followup_call(command):
    text=folded(normalize_command(command)).strip(' .?!,')
    text=re.sub(r'^(?:(?:eu )?quero que (?:voce )?|voce pode |pode |por favor )','',text)
    if re.search(r'\b(?:nao|nunca|se|quando|anote|lembre|alarme|volume)\b',text):return None
    if re.search(r'\b(?:e|depois)\s+(?:abra|toque|coloque|pause|continue|aumente|diminua)\b',text):return None
    marker=bool(re.search(r'\b(?:sugestoes|sugestao|recomendacoes|recomendacao)\b',text))
    relative=bool(re.search(r'\b(?:deles|delas|dessa banda|desta banda|mesma banda|mesmo artista|desse artista)\b',text))
    next_request=bool(re.match(r'^(?:(?:passe|passa|pular|pule|va|siga) (?:para |pra |pro )?(?:a |o )?)?proxim[ao]\b',text))
    another=bool(re.match(r'^(?:(?:toque|toca|coloque|coloca|reproduza|bote|siga) (?:a |uma |o )?)?(?:outra|mais uma|primeira|primeiro)\b',text))
    generic_another=bool(re.fullmatch(r'(?:(?:toque|toca|coloque|coloca|reproduza) )?(?:outra|mais uma)(?: (?:musica|faixa))?',text))
    if not (next_request or generic_another or (marker or relative) and (another or re.match(r'^(?:toque|toca|coloque|coloca|siga|reproduza)\b',text))):return None
    generic=bool(re.fullmatch(r'(?:(?:passe|passa|pule|va|siga) (?:para |pra |pro )?(?:a |o )?)?proxim[ao](?: (?:musica|faixa|video|reproducao))?',text))
    if generic or generic_another:return {'action':'media','check':'next'}
    return {'action':'media','check':'recommendation','query':command.strip()[:1000]}


def policy(command):
    text=folded(command)
    same=bool(re.search(r'\b(?:deles|delas|dessa banda|desta banda|mesma banda|mesmo artista|desse artista)\b',text))
    explicit=bool(re.search(r'\b(?:sugestoes|sugestao|recomendacoes|recomendacao)\b',text))
    # Explicit artist spans are data; the model can relate a phonetic spelling
    # to an observed artist, but cannot silently switch to an unrelated band.
    match=re.search(r'\b(?:outra|musica|reproducao|faixa|sugestao|recomendacao)\s+(?:musica\s+)?(?:do|da|de)\s+(.+?)(?=\s+(?:pelas?|nas?|das?)\s+(?:sugestoes|recomendacoes)|$)',text)
    artist=match[1].strip(' .?!,') if match and not same else ''
    return {'source':'recommendations' if explicit or same or artist else 'auto',
        'criterion':'same_artist' if same else 'requested_artist' if artist else 'first_eligible','requested_artist':artist}
