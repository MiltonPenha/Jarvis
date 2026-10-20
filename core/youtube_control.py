"""YouTube playback through visible search results and observed media progress."""
import re
import time
import unicodedata
from urllib.parse import urlencode, urlparse, parse_qs


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD',str(value).casefold()) if unicodedata.category(c)!='Mn')


def music_query(value):
    return value.strip(' .?!,')


from core.media_control import player_state, preferences as _preferences


def _check(cancelled, page=None):
    if cancelled():
        if page:
            try: page.evaluate("() => document.querySelector('video')?.pause()")
            except Exception: pass
        raise ValueError('Reprodução interrompida pelo usuário.')


def _manual_gate(page):
    host=urlparse(page.url).hostname or ''
    if 'consent.youtube.com' in host or 'consent.google.com' in host:
        return 'O YouTube está pedindo uma escolha de cookies. Faça a escolha na janela e repita o pedido.'
    text=normalized(page.locator('body').inner_text(timeout=3000)[:1800])
    if any(marker in text for marker in ("sign in to confirm",'faca login para confirmar','confirme que voce nao e um robo','unusual traffic','trafego incomum')):
        return 'O YouTube pediu login ou verificação humana. Resolva na janela e repita o pedido.'
    return None


def authentication_state(page):
    """Observe YouTube itself; Chrome account sync is not proof of site login."""
    host=urlparse(page.url).hostname or ''
    if host not in ('youtube.com','www.youtube.com'):return {'authenticated':False,'state':'wrong_site'}
    def site_login():
        # Read only the site's public session boolean, never account details,
        # cookies or tokens. Modern layouts may omit the old avatar button.
        return page.evaluate("() => window.ytcfg?.get?.('LOGGED_IN') === true")
    if site_login():return {'authenticated':True,'state':'authenticated','evidence':'site_session_flag'}
    try:
        page.locator('ytd-masthead, #masthead').first.wait_for(state='visible',timeout=8000)
        page.wait_for_function('''() => window.ytcfg?.get?.('LOGGED_IN') === true || !!document.querySelector('ytd-masthead button#avatar-btn, #masthead button#avatar-btn') ||
            [...document.querySelectorAll('ytd-masthead a[href*="ServiceLogin"], #masthead a[href*="accounts.google.com"]')].some(e=>e.getClientRects().length)''',timeout=5000)
    except Exception:pass
    # Presence of an enabled visible avatar control is sufficient. Do not click
    # it, extract account identifiers or read cookies to determine login state.
    avatar=page.locator('ytd-masthead button#avatar-btn, #masthead button#avatar-btn')
    authenticated=site_login() or any(node.is_visible() and node.is_enabled() for node in avatar.element_handles())
    return {'authenticated':authenticated,'state':'authenticated' if authenticated else 'login_required'}


class CandidateRows(list):
    """One atomic DOM observation, with diagnostics from the same document."""
    def __init__(self,rows,diagnostics):
        super().__init__(rows);self.diagnostics=diagnostics


