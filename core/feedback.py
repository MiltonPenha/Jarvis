"""Presentation of observed results; presentation never authorizes an effect."""
CLARIFICATION_STAGES={'ambiguous_results','no_results','no_matching_result','selection_uncertain'}

def needs_clarification(result):
    return result.get('stage') in CLARIFICATION_STAGES and not result.get('playback_confirmed')

def _content_update(event):
    data=event.get('data') or {}
    if event.get('type')=='progress':
        candidate=data.get('candidate') or {}
        if data.get('stage')=='results_found':
            return {'stage':'found','count':data['count'],'title':'Resultados encontrados'}
        if candidate and data.get('stage') in ('video_selected','opening_video','title_identified'):
            return {'stage':'awaiting_choice' if data['stage']=='title_identified' else 'selected' if data['stage']=='video_selected' else 'opening',
                    'title':candidate.get('title',''),'channel':candidate.get('channel',''),'video_id':candidate.get('video_id','')}
    if event.get('type')=='tool':
        result=data.get('result') or {}
        candidate=result.get('selected_candidate') or (result.get('music_confirmation') or {}).get('candidate') or {}
        title=result.get('title') or candidate.get('title')
        if title:
            confirmed=result.get('verified') is True and result.get('playback_confirmed') is True
            return {'stage':'confirmed' if confirmed else 'awaiting_choice' if needs_clarification(result) else 'unconfirmed',
                    'title':title,'channel':candidate.get('channel',''),'video_id':result.get('video_id') or candidate.get('video_id','')}
        if data.get('action') in ('open_target','project_open','browser_open'):
            return {'stage':'opening' if data.get('state')=='running' else 'sent' if result.get('launch_requested') else 'confirmed' if result.get('verified') is True else 'unconfirmed',
                    'title':result.get('title') or result.get('url') or result.get('message') or 'Abertura em andamento'}
    return None


def content_update(event):
    data=event.get('data') or {};result=data.get('result') or {}
    if event.get('type')=='progress' and data.get('stage')=='searching':
        return {'stage':'searching','title':'Busca em andamento','query':data.get('query',''),
            'result_set_id':data.get('result_set_id',''),'candidates':[]}
    presentation=_content_update(event)
    observed=result.get('result_set') or result.get('music_goal',{}).get('result_set') or {}
    if not presentation and needs_clarification(result) and observed.get('candidates'):
        presentation={'stage':'awaiting_choice','title':'Escolha entre os resultados disponíveis'}
    if presentation:
        presentation.update(result_set_id=data.get('result_set_id') or observed.get('id',''),
            source_task_id=data.get('source_task_id') or observed.get('source_task_id',''),
            query=data.get('query') or observed.get('query',''))
        if data.get('candidates') is not None:presentation['candidates']=data['candidates']
        elif observed.get('candidates') is not None:presentation['candidates']=observed['candidates']
    return presentation
