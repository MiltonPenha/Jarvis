"""Observed HTML media controls, plus the existing YouTube search adapter.

Only the owned browser can call these functions; no global play/pause toggles.
"""
from dataclasses import dataclass,field
import time
import re
import hashlib
from urllib.parse import parse_qs,urlparse,urlencode


@dataclass
class MediaSession:
    queue:list=field(default_factory=list)
    index:int=-1
    volume:int|None=None
    muted:bool|None=None
    query:str=''
    require_login:bool=False


def player_state(page):
    state=page.evaluate('''() => {
        const player=document.querySelector('#movie_player');
        const videos=player?[player.querySelector('video')].filter(Boolean):[...document.querySelectorAll('video,audio')];
        const video=videos[0], data=player?.getVideoData?.()||{};
        const error=document.querySelector('.ytp-error-content-wrap');
        const level=player?.getVolume?.();
        return {exists:!!video, count:videos.length, paused:video?.paused??true, ended:video?.ended??false,
            time:video?.currentTime||0, ready:video?.readyState||0,
            muted:!!player?.isMuted?.()||!!video?.muted,
            volume:typeof level==='number'&&Number.isFinite(level)?level/100:video?.volume??0,
            ad:!!player?.classList.contains('ad-showing'), video_id:data.video_id||'',
            identity:data.video_id||video?.currentSrc||video?.src||'',
            title:data.title||navigator.mediaSession?.metadata?.title||document.title,
            origin:location.origin,error:error&&error.getClientRects().length?error.innerText:''};
    }''')
    if not state['video_id']:
        state['identity']=hashlib.sha256(state['identity'].encode()).hexdigest() if state['identity'] else ''
    return state


def preferences(page,volume=None,muted=None):
    page.evaluate('''args => {
        const player=document.querySelector('#movie_player'), video=player?.querySelector('video')||document.querySelector('video,audio');
        if(!video) throw Error('Player não encontrado.');
        // YouTube unMute can restore/clamp its old level (e.g. 5%). Apply the
        // requested destination last, within the same logical transaction.
        if(args.muted!==null) { if(args.muted) player?.mute?.(); else player?.unMute?.(); video.muted=args.muted; }
        if(args.volume!==null) { if(player?.setVolume) player.setVolume(args.volume); else video.volume=args.volume/100; }
    }''',{'volume':volume,'muted':muted})


def adjust_volume(page,mode,value,session,cancelled):
    from core.volume_control import adjust
    identity=None
    def read():
        nonlocal identity
        state=player_state(page)
        if state.get('count')!=1:raise ValueError('Selecione um único player antes de ajustar o volume.')
        if state.get('error'):raise ValueError('O player informou: '+state['error'][:350])
        if identity is not None and identity!=state['identity']:raise ValueError('A reprodução mudou durante o ajuste de volume.')
        identity=state['identity']
        return {**state,'volume_percent':state['volume']*100}
    result=adjust(mode,value,read,lambda target,muted:preferences(page,target,muted),cancelled)
    result.update(action='volume' if mode in ('absolute','relative','multiply') else mode,
        title=result['state']['title'],origin=result['state']['origin'])
    if result['verified'] and mode!='status':
        session.volume=result['volume_percent'];session.muted=result['muted']
    return result