def _candidates(page, query):
    raw=page.evaluate(r'''() => {
        const visible=e=>!!e&&!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
        const text=e=>(e?.textContent||'').replace(/\s+/g,' ').trim();
        const cards=[...document.querySelectorAll('ytd-search ytd-video-renderer, ytd-search yt-lockup-view-model')];
        // The unscoped fallback also supports embedded result fixtures; never
        // read watch-page recommendations as search results.
        const nodes=cards.length?cards:[...document.querySelectorAll('ytd-video-renderer')];
        let missing=0,ads=0,nonVideo=0;const incomplete=[];
        const rows=nodes.filter(visible).slice(0,20).flatMap((node,index)=>{
            if(node.closest('ytd-ad-slot-renderer')||node.querySelector('[is-ad], ytd-ad-slot-renderer')){ads++;return []}
            const titleNode=node.querySelector('a#video-title, h3 a[href*="/watch?"], .yt-lockup-metadata-view-model__title');
            const link=titleNode?.matches('a')?titleNode:titleNode?.querySelector('a[href*="/watch?"]');
            const channelNode=node.querySelector('#channel-name a, a[href^="/@"], a[href*="/channel/"]');
            const title=(titleNode?.getAttribute('title')||text(titleNode)).trim();
            let url;const href=link?.getAttribute('href');try{if(href)url=new URL(href,location.href)}catch{}
            // A displayed radio collection is not an incomplete music card.
            // Ordinary videos may also carry list/RD parameters, so require
            // the visible collection title as independent evidence.
            if(/^mix(?:\s+de\s+|\s*[-–—:]\s*)/i.test(title)&&url?.searchParams.has('list')){nonVideo++;return []}
            if(url&&(!['youtube.com','www.youtube.com'].includes(url.hostname)||url.pathname!='/watch')){nonVideo++;return []}
            if(!title||!url||!/^[-\w]{11}$/.test(url.searchParams.get('v')||'')){missing++;incomplete.push({position:index+1,title,reason:'missing_title_or_video_link'});return []}
            const channel=text(channelNode);
            if(!channel){missing++;incomplete.push({position:index+1,title,url:url.href,reason:'missing_channel'});return []}
            return [{title,channel,video_id:url.searchParams.get('v'),url:url.href,position:index+1,
                duration:text(node.querySelector('ytd-thumbnail-overlay-time-status-renderer, yt-thumbnail-badge-view-model'))}];
        });
        const noResults=[...document.querySelectorAll('ytd-message-renderer')].some(e=>visible(e)&&/no results|nenhum resultado|não encontramos|nao encontramos/i.test(text(e)));
        return {rows,diagnostics:{url:location.href,document_key:performance.timeOrigin,cards:nodes.length,missing,ads,non_video:nonVideo,incomplete,no_results:noResults,
            loading:!!document.querySelector('ytd-search tp-yt-paper-spinner[active], ytd-search yt-loading-spinner[active]')}};
    }''')
    candidates=[]
    for row in raw['rows']:
        connectors={'and','the','uma','musica','do','dos','da','das','de','para','banda','artista'}
        words=[w for w in re.findall(r'\w+',normalized(query)) if len(w)>1 and w not in connectors]
        title=row['title'];channel=row['channel']
        score=sum(2 for w in words if w in normalized(title))+sum(1 for w in words if w in normalized(channel))
        coverage=sum(w in normalized(title+' '+channel) for w in words)/max(1,len(words))
        compact=lambda text:re.sub(r'\W+','',normalized(text))
        if compact(query) and compact(query) in compact(channel):score+=8
        unwanted=('full album','greatest hits','playlist','compilation','karaoke','cover','reaction','tutorial')
        if any(w in normalized(title) and w not in normalized(query) for w in unwanted):score-=8
        candidates.append({**row,'score':score,'coverage':coverage})
    return CandidateRows(sorted(candidates,key=lambda item:item['score'],reverse=True),raw['diagnostics'])


def _read_results(page,query,cancelled,exclude):
    """Retry the observation, not the search. Do not reuse old card handles."""
    snapshots=[];previous=None;stable=0;observed=[]
    for sample in range(40):
        _check(cancelled)
        rows=_candidates(page,query);diagnostics=getattr(rows,'diagnostics',{})
        actual=diagnostics.get('url')
        if actual:
            parsed=urlparse(actual)
            if parsed.path!='/results' or parse_qs(parsed.query).get('search_query')!=[query]:
                raise RuntimeError('A aba mudou durante a leitura da pesquisa.')
        observed=[r for r in rows if r['video_id'] not in exclude]
        signature=[(r['video_id'],r['title'],r.get('channel')) for r in observed]
        snapshots.append({**diagnostics,'sample':sample,'readable':len(observed)})
        stable=stable+1 if signature==previous else 0;previous=signature
        if diagnostics.get('no_results'):return observed,snapshots
        if observed and stable>=3 and not diagnostics.get('loading') and not diagnostics.get('missing'):return observed,snapshots
        if not observed:
            gate=_manual_gate(page)
            if gate:raise ValueError(gate)
        page.wait_for_timeout(250)
    if not observed:raise RuntimeError('Resultados não ficaram legíveis no tempo disponível.')
    # Partial cards are diagnosed explicitly; valid complete cards can still
    # support selection after the bounded wait, without inventing missing data.
    return observed,snapshots


