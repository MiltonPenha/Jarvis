"""One controller for authorized Chrome tabs or an explicitly isolated profile."""
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
import ipaddress
from pathlib import Path
import re
import socket
import threading
import unicodedata
import uuid
import time
import json
from urllib.parse import urlencode, urlparse
from core.config import config
from core.chrome_session import browser_settings,connection_status


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text).casefold()) if unicodedata.category(c)!='Mn')


def public_url(url):
    if not url.startswith(('https://','http://')): url='https://'+url
    parsed=urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Informe um endereço HTTP/HTTPS público, sem credenciais.')
    if parsed.port not in (None,80,443): raise ValueError('O navegador aceita apenas portas web públicas.')
    try: addresses=socket.getaddrinfo(parsed.hostname,parsed.port or 443,type=socket.SOCK_STREAM)
    except OSError as exc: raise ValueError('Não consegui localizar esse site.') from exc
    if any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise PermissionError('Endereços locais ou privados não são destinos deste navegador.')
    return url


class BrowserControl:
    def __init__(self, profile=None, headless=False, mute_audio=False, mode=None):
        self.profile=Path(profile or config.DATA_DIR/'browser-profile')
        self.headless=headless
        self.mute_audio=mute_audio
        self.mode=mode or ('isolated' if profile is not None or headless else browser_settings()['mode'])
        self.browser=None
        self.connected_profile=''
        self.managed_pages=set()
        self.progress=lambda value:None
        self.refs_version=0
        self.observations={}
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='jarvis-browser')
        self.context=None; self.playwright=None; self.page=None; self.refs=[]; self.refs_url=''
        self.closing=threading.Event()
        self._pump_scheduled=False
        self.tabs={}
        self.media_sessions={}
        self.refs_page=None
        self._media_observation=None
        self._media_observation_tab=''
        self._media_observation_lock=threading.Lock()

    def observe_media(self,tab_id):
        """Read only the already bound player, on its owner thread. Never connect."""
        if not self.context or not tab_id:return {'state':'unavailable','observed':False}
        def read():
            from core.media_control import player_state
            page=self.tabs.get(tab_id)
            if not page or page.is_closed():return {'state':'closed','observed':True}
            state=player_state(page)
            return {**state,'state':'unavailable' if not state['exists'] else 'ended' if state['ended'] else 'paused' if state['paused'] else 'buffering' if state['ready']<2 else 'playing',
                    'observed':True,'observed_at':time.time()}
        # One bounded pending read even if the executor is busy with navigation.
        with self._media_observation_lock:
            if self._media_observation is not None and self._media_observation_tab!=tab_id:
                if not self._media_observation.done():return {'state':'refreshing','observed':False}
                self._media_observation=None
            if self._media_observation is None:
                self._media_observation=self.executor.submit(read);self._media_observation_tab=tab_id
            future=self._media_observation
        try:return future.result(timeout=2)
        except FutureTimeout:return {'state':'refreshing','observed':False}
        except Exception:return {'state':'unavailable','observed':False}
        finally:
            with self._media_observation_lock:
                if self._media_observation is future and future.done():self._media_observation=None

    def execute(self, action, target='', content='', cancelled=lambda:False, context=None, parameters=None, progress=None):
        stopped=threading.Event()
        check=lambda:stopped.is_set() or self.closing.is_set() or cancelled()
        future=self.executor.submit(self._request,action,target,content,check,context,parameters,progress)
        try:
            return future.result(timeout=110 if action=='media' and parameters and parameters.get('check') in ('next','recommendation') else 90 if action in ('youtube_play','play_music','media') else 60 if self.mode=='chrome' and not self.context else 45)
        except FutureTimeout:
            stopped.set();future.cancel()
            raise TimeoutError('O navegador excedeu o tempo limite. A operação foi interrompida.') from None

    def _request(self, action, target, content, cancelled, context=None, parameters=None, progress=None):
        from playwright.sync_api import Error
        callback=progress or (lambda value:None)
        self.progress=lambda value:self._stage(action,value,callback)
        started=time.monotonic()
        for attempt in range(2):
            if cancelled(): raise ValueError('Operação do navegador interrompida.')
            try:
                result=self._tool(parameters,context,cancelled) if context is not None else self._execute(action,target,content,cancelled)
                self.progress({'stage':'action_finished','verified':bool(result.get('verified')),'elapsed_seconds':round(time.monotonic()-started,3)})
                return result
            except Error as exc:
                closed='has been closed' in str(exc) or 'Target closed' in str(exc)
                if not closed:
                    self.progress({'stage':'action_failed','error':str(exc)[:700],'elapsed_seconds':round(time.monotonic()-started,3)})
                    raise
                if self.mode=='chrome' and self.browser and self.browser.is_connected():
                    self.refs=[]
                    if self.page and self.page.is_closed():self.page=None
                else:self._close()
                # Only navigation may recover automatically; clicks and playback
                # are never replayed after an uncertain effect or cancellation.
                if action not in ('browser_open','browser_search') or attempt or cancelled():
                    raise ValueError('A janela do navegador foi fechada. Peça para abrir o site novamente.') from None
            except Exception as exc:
                self.progress({'stage':'action_failed','error':str(exc)[:700],'elapsed_seconds':round(time.monotonic()-started,3)})
                raise

    def tool(self,args,context,cancelled=lambda:False,progress=None):
        return self.execute(args['action'],cancelled=cancelled,context=context,parameters=args,progress=progress)

    def _stage(self,action,value,callback):
        # Public progress is concise; diagnostics keep only path/domain, not
        # search strings, account information or unrelated personal page text.
        from core.safety import file_lock,redact
        url=urlparse(self.page.url) if self.page and not self.page.is_closed() else None
        event={**value,'action':action,'mode':self.mode,'profile':self.connected_profile,
            'tab_id':next((key for key,page in self.tabs.items() if page==self.page),None),
            'url':url.scheme+'://'+url.netloc+url.path if url else '',
            'time':time.time()}
        path=config.DATA_DIR/'logs/browser-events.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
        with file_lock(path):
            if path.exists() and path.stat().st_size>1_000_000:
                path.replace(path.with_suffix('.previous.jsonl'))
            with path.open('a',encoding='utf-8') as stream:stream.write(redact(json.dumps(event,ensure_ascii=False))+'\n')
        callback(value)

    def _live_tabs(self):
        if not self.context: self.tabs.clear();return {}
        pages=[page for page in self.context.pages if not page.is_closed() and (self.mode=='isolated' or page in self.managed_pages)]
        self.tabs={key:page for key,page in self.tabs.items() if page in pages}
        for page in pages:
            if page not in self.tabs.values(): self.tabs[uuid.uuid4().hex[:10]]=page
        return self.tabs

    def _tab_id(self,page):
        return next(key for key,value in self._live_tabs().items() if value==page)

    def _target_identity(self,page):
        """Chrome's observed tab identity survives controller reconnection.

        Uses the already authorized connection, never another CDP client.
        The model cannot supply this identity or use it as a navigation URL.
        """
        if self.mode!='chrome' or not self.context or page.is_closed():return ''
        session=None
        try:
            session=self.context.new_cdp_session(page)
            identifier=session.send('Target.getTargetInfo')['targetInfo']['targetId']
            return identifier if isinstance(identifier,str) and re.fullmatch(r'[a-fA-F0-9]{32}',identifier) else ''
        except Exception:return ''
        finally:
            if session:
                try:session.detach()
                except Exception:pass

    def _recover_media(self,context):
        """Rebind a restarted conversation to its exact, still-open known video."""
        if self.mode!='chrome' or not self.context:return False
        from core.task_store import TaskStore
        from core.media_control import player_state
        from urllib.parse import parse_qs
        known=TaskStore().last_playback(context.session)
        matches=[]
        for page in self.context.pages:
            if page.is_closed():continue
            parsed=urlparse(page.url)
            if known and parsed.hostname in ('youtube.com','www.youtube.com') and parsed.path=='/watch' and parse_qs(parsed.query).get('v')==[known['video_id']]:matches.append(page)
        if len(matches)==1:
            page=matches[0];state=player_state(page)
            if state.get('count')!=1 or not state.get('exists') or state.get('video_id')!=known['video_id'] or state.get('error'):return False
        else:
            # Cold-start recovery may follow YouTube autoplay. Read only watch
            # players; a unique active video is observable evidence. Ambiguous
            # players stay unbound. Existing invalid bindings never reach here.
            active=[]
            for candidate in self.context.pages:
                if candidate.is_closed():continue
                parsed=urlparse(candidate.url)
                if parsed.hostname not in ('youtube.com','www.youtube.com') or parsed.path!='/watch':continue
                observed=player_state(candidate)
                if observed.get('exists') and observed.get('count')==1 and not observed.get('paused',True) and not observed.get('ad') and not observed.get('error'):
                    active.append((candidate,observed))
            if len(active)!=1:return False
            page,state=active[0]
            if not known or state.get('video_id')!=known['video_id']:context.media_query=''
        placeholder=self.page
        self.managed_pages.add(page);self.page=page
        page.set_default_timeout(8000);page.set_default_navigation_timeout(18000)
        context.media_tab_id=self._tab_id(page);context.media_identity=state['identity'];context.media_invalid=False
        if placeholder is not page and placeholder in self.managed_pages and placeholder.url=='about:blank':
            placeholder.close();self.managed_pages.discard(placeholder)
        return True

    def _media_target(self,context,action):
        from core.media_control import player_state
        tabs=self._live_tabs()
        if context.media_invalid and action!='status':
            raise ValueError('O contexto da mídia ficou inválido. Consulte a música atual, selecione uma aba ou peça nova reprodução.')
        if context.media_tab_id:
            page=tabs.get(context.media_tab_id)
            if page is None:
                context.media_tab_id='';context.media_identity=''
                context.media_invalid=True
                raise ValueError('A aba da reprodução foi fechada. Não controlei outro player. Peça uma música ou selecione uma aba.')
        else:
            candidates=[]
            for key,page in tabs.items():
                state=player_state(page)
                if state['exists']: candidates.append((key,page))
            if not candidates and self._recover_media(context):
                tabs=self._live_tabs();candidates=[(context.media_tab_id,tabs[context.media_tab_id])]
            if len(candidates)!=1:
                raise ValueError('Selecione a aba da mídia antes de controlar: '+(', '.join(key+': '+page.title()[:70] for key,page in candidates) or 'nenhuma reprodução encontrada')+'.')
            context.media_tab_id,page=candidates[0]
        state=player_state(page)
        if not state['exists'] or state['count']!=1:
            raise ValueError('O player foi removido ou há múltiplas reproduções nesta aba. Selecione uma reprodução única.')
        if context.media_identity and context.media_identity!=state['identity'] and action not in ('status','suggestions'):
            raise ValueError('A reprodução mudou fora do controle do JARVIS. Consulte qual música está tocando ou selecione a aba antes de controlar.')
        context.media_identity=state['identity']
        context.media_invalid=False
        return page,state

    def _music_page(self,context):
        """Prefer the controlled search/player, including a failed search page."""
        from urllib.parse import parse_qs
        def youtube(page):return page and not page.is_closed() and urlparse(page.url).hostname in ('youtube.com','www.youtube.com')
        tabs=self._live_tabs()
        for identifier in (context.media_tab_id,context.tab_id):
            if youtube(tabs.get(identifier)):return tabs[identifier]
        known=[tabs[key] for key in self.media_sessions if key in tabs and youtube(tabs[key])]
        if len(known)==1:return known[0]
        pages=[page for page in self.context.pages if youtube(page)]
        goal=context.music_goal
        search=goal.get('last_search_query') or goal.get('query')
        matches=[page for page in pages if page.url==goal.get('tab_url') or search and parse_qs(urlparse(page.url).query).get('search_query')==[search]]
        if len(matches)!=1:
            from core.task_store import TaskStore
            playback=TaskStore().last_playback(context.session)
            matches=[page for page in pages if playback and parse_qs(urlparse(page.url).query).get('v')==[playback['video_id']]]
        if len(matches)==1:page=matches[0]
        elif len(pages)==1:page=pages[0]
        elif len(pages)>1:raise ValueError('Há várias abas do YouTube e perdi a referência da música. Selecione a aba antes de pesquisar; não abri outra.')
        else:page=self.page if self.page and not self.page.is_closed() and self.page.url=='about:blank' else self._new_page()
        self.managed_pages.add(page);page.set_default_timeout(8000);page.set_default_navigation_timeout(18000)
        return page

    def _respond_music_confirmation(self,args,context,cancelled):
        from core.music_followup import confirmation_pending
        from core.media_control import MediaSession,player_state
        from core.youtube_control import confirm_youtube
        from urllib.parse import parse_qs
        pending=dict(context.music_goal.get('confirmation',{}))
        if args.get('query')!=pending.get('id') or pending.get('session')!=context.session or not confirmation_pending(pending):
            raise ValueError('Essa escolha não está mais aguardando confirmação nesta conversa. Não iniciei outra busca.')
        record=context.record_music_confirmation
        if not record:raise ValueError('Não consegui registrar a confirmação. Nenhuma reprodução foi iniciada.')
        def transition(state):
            pending['state']=state;record(pending)
        claimed=False
        if cancelled():raise ValueError('Confirmação cancelada antes da reprodução.')
        if args['check']=='reject_music':
            transition('rejected');context.pending_music_query=''
            return {'verified':True,'stage':'confirmation_rejected','playback_confirmed':False,'music_goal':context.music_goal,
                    'message':'Senhor, descartei essa escolha. Qual música deseja ouvir?'}
        try:
            self._start()
            identifier=pending['candidate']['video_id']
            def matches(page):
                if page.is_closed():return False
                parsed=urlparse(page.url)
                return parsed.hostname in ('youtube.com','www.youtube.com') and (page.url==pending['search_url'] or parsed.path=='/watch' and parse_qs(parsed.query).get('v')==[identifier])
            pages=[page for page in self.context.pages if matches(page)]
            bound=self._live_tabs().get(pending.get('tab_id'))
            contextual=bool(pending.get('result_set_id') and pending.get('result_set_id')==context.music_goal.get('result_set',{}).get('id') and pending.get('authorization') in ('context_candidate','title_only'))
            if contextual and pending.get('target_id'):
                if not bound or self._target_identity(bound)!=pending['target_id']:
                    exact=[page for page in self.context.pages if not page.is_closed() and self._target_identity(page)==pending['target_id']]
                    bound=exact[0] if len(exact)==1 else None
            if contextual and bound in self.context.pages and not bound.is_closed():page=bound
            elif bound in pages:page=bound
            elif len(pages)==1:page=pages[0]
            else:raise ValueError('A aba da escolha foi fechada ou está ambígua. Selecione a aba desejada; mantive a escolha e não abri outra aba.')
            self.page=page;self.managed_pages.add(page)
            context.tab_id=self._tab_id(page);context.media_tab_id=context.tab_id
            session=self.media_sessions.setdefault(context.tab_id,MediaSession())
            def claim():
                nonlocal claimed
                current=context.music_goal.get('confirmation',{})
                if cancelled() or current.get('id')!=pending['id'] or current.get('state')!='pending':
                    raise ValueError('A escolha foi substituída antes de iniciar a reprodução.')
                transition('executing')  # Durable before the first playback effect.
                claimed=True
            result=confirm_youtube(page,pending,cancelled,session,require_login=self.mode=='chrome' or not self.headless,progress=self.progress,before_play=claim)
            transition('consumed' if result.get('verified') else 'failed')
            context.media_identity=player_state(page)['identity'];context.media_invalid=False
            if result.get('verified'):
                context.media_query=pending['query'];context.pending_music_query=''
                context.music_goal.update(last_video_id=result['video_id'],confirmed_title=result['title'],tab_url=page.url)
            result.update(tab_id=context.tab_id,tab_url=page.url,music_goal=context.music_goal)
            return result
        except Exception as exc:
            if cancelled():transition('cancelled')
            elif claimed:transition('failed')
            else:
                pending['last_error']=str(exc)[:400];record(pending)
            if pending.get('authorization') in ('context_candidate','title_only'):
                return {'verified':False,'stage':'candidate_playback_failed' if claimed else 'candidate_page_changed','playback_confirmed':False,
                    'selected_candidate':pending['candidate'],'title':pending['candidate']['title'],'music_goal':context.music_goal,
                    'error_type':type(exc).__name__,'message':'Senhor, não consegui '+('reproduzir essa mídia já identificada.' if claimed else 'identificar a aba dessa mídia. Selecione a aba desejada para continuar.')+' A escolha foi preservada; não iniciei outra busca.'}
            raise

    def _tool(self,args,context,cancelled):
        from core.media_control import MediaSession,player_state,control,adjust_volume
        action=args['action'];target=args.get('query','');content=args.get('content','')
        if action=='browser_connect':
            self._start()
            return {'verified':True,'stage':'chrome_connected','profile':self.connected_profile,'mode':self.mode,
                'message':'Senhor, conectado ao seu Chrome.' if self.mode=='chrome' else 'Senhor, conectado ao perfil separado escolhido.'}
        if action=='media' and args.get('check') in ('confirm_music','reject_music'):
            return self._respond_music_confirmation(args,context,cancelled)
        if action in ('media','volume'):
            operation=args.get('check',args.get('mode','status'))
            page,before=self._media_target(context,operation)
            session=self.media_sessions.setdefault(context.media_tab_id,MediaSession())
            value=args.get('value')
            result=adjust_volume(page,operation,value,session,cancelled) if action=='volume' else control(page,operation,session,cancelled,value,progress=self.progress,
                request=args.get('query') or context.task,select=context.select_music,context=context.compact())
            context.media_identity=player_state(page)['identity']
            result['tab_id']=context.media_tab_id
            return result
        if action=='browser_tabs':
            rows=[{'id':key,'title':page.title(),'url':page.url,'selected':key==context.tab_id}
                for key,page in self._live_tabs().items() if normalized(target) in normalized(page.title()+' '+page.url)]
            return {'verified':True,'tabs':rows,'message':'Senhor, abas do JARVIS:\n'+'\n'.join(row['id']+': '+row['title'] for row in rows)}
        if action=='browser_select':
            if target.startswith(('https://','http://')):
                from urllib.parse import parse_qs
                parsed=urlparse(target);video=parse_qs(parsed.query).get('v',[''])[0]
                if parsed.hostname not in ('youtube.com','www.youtube.com') or parsed.path!='/watch' or not re.fullmatch(r'[\w-]{11}',video):
                    raise ValueError('Informe o ID de uma aba ou o endereço de um vídeo do YouTube.')
                matches=[p for p in self.context.pages if not p.is_closed() and urlparse(p.url).hostname in ('youtube.com','www.youtube.com') and parse_qs(urlparse(p.url).query).get('v')==[video]] if self.context else []
                if len(matches)!=1:raise ValueError('Não encontrei uma única aba desse vídeo na sessão conectada. Confira o perfil do Chrome e liste as abas.')
                page=matches[0];self.managed_pages.add(page);target=self._tab_id(page)
            else:page=self._live_tabs().get(target)
            if page is None: raise ValueError('Aba inexistente ou fechada. Consulte as abas novamente.')
            self.page=page;context.tab_id=target;page.bring_to_front()
            state=player_state(page)
            if state['exists'] and state['count']==1:
                context.media_tab_id=target;context.media_identity=state['identity']
                context.media_invalid=False
            return self._snapshot()
        if action not in ('browser_open','browser_search','play_music','browser_close'):
            page=self._live_tabs().get(context.tab_id)
            if not page: raise ValueError('A aba selecionada foi fechada ou não existe. Consulte as abas ou abra um site.')
            self.page=page
        else:
            page=self._live_tabs().get(context.tab_id)
            if page: self.page=page
        if action=='play_music':
            from core.youtube_control import play_youtube
            self._start()
            self.page=self._music_page(context)
            context.tab_id=self._tab_id(self.page);context.media_tab_id=context.tab_id
            context.media_invalid=False
            session=self.media_sessions.setdefault(context.tab_id,MediaSession())
            if context.interpret_music and not context.music_intent:
                context.music_intent=context.interpret_music(context.task,context.compact())
            if context.music_intent:
                from core.music_intent import question
                if not context.music_intent.get('accepted'):return {'verified':False,'message':question(context.music_intent),'music_intent':context.music_intent}
                target=context.music_intent['query']
            result=play_youtube(self.page,target,cancelled,session,require_login=self.mode=='chrome' or not self.headless,progress=self.progress,resolve=context.resolve_music,record_query=context.record_music_query,select_result=context.select_music_result,goal=context.music_goal or context.music_intent)
            if cancelled() or context.music_task and context.music_goal.get('task_id')!=context.music_task:
                raise ValueError('A pesquisa foi substituída por um pedido mais recente.')
            if context.music_intent:result['music_intent']=context.music_intent
            result['tab_url']=self.page.url
            context.music_goal.update(tab_url=self.page.url,last_search_query=result.get('effective_query',target),
                observed=result.get('observed_results',[])[:14])
            if result.get('result_set'):
                context.music_goal['result_set']={**result['result_set'],'tab_id':context.tab_id,'target_id':self._target_identity(self.page)}
            if result.get('selected_candidate'):context.music_goal['selected_candidate']=result['selected_candidate']
            if result.get('resolved_content'):context.music_goal['resolved_query']=result['resolved_content']
            if result.get('transcription_corrections'):context.music_goal['observed_corrections']=result['transcription_corrections']
            if result.get('video_id'):context.music_goal['last_video_id']=result['video_id']
            if result.get('verified'):context.music_goal['confirmed_title']=result.get('title','')
            if result.get('music_confirmation'):
                context.music_goal['confirmation']={**result['music_confirmation'],'session':context.session,'tab_id':context.tab_id,
                    'result_set_id':(result.get('result_set') or {}).get('id','')}
            result['music_goal']=context.music_goal
            context.media_identity=player_state(self.page)['identity']
            if result.get('verified'):
                context.media_query=result.get('effective_query',target);context.pending_music_query=''
            else:context.pending_music_query=target
            result['tab_id']=context.tab_id
            return result
        if action in ('browser_open','browser_search') and self.page and not self.page.is_closed():
            # Ordinary navigation preserves an already controlled media tab.
            if any(page==self.page and key in self.media_sessions for key,page in self._live_tabs().items()):
                self.page=self._new_page()
        if action=='browser_wait':
            condition=args['condition'];deadline=time.monotonic()+8
            baseline=player_state(self.page)['time'] if condition=='playback' else 0
            while time.monotonic()<deadline:
                if cancelled(): raise ValueError('Espera cancelada.')
                ready=(self.page.evaluate('document.readyState') in ('interactive','complete') if condition=='ready' else
                    target in self.page.locator('body').inner_text(timeout=2000) if condition=='text' else
                    self._find(target)['element'].is_visible() if condition=='element' else
                    (lambda state:state['exists'] and not state['paused'] and state['ready']>=2 and not state['ad'] and state['time']-baseline>.15)(player_state(self.page)))
                if ready: return {'verified':True,'condition':condition,'message':'Senhor, condição observada: '+condition}
                self.page.wait_for_timeout(120)
            return {'verified':False,'message':'Senhor, a condição solicitada não foi observada em 8 segundos.'}
        result=self._snapshot() if action=='browser_state' else self._execute(action,target,content,cancelled)
        if self.page and not self.page.is_closed(): context.tab_id=self._tab_id(self.page);result['tab_id']=context.tab_id
        return result

    def _queue_pump(self):
        if self.context and not self.closing.is_set() and not self._pump_scheduled:
            self._pump_scheduled=True
            try: self.executor.submit(self._pump)
            except RuntimeError: self._pump_scheduled=False

    def _pump(self):
        self._pump_scheduled=False
        if not self.context or self.closing.is_set(): return
        try:
            pages=[page for page in self.context.pages if not page.is_closed() and (self.mode=='isolated' or page in self.managed_pages)]
            if not pages:
                if self.mode=='isolated':self._close()
                return
            # Sync Playwright dispatches network routes only while inside its
            # event loop. Keep media, navigation and close events alive at idle.
            pages[0].wait_for_timeout(100)
        except Exception:
            if self.mode=='chrome' and self.browser and self.browser.is_connected():
                # Closing a managed tab must not detach the authorized browser.
                # The next navigation can create another tab in this context.
                if self.page and self.page.is_closed():self.page=None
                self._queue_pump();return
            self._close();return
        self._queue_pump()

    def _start(self):
        if self.context:
            try:
                pages=[page for page in self.context.pages if not page.is_closed() and (self.mode=='isolated' or page in self.managed_pages)]
                if pages:
                    candidate=self.page if self.page in pages else pages[-1]
                    if self.mode=='isolated':candidate.evaluate('document.readyState')
                    self.page=candidate
                    self._queue_pump();return
                if self.mode=='chrome' and self.browser and self.browser.is_connected():
                    self.page=self._new_page();self._queue_pump();return
            except Exception: pass
            self._close()
        from playwright.sync_api import sync_playwright
        if not self.playwright: self.playwright=sync_playwright().start()
        if self.mode=='chrome':
            status=connection_status()
            if status['endpoint']=='chrome' and not status['authorization_available']:
                raise ValueError('Senhor, autorize a conexão ao seu Chrome em Configurações → Navegador → Autorizar no Chrome. Nenhum perfil separado foi aberto.')
            self.progress({'stage':'connecting','message':'Conectando ao seu Chrome.'})
            try:
                self.browser=self.playwright.chromium.connect_over_cdp(status['resolved_endpoint'],no_defaults=True,timeout=30000)
                self.context=self.browser.contexts[0]
                # Verify the connected profile from Chrome itself, not from Google
                # account sync state. Only this temporary diagnostic tab is closed.
                probe=self.context.new_page()
                try:
                    probe.goto('chrome://version/',wait_until='domcontentloaded',timeout=8000)
                    self.connected_profile=Path(probe.locator('#profile_path').inner_text(timeout=3000).strip()).name
                finally:probe.close()
                if self.connected_profile!=status['profile']:
                    self._close()
                    raise ValueError('Senhor, o Chrome autorizou outro perfil. Selecione o perfil correto em Configurações → Navegador e autorize a conexão nele.')
                # Reuse a unique YouTube tab only. Other personal tabs are not
                # enrolled, routed, modified or included in browser observations.
                youtube=[page for page in self.context.pages if not page.is_closed() and (urlparse(page.url).hostname or '') in ('www.youtube.com','youtube.com')]
                self.page=youtube[0] if youtube else self.context.new_page()
                self.managed_pages.add(self.page)
                self.page.set_default_timeout(8000);self.page.set_default_navigation_timeout(18000)
                self._queue_pump();return
            except ValueError:raise
            except Exception as exc:
                self._close()
                raise ValueError('Senhor, não consegui conectar ao seu Chrome. Aceite a autorização no navegador e tente Conectar novamente. Suas janelas foram preservadas.') from exc
        self.profile.mkdir(parents=True,exist_ok=True)
        # Own profile: no attachment to another browser, no remote debugging port.
        self.context=self.playwright.chromium.launch_persistent_context(str(self.profile),channel='chrome',
            headless=self.headless,locale='pt-BR',accept_downloads=False,chromium_sandbox=True,
            args=['--disable-gpu','--disable-dev-shm-usage']+(['--mute-audio'] if self.mute_audio else []),viewport={'width':1200,'height':800})
        self.context.set_default_timeout(8000)
        self.context.set_default_navigation_timeout(18000)
        self.context.route('**/*', self._route)
        self.page=self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.on('dialog',lambda dialog:dialog.dismiss())
        self._queue_pump()

    def _new_page(self):
        page=self.context.new_page();self.managed_pages.add(page)
        page.set_default_timeout(8000);page.set_default_navigation_timeout(18000)
        return page

    def _route(self, route):
        url=route.request.url
        parsed=urlparse(url)
        # Block local resources, network pivots and downloads, including redirects.
        try:
            if parsed.scheme in ('http','https'):
                public_url(url)
            elif parsed.scheme not in ('data','blob','about'):
                raise PermissionError('Protocolo bloqueado.')
            route.continue_()
        except Exception:
            route.abort()

    def _snapshot(self):
        self.refs=[]
        if not self.page or self.page.is_closed(): raise ValueError('A página foi fechada. Diga: abrir Google.')
        title=self.page.title()
        self.refs_url=self.page.url
        self.refs_page=self.page
        self.refs_version+=1
        self.ref_dom=self._dom_version()
        if '/sorry/' in self.page.url and 'google.' in urlparse(self.page.url).netloc:
            return {'verified':True,'url':self.page.url,'title':'Verificação do Google','elements':[],
                'needs_manual_verification':True,'message':'Senhor, o Google pediu uma verificação humana. Resolva-a na janela do navegador do JARVIS e depois peça para listar a página. A pesquisa ainda não foi confirmada.'}
        # Google result headings identify real search results separately from navigation links.
        selectors='a:has(h3)' if 'google.' in urlparse(self.page.url).netloc and '/search' in self.page.url else 'a, button, input, textarea, select'
        elements=self.page.locator(selectors)
        for element in elements.element_handles()[:250]:
            if len(self.refs)>=35: break
            try:
                if not element.is_visible(): continue
                info=element.evaluate("e => ({tag:e.tagName.toLowerCase(), label:e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.innerText||e.getAttribute('name')||'', href:e.href||'', type:e.type||''})")
                label=re.sub(r'\s+',' ',info['label']).strip()[:160]
                if not label: continue
                if re.match(r'(?i)^(?:conta do google|google account)\s*:',label):continue
                self.refs.append({'element':element,'label':label,'tag':info['tag'],'href':info['href'],'type':info['type']})
            except Exception: continue
        self.ref_dom=self._dom_version()
        tab=self._tab_id(self.page)
        links=[{'id':f'{tab}:v{self.refs_version}:{i+1}','label':row['label'],'type':row['tag']} for i,row in enumerate(self.refs)]
        self.observations[self.refs_version]={'tab':tab,'url':self.refs_url,'rows':[
            {key:row[key] for key in ('label','tag','href','type')} for row in self.refs]}
        if len(self.observations)>12:self.observations.pop(next(iter(self.observations)))
        return {'verified':True,'url':self.page.url,'title':title,'elements':links,
            'observation':self.refs_version,'tab_id':tab,
            'message':'Senhor, página aberta: '+title+'.'}

    def _dom_version(self):
        return self.page.evaluate('''() => {
            if(!window.__jarvisObservation) {
                const state={id:globalThis.crypto?.randomUUID?.()||String(performance.timeOrigin),version:0};
                new MutationObserver(()=>state.version++).observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden','aria-hidden','href','aria-label','disabled']});
                window.__jarvisObservation=state;
            }
            return [window.__jarvisObservation.id,window.__jarvisObservation.version];
        }''')

    def _find(self, target, action='browser_click'):
        # Resolve stale references by their observed meaning, never by the new
        # position of an old index. Cross-tab numeric references cannot migrate.
        reference=re.fullmatch(r'(?:([a-f0-9]+):v(\d+):)?(\d+)',target)
        remembered=None
        if reference:
            index=int(reference[3])-1
            if reference[1] and reference[1]!=self._tab_id(self.page):
                self._snapshot();raise ValueError('A aba mudou; a referência antiga pertence a outra aba.')
            if self.refs_page and self.page!=self.refs_page:
                self._snapshot();raise ValueError('A aba mudou; a referência antiga não será usada em outra aba.')
            if reference[2] and int(reference[2])!=self.refs_version:
                previous=self.observations.get(int(reference[2]))
                if not previous or previous['tab']!=self._tab_id(self.page) or previous['url']!=self.page.url or not 0<=index<len(previous['rows']):
                    self._snapshot();raise ValueError('A referência expirou após mudar de página. Nenhuma ação foi enviada.')
                remembered=previous['rows'][index]
                self._snapshot()
            elif 0<=index<len(self.refs):remembered=self.refs[index]
            else:raise ValueError('A referência não pertence à observação atual. A página foi observada novamente.')
            if self.page.url!=self.refs_url:
                self._snapshot();raise ValueError('A página mudou; a referência anterior não será usada em outro documento.')
        for attempt in range(2):
            if not self.refs or self.page.url!=self.refs_url or self._dom_version()!=getattr(self,'ref_dom',None) or attempt:
                self._snapshot()
            if remembered:
                matches=[row for row in self.refs if row['label']==remembered['label'] and row['tag']==remembered['tag'] and row['href']==remembered['href']]
            else:
                matches=[row for row in self.refs if normalized(target)==normalized(row['label'])]
                if not matches:matches=[row for row in self.refs if normalized(target) in normalized(row['label']+' '+row['href'])]
            if action in ('browser_fill','browser_enter'):matches=[row for row in matches if row['tag'] in ('input','textarea')]
            live=[]
            for row in matches:
                try:
                    if row['element'].is_visible() and row['element'].is_enabled() and row['element'].evaluate('e=>e.isConnected'):live.append(row)
                except Exception:pass
            # Equivalent duplicated navigation links are safe to narrow to one
            # visible destination. Different destinations remain an internal error.
            if len(live)>1 and all(row['href'] and row['href']==live[0]['href'] for row in live):live=live[:1]
            if len(live)==1:
                live[0]['element'].wait_for_element_state('stable',timeout=2000)
                return live[0]
        self.progress({'stage':'element_resolution_failed','message':'Não consegui localizar o controle na página atual após atualizar a observação.'})
        raise ValueError('Não consegui localizar um controle único e visível na página atual após duas observações. Nenhum clique foi enviado.')

    def _execute(self, action, target, content, cancelled=lambda:False):
        if cancelled(): raise ValueError('Operação do navegador interrompida.')
        if action=='browser_close':
            shared=self.mode=='chrome'
            self._close(); return {'verified':True,'message':'Senhor, desconectei o JARVIS do Chrome. Suas janelas continuam abertas.' if shared else 'Senhor, o navegador do JARVIS foi fechado.'}
        if action=='browser_connect':
            self._start();return {'verified':True,'stage':'chrome_connected','profile':self.connected_profile,'mode':self.mode,'message':'Senhor, conectado ao seu Chrome.'}
        if action not in ('browser_open','browser_search','browser_read','browser_click','browser_fill','browser_back','browser_scroll','browser_enter','youtube_play'):
            raise ValueError('Ação de navegador desconhecida.')
        if action not in ('browser_open','browser_search','youtube_play') and (not self.context or not self.page or self.page.is_closed()):
            raise ValueError('Abra uma página pelo JARVIS primeiro. O controle usa a janela própria do assistente.')
        self._start()
        if cancelled(): raise ValueError('Operação do navegador interrompida.')
        if self.page.is_closed(): self.page=self._new_page()
        if action=='youtube_play':
            from core.youtube_control import play_youtube
            return play_youtube(self.page,target,cancelled,require_login=self.mode=='chrome' or not self.headless,progress=self.progress)
        if action=='browser_open':
            target={'google':'https://www.google.com','youtube':'https://www.youtube.com','github':'https://github.com'}.get(target.casefold(),target)
            self.page.goto(public_url(target),wait_until='domcontentloaded')
        elif action=='browser_search':
            if not target.strip(): raise ValueError('Informe o que pesquisar.')
            self.page.goto('https://www.google.com/search?'+urlencode({'q':target,'hl':'pt-BR'}),wait_until='domcontentloaded')
        elif action=='browser_back':
            self.page.go_back(wait_until='domcontentloaded')
        elif action=='browser_scroll':
            self.page.mouse.wheel(0,-650 if normalized(target) in ('cima','up','subir') else 650)
        elif action in ('browser_fill','browser_enter','browser_click'):
            if cancelled(): raise ValueError('Operação do navegador interrompida.')
            if not self.refs: self._snapshot()
            row=self._find(target,action)
            if action=='browser_fill':
                if row['tag'] not in ('input','textarea') or row['type'] in ('password','file','hidden'):
                    raise PermissionError('Selecione um campo de texto comum. Senhas e anexos são manuais.')
                row['element'].fill(content)
                return {'verified':row['element'].input_value()==content,'message':'Senhor, campo preenchido. Nenhum formulário foi enviado.'}
            if action=='browser_enter':
                if row['type']!='search' and normalized(row['label']) not in ('pesquisar','pesquisa','search','q'):
                    raise PermissionError('Enter automático é permitido apenas em campos de pesquisa.')
                row['element'].press('Enter')
            else:
                if row['tag']!='a' or not row['href']:
                    # Ordinary reading/navigation controls; no generic form submission.
                    allowed=('proximo','anterior','menu','mais resultados','play','reproduzir','pausar','aceitar todos','rejeitar todos')
                    if normalized(row['label']) not in allowed:
                        raise PermissionError('Este controle exige interação manual; use links ou campos de pesquisa.')
                elif not row['href'].startswith('#'):
                    public_url(row['href'])
                    if re.search(r'(?i)(logout|signout|delete|remove|checkout|purchase|comprar|excluir|apagar)',row['href']+' '+row['label']):
                        raise PermissionError('Essa ação exige interação manual.')
                if row['tag']=='a' and row['href']:
                    self.page.goto(public_url(row['href']),wait_until='domcontentloaded')
                else:
                    row['element'].click()
        if action=='browser_read':
            result=self._snapshot()
            text=self.page.locator('body').inner_text(timeout=8000)[:4500]
            result['message']='Senhor, conteúdo de '+result['title']+':\n'+text+'\n\nElementos:\n'+'\n'.join(f"{r['id']}. {r['label']}" for r in result['elements'])
            return result
        try: self.page.wait_for_load_state('domcontentloaded',timeout=5000)
        except Exception: pass
        return self._snapshot()

    def _close(self):
        if self.context and self.mode=='isolated':
            try: self.context.close()
            except Exception: pass
        self.context=None; self.page=None; self.refs=[]
        self.tabs.clear();self.media_sessions.clear();self.refs_page=None
        self.managed_pages.clear();self.browser=None;self.connected_profile=''
        self.observations.clear()
        if self.playwright:
            self.playwright.stop(); self.playwright=None

    def close(self):
        self.closing.set()
        try: self.executor.submit(self._close).result(timeout=15)
        finally: self.closing.clear()


browser_control=BrowserControl()