def control(page,action,session,cancelled,value=None,progress=lambda value:None,request='',select=None,context=None):
    if action in ('volume','mute','unmute'):
        return adjust_volume(page,'absolute' if action=='volume' else action,value,session,cancelled)
    from core.youtube_control import _confirm_playback
    if cancelled(): raise ValueError('Controle de mídia cancelado.')
    before=player_state(page)
    if before.get('count')!=1: raise ValueError('Há múltiplos players nesta página ou o player foi removido. Selecione uma reprodução única.')
    if before.get('error'): raise ValueError('O player informou: '+before['error'][:350])
    if before.get('ad') and action not in ('status','suggestions','pause','volume','mute','unmute'):
        raise ValueError('Há um anúncio em andamento. Aguarde o término antes de retomar ou trocar a faixa.')
    if action=='suggestions':
        from core.youtube_suggestions import snapshot
        snap=snapshot(page,session)
        return {'verified':True,'snapshot':snap,'message':f"Senhor, encontrei {len(snap['recommendations'])} sugestões de vídeo na página."}
    if action in ('next','recommendation') and (urlparse(page.url).hostname or '') in ('youtube.com','www.youtube.com'):
        from core.youtube_suggestions import transition
        return transition(page,session,request or 'Próxima música',select,context or {},cancelled,progress)
    if action in ('next','previous'):
        identifier=before.get('video_id')
        found=next((i for i,row in enumerate(session.queue) if row['video_id']==identifier),None)
        if found is None:
            raise ValueError('Este player não oferece uma fila conhecida para avançar ou voltar. Peça outra música.')
        index=found+(1 if action=='next' else -1)
        if not 0<=index<len(session.queue): raise ValueError('A fila terminou.' if action=='next' else 'Esta é a primeira faixa da fila.')
        selected=session.queue[index]
        if cancelled(): raise ValueError('Troca de faixa cancelada.')
        # A single effect. A timeout never retries this navigation.
        page.goto('https://www.youtube.com/watch?'+urlencode({'v':selected['video_id']}),wait_until='domcontentloaded')
        session.index=index
        progress({'stage':'opening_video','message':'Abrindo o vídeo.'})
        result=_confirm_playback(page,selected,cancelled,session,progress=progress)
        result.update(queue_position=index+1,queue_size=len(session.queue))
        return result
    if action in ('pause','resume','stop'):
        # Resume is idempotent. Avoid clicking a toggle that could race autoplay.
        error=page.evaluate('''async action => {
            const p=document.querySelector('#movie_player'), v=p?.querySelector('video')||document.querySelector('video,audio');
            if(!v) return 'Player não encontrado.';
            if(action==='resume') {
                try { p?.playVideo?.(); await v.play(); } catch(e) { return e.message; }
            } else { p?.pauseVideo?.(); v.pause(); if(action==='stop') {v.currentTime=0;v.pause();} }
            return '';
        }''',action)
        if error: return {'verified':False,'message':'Senhor, o player não aceitou o comando: '+error}
    elif action!='status': raise ValueError('Controle de mídia desconhecido.')
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        if cancelled(): raise ValueError('Controle de mídia interrompido; confira o estado antes de repetir.')
        after=player_state(page)
        confirmed=(action=='status' or action=='pause' and after['paused'] or
            action=='stop' and after['paused'] and after['time']<.5 or
            action=='resume' and not after['paused'] and after['time']-(0 if before['ended'] else before['time'])>.15)
        if confirmed:
            percent=round(after['volume']*100)
            messages={'pause':'música pausada.','resume':'reprodução retomada.','stop':'música parada e posição reiniciada.',
                'status':f"{after['title']}: {'pausada' if after['paused'] else 'em reprodução'}, player em {percent}%"+(' e sem som.' if after['muted'] else '.')}
            return {'verified':True,'scope':'player','action':action,'state':after,'title':after['title'],
                'origin':after['origin'],'volume_percent':percent,'message':'Senhor, '+messages[action]}
        page.wait_for_timeout(120)
    return {'verified':False,'message':'Senhor, o comando foi enviado, mas o player não confirmou a alteração. Confira a página antes de repetir.'}


def play_tool(args,cancelled,context):
    from core.browser_control import browser_control
    return browser_control.tool(args,context,cancelled,progress=context.report)


def media_tool(args,cancelled,context):
    from core.browser_control import browser_control
    return browser_control.tool(args,context,cancelled,progress=context.report)


def volume_tool(args,cancelled,context):
    if cancelled(): raise ValueError('Ajuste de volume cancelado.')
    mode=args['mode'];value=args.get('value')
    if mode in ('absolute','relative','multiply') and value is None: raise ValueError('Informe o valor do volume.')
    if args.get('scope','player')=='system':
        from core.system_audio import endpoint_volume
        return endpoint_volume(mode,value,cancelled=cancelled)
    from core.browser_control import browser_control
    return browser_control.tool(args,context,cancelled,progress=context.report)