def play_youtube(page, query, cancelled=lambda:False, session=None, require_login=False, exclude=None, progress=lambda value:None,resolve=None,record_query=None,select_result=None,goal=None):
    query=music_query(query)
    if not query or len(query)>400: raise ValueError('Informe uma música ou artista com até 400 caracteres.')
    _check(cancelled)
    if require_login:
        progress({'stage':'checking_youtube_login','message':'Verificando sua sessão no YouTube.'})
        if (urlparse(page.url).hostname or '') not in ('youtube.com','www.youtube.com'):
            page.goto('https://www.youtube.com/',wait_until='domcontentloaded')
        gate=_manual_gate(page)
        if gate:return {'verified':False,'stage':'consent_or_verification','needs_manual_verification':True,'message':'Senhor, '+gate}
        auth=authentication_state(page)
        if not auth['authenticated']:
            return {'verified':False,'stage':auth['state'],'youtube_authenticated':False,'playback_confirmed':False,
                'message':'Senhor, este perfil ainda não está autenticado no YouTube. Entre na sua conta nessa aba e repita o pedido. Não iniciei uma reprodução anônima.'}
    if select_result:
        return _play_contextual(page,query,cancelled,session,require_login,exclude or set(),progress,record_query,select_result,goal or {})
    progress({'stage':'searching','message':'Pesquisando no YouTube.'})
    if session is not None:session.query=query;session.require_login=require_login
    if record_query:record_query(query)
    page.goto('https://www.youtube.com/results?'+urlencode({'search_query':query}),wait_until='domcontentloaded')
    deadline=time.monotonic()+12
    candidates=[];observed=[]
    while time.monotonic()<deadline:
        _check(cancelled)
        observed=_candidates(page,query)
        candidates=[row for row in observed if row['video_id'] not in (exclude or set()) and row['score']>0 and row['coverage']>=.7]
        # Wait for a useful observed queue, rather than stopping when the first
        # tile (often accompanied only by a cover) happens to render.
        eligible=[row for row in candidates if row['score']>=max(1,candidates[0]['score']*.4)] if candidates else []
        if len(eligible)>=3: break
        if not candidates and len(observed)>=5:break
        gate=_manual_gate(page)
        if gate: return {'verified':False,'playback_confirmed':False,'needs_manual_verification':True,'message':'Senhor, '+gate}
        page.wait_for_timeout(300)
    if not candidates:
        resolution=None
        if resolve and observed:
            progress({'stage':'resolving_artist','message':'Conferindo o nome do artista com o modelo local.'})
            resolution=resolve(query,observed)
            if resolution.get('accepted') and normalized(resolution['query'])!=normalized(query):
                progress({'stage':'artist_resolved','message':'Interpretando o artista como '+resolution['query']+', com base nos resultados encontrados.'})
                result=play_youtube(page,resolution['query'],cancelled,session,require_login,exclude,progress,record_query=record_query)
                result['music_resolution']=resolution
                result['requested_query']=query
                return result
        return {'verified':False,'stage':'no_results','playback_confirmed':False,'query':query,'music_resolution':resolution,
            'message':'Senhor, pesquisei “'+query+'”, mas não encontrei um resultado suficientemente correspondente. Pode confirmar o artista ou título?'}
    selected=candidates[0]
    if session is not None:
        seen=set()
        session.queue=[]
        for candidate in candidates:
            if candidate['video_id'] not in seen and candidate['score']>=max(1,selected['score']*.4):
                session.queue.append(candidate); seen.add(candidate['video_id'])
        if not session.queue: session.queue=[selected]
        session.index=0
    _check(cancelled)
    progress({'stage':'video_selected','message':'Abrindo o vídeo.'})
    url='https://www.youtube.com/watch?'+urlencode({'v':selected['video_id']})
    page.goto(url,wait_until='domcontentloaded')
    result=_confirm_playback(page,selected,cancelled,session,progress=progress)
    result.update(search_completed=True,video_selected=True,youtube_authenticated=True if require_login else None,effective_query=query)
    return result


def _play_contextual(page,query,cancelled,session,require_login,exclude,progress,record_query,select_result,goal):
    import uuid
    from core.music_followup import candidate_rows
    attempts=[];searches=[query];selected=None;observed=[];decision={};events=[]
    started=time.monotonic()
    def event(stage,**data):events.append({'stage':stage,'seconds':round(time.monotonic()-started,3),**data})
    result_set={'id':uuid.uuid4().hex,'source_task_id':goal.get('task_id',''),'query':query,'created_at':time.time(),
        'candidates':[],'presented_candidate_id':'','selected_candidate_id':''}
    metadata={'search_queries':searches,'effective_query':query,'result_set':result_set,
        'music_selection':{'purpose':'search_result','attempts':attempts,'decision':decision},
        'music_pipeline':{'task_id':goal.get('task_id',''),'query':query,'events':events},'observed_results':observed}
    def finish(result):
        _check(cancelled)
        result_set['selected_candidate_id']=(result.get('selected_candidate') or {}).get('video_id','')
        result_set['presented_candidate_id']=(result.get('music_confirmation') or metadata.get('music_confirmation') or {}).get('candidate',{}).get('video_id','')
        if not result.get('verified'):result_set['clarification']=result.get('message','')[:600]
        event('final',outcome=result.get('stage'),verified=result.get('verified'),message=result.get('message'))
        return {**metadata,**result}
    _check(cancelled)
    progress({'stage':'searching','query':query,'result_set_id':result_set['id'],'message':'Pesquisando a música na aba do YouTube.'})
    if record_query:record_query(query)
    event('search_navigation',query=query,reason='accepted_music_intent')
    search_url='https://www.youtube.com/results?'+urlencode({'search_query':query})
    result_set['search_url']=search_url
    try:page.goto(search_url,wait_until='domcontentloaded')
    except Exception as exc:
        _check(cancelled)
        event('navigation_timeout',target='search',error_type=type(exc).__name__)
        parsed=urlparse(str(page.url))
        if parsed.path!='/results' or parse_qs(parsed.query).get('search_query')!=[query]:
            return finish({'verified':False,'stage':'search_navigation_failed','playback_confirmed':False,'message':'Senhor, não consegui abrir a pesquisa no YouTube.','error_type':type(exc).__name__})
    try:observed,snapshots=_read_results(page,query,cancelled,exclude)
    except Exception as exc:
        _check(cancelled)
        stage='consent_or_verification' if isinstance(exc,ValueError) else 'results_read_failed'
        event(stage,error_type=type(exc).__name__,detail=str(exc)[:350])
        return finish({'verified':False,'stage':stage,'playback_confirmed':False,
            'message':'Senhor, '+str(exc) if isinstance(exc,ValueError) else 'Senhor, abri a pesquisa, mas não consegui ler os resultados. Não selecionei nenhum vídeo.'})
    metadata['observed_results']=observed
    result_set['candidates']=candidate_rows(observed)
    progress({'stage':'results_found','count':len(observed),'query':query,'result_set_id':result_set['id'],
        'source_task_id':result_set['source_task_id'],'candidates':result_set['candidates'],'message':f'Encontrei {len(observed)} resultados legíveis.'})
    event('results_read',snapshots=snapshots,observed=observed)
    _check(cancelled)
    if observed:
        progress({'stage':'selecting_music','message':'Conferindo conteúdo e artista nos resultados com a IA local.'})
        decision=select_result(goal.get('query') or query,observed,goal)
        attempts.append(decision);metadata['music_selection']['decision']=decision
        _check(cancelled)
        selected=next((row for row in observed if row['video_id']==decision.get('candidate_id')),None) if decision.get('accepted') else None
        event('selection',accepted=bool(selected),candidate_id=decision.get('candidate_id'),reason=decision.get('reason'),
            evidence=decision.get('evidence',{}).get(decision.get('candidate_id')),new_search=False)
    if selected is None:
        if snapshots[-1].get('missing') or snapshots[-1].get('loading'):
            stage='results_read_incomplete';message='Senhor, a página ainda deixou resultados incompletos. Não consegui concluir a leitura para escolher a música.'
        elif not observed:
            stage='no_results';message='Senhor, o YouTube informou que não há resultados para essa consulta. Qual título ou artista deseja usar?'
        elif decision.get('reason')=='model_unavailable':
            stage='selection_unavailable';message='Senhor, li os resultados, mas a IA local não concluiu a escolha. Não iniciei outro vídeo.'
        elif decision.get('reason')!='ambiguous_results':
            stage='no_matching_result' if decision.get('reason')=='insufficient_evidence' else 'selection_uncertain'
            message='Senhor, li os resultados, mas não consegui sustentar uma escolha para o conteúdo pedido. Qual título e artista deseja ouvir?'
        else:
            stage='ambiguous_results';message='Senhor, encontrei músicas diferentes com esse nome. Qual delas deseja ouvir?'
            if decision.get('suggested_title'):message='Senhor, você quis dizer '+decision['suggested_title']+'?'
            proposed=decision.get('suggested_candidate')
            if proposed and any(row['video_id']==proposed['video_id'] and row['title']==proposed['title'] for row in observed):
                from core.music_followup import offer_confirmation
                metadata['music_confirmation']=offer_confirmation(proposed,goal.get('query') or query,goal.get('task_id',''),page.url,question_kind='title_hypothesis')
        return finish({'verified':False,'stage':stage,'playback_confirmed':False,'message':message,'spoken_message':message})
    _check(cancelled)
    if session is not None:
        session.query=query;session.require_login=require_login
        session.queue=[row for row in observed if decision.get('evidence',{}).get(row['video_id'],{}).get('eligible')]
        if not session.queue:session.queue=[selected]
        session.index=next((i for i,row in enumerate(session.queue) if row['video_id']==selected['video_id']),0)
    progress({'stage':'video_selected','candidate':selected,'query':query,'result_set_id':result_set['id'],'message':'Selecionei '+selected['title']+'.'})
    progress({'stage':'opening_video','candidate':selected,'query':query,'result_set_id':result_set['id'],'message':'Abrindo '+selected['title']+'.'})
    event('video_navigation',candidate_id=selected['video_id'])
    try:page.goto('https://www.youtube.com/watch?'+urlencode({'v':selected['video_id']}),wait_until='domcontentloaded')
    except Exception as exc:
        _check(cancelled)
        event('navigation_timeout',target='video',error_type=type(exc).__name__)
        parsed=urlparse(str(page.url))
        if parsed.path!='/watch' or parse_qs(parsed.query).get('v')!=[selected['video_id']]:
            return finish({'verified':False,'stage':'video_navigation_failed','playback_confirmed':False,'message':'Senhor, encontrei o vídeo, mas não consegui abri-lo. Não confirmei a reprodução.','error_type':type(exc).__name__})
    _check(cancelled)
    try:result=_confirm_playback(page,selected,cancelled,session,progress=progress)
    except Exception as exc:
        _check(cancelled)
        result={'verified':False,'stage':'playback_failed','playback_confirmed':False,'title':selected['title'],
            'message':'Senhor, encontrei e abri o vídeo, mas não consegui confirmar o início da reprodução.','error_type':type(exc).__name__}
    result.update(**metadata,search_completed=True,video_selected=True,youtube_authenticated=True if require_login else None,
        selected_candidate=selected,transcription_corrections=decision.get('corrections',[]),resolved_content=decision.get('corrected_content',goal.get('query',query)))
    if result.get('verified') and not result.get('player_muted'):result['spoken_message']='Senhor, estou reproduzindo '+result['title']+'.'
    event('playback_verification',candidate_id=selected['video_id'],verified=result.get('verified'),outcome=result.get('stage'))
    return finish(result)


def confirm_youtube(page,pending,cancelled,session=None,require_login=False,progress=lambda value:None,before_play=lambda:None):
    """Consume the offered observed ID. Never search or rerun ambiguous selection."""
    from core.youtube_suggestions import individual
    candidate=dict(pending['candidate']);identifier=candidate.get('video_id','')
    candidate['url']='https://www.youtube.com/watch?'+urlencode({'v':identifier})
    authorized_context=bool(pending.get('result_set_id') and pending.get('authorization') in ('context_candidate','title_only'))
    if not re.fullmatch(r'[\w-]{11}',identifier) or not candidate.get('title') or not authorized_context and not individual(candidate,''):
        raise ValueError('A escolha pendente não contém um vídeo musical válido. Faça uma nova busca.')
    _check(cancelled)
    gate=_manual_gate(page)
    if gate:raise ValueError(gate)
    if require_login and not authentication_state(page)['authenticated']:
        raise ValueError('Entre na sua conta do YouTube antes de reproduzir a escolha confirmada.')
    parsed=urlparse(page.url)
    already_open=parsed.path=='/watch' and parse_qs(parsed.query).get('v')==[identifier]
    if not already_open and not authorized_context:
        if page.url!=pending['search_url']:raise ValueError('A página da escolha mudou. Faça uma nova busca; não selecionei outro vídeo.')
        current=next((row for row in _candidates(page,pending['query']) if row['video_id']==identifier),None)
        if not current or normalized(current['title'])!=normalized(candidate['title']) or normalized(current.get('channel',''))!=normalized(candidate.get('channel','')):
            raise ValueError('O resultado oferecido mudou ou saiu da página. Faça uma nova busca; não escolhi outro vídeo.')
    _check(cancelled);before_play();_check(cancelled)
    if session is not None:
        session.query=pending['query'];session.require_login=require_login;session.queue=[candidate];session.index=0
    if not already_open:
        progress({'stage':'video_selected','candidate':candidate,'result_set_id':pending.get('result_set_id',''),'source_task_id':pending.get('source_task_id',''),
            'message':'Usando a escolha que o Senhor confirmou: '+candidate['title']+'.'})
        progress({'stage':'opening_video','candidate':candidate,'result_set_id':pending.get('result_set_id',''),'message':'Abrindo o vídeo autorizado.'})
        page.goto(candidate['url'],wait_until='domcontentloaded')
    _check(cancelled)
    result=_confirm_playback(page,candidate,cancelled,session,progress=progress)
    result.update(selected_candidate=candidate,confirmation_id=pending['id'],selection_source='user_confirmation',
        effective_query=pending['query'],search_completed=False,video_selected=True,
        youtube_authenticated=True if require_login else None)
    if result.get('verified') and not result.get('player_muted'):result['spoken_message']='Senhor, estou reproduzindo '+candidate['title']+'.'
    return result


def _confirm_playback(page,selected,cancelled,session=None,progress=lambda value:None):
    url='https://www.youtube.com/watch?'+urlencode({'v':selected['video_id']})
    deadline=time.monotonic()+25
    baseline=None; requested_play=False; state={}; preferences_applied=False;ad_reported=False
    while time.monotonic()<deadline:
        _check(cancelled,page)
        state=player_state(page)
        if state.get('error'):
            return {'verified':False,'stage':'video_unavailable','playback_confirmed':False,'url':url,'title':selected['title'],
                'message':'Senhor, o YouTube abriu a faixa, mas informou: '+state['error'][:350]}
        if state.get('ad'):
            if not ad_reported:progress({'stage':'advertisement','message':'O YouTube está exibindo um anúncio; aguardando a música.'});ad_reported=True
            baseline=None
            skip=page.locator('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern').first
            if skip.count() and skip.is_visible(): skip.click(timeout=2000)
        elif state.get('exists') and state.get('video_id')==selected['video_id']:
            if session is not None and not preferences_applied:
                _preferences(page,session.volume,session.muted);preferences_applied=True
            if state.get('paused') and not requested_play:
                control=page.locator('button.ytp-play-button').first
                if control.count() and control.is_visible():
                    control.click(timeout=3000)
                    # Autoplay can start between observation and click; finish
                    # with idempotent play so a toggle cannot leave it paused.
                    page.evaluate("async () => { const v=document.querySelector('video'); if(v) await v.play().catch(()=>{}); }")
                    requested_play=True
            if not state.get('paused') and state.get('ready',0)>=2:
                if baseline is None: baseline=state['time']
                same_video=state.get('video_id')==selected['video_id']
                if same_video and state['time']-baseline>=.3:
                    _check(cancelled,page)
                    silent=state.get('muted') or state.get('volume',0)==0
                    progress({'stage':'playing','message':'Reprodução iniciada.' if not silent else 'Reprodução iniciada com o player sem som.'})
                    return {'verified':True,'stage':'playing','playback_confirmed':True,'url':url,'title':state.get('title') or selected['title'],
                        'video_id':selected['video_id'],'position_seconds':round(state['time'],2),
                        'player_muted':silent,
                        'message':'Senhor, reprodução confirmada no YouTube: '+(state.get('title') or selected['title'])+'.'+(' O player está sem som.' if silent else ''),
                        'spoken_message':'Senhor, a reprodução iniciou, mas o player está sem som.' if silent else 'Senhor, a música está tocando no YouTube.'}
            else: baseline=None
        page.wait_for_timeout(250)
    mismatch=bool(state.get('exists') and state.get('video_id') and state['video_id']!=selected['video_id'] and not state.get('ad'))
    reason='O vídeo do player não corresponde à escolha autorizada.' if mismatch else 'Há um anúncio em andamento.' if state.get('ad') else 'O player ainda não iniciou ou está aguardando carregamento.'
    return {'verified':False,'stage':'playback_identity_mismatch' if mismatch else 'advertisement' if state.get('ad') else 'autoplay_or_loading','playback_confirmed':False,'url':url,'title':selected['title'],
        'message':'Senhor, abri '+selected['title']+', mas ainda não confirmei a reprodução. '+reason}
