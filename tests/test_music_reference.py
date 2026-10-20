"""Contextual music decisions: mocked inference/browser, real orchestration/store."""
import asyncio
import copy
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch

from core.music_followup import candidate_rows,offer_confirmation,reference_context,reference_request,validate_reference
from core.operational_context import OperationalContext,context_for

A={'video_id':'gbS7o0F8eNs','title':'TAUZ - MADARA | DROP NOSTALGICZ','channel':'Tauz','position':2}
B={'video_id':'ZbZSe6N_BXs','title':'Pharrell Williams - Happy (Official Video)','channel':'Pharrell Williams','position':1}
SEARCH='https://www.youtube.com/results?search_query=rap+uma+dara'


def goal(session='fixture',presented=True,rows=None):
    rows=rows or [A,B]
    result={'id':'observed-list','source_task_id':'source','created_at':time.time(),'query':'rap uma dara',
            'search_url':SEARCH,'tab_id':'tab','candidates':candidate_rows(rows)}
    value={'accepted':True,'query':'rap uma dara','task_id':'source','result_set':result,'tab_url':SEARCH}
    if presented:
        result['presented_candidate_id']=A['video_id']
        value['confirmation']={**offer_confirmation(A,value['query'],'source',SEARCH,'title_hypothesis'),
                               'session':session,'tab_id':'tab','result_set_id':result['id']}
    return value


def decision(action='play_existing',candidate=A,span='essa',**extra):
    return {'action':action,'candidate_id':candidate['video_id'],'result_set_id':'observed-list',
        'position':candidate['position'] if action=='select_position' else 0,'reference_span':span,
        'content_spans':[],'title_span':'','artist_span':'','service':'unspecified',**extra}


class ReferenceGroundingTests(unittest.TestCase):
    def test_gate_preserves_controls_and_literal_titles(self):
        for text in ('Quero que você toque exatamente essa mídia que você encontrou.','Pode tocar a que você encontrou.',
                     'Toque essa.','Reproduza exatamente essa mídia.','Mesmo assim, toque essa.','Toque a primeira dessas opções.'):
            self.assertTrue(reference_request(text),text)
        for text in ('Toque a música "Essa mídia que você encontrou"','Toque a primeira sugestão','Pause a música','Aumente o volume',
                     'Pode aumentar esse volume?','Abra essa mesma página'):
            self.assertFalse(reference_request(text),text)

    def test_membership_positions_and_no_arbitrary_first(self):
        snapshot=reference_context({'music_goal':goal(presented=False)})
        self.assertEqual([row['position'] for row in snapshot['candidates']],[1,2])
        self.assertFalse(validate_reference(decision(candidate=B),'Toque essa',snapshot)['accepted'])
        self.assertTrue(validate_reference(decision('select_position',B,span='primeira'),'Toque a primeira dessas opções',snapshot)['accepted'])
        for change in ({'candidate_id':'abcdefghijk'},{'result_set_id':'foreign'},{'position':2}):
            result=validate_reference(decision('select_position',B,span='primeira',**change),'Toque a primeira',snapshot)
            self.assertFalse(result['accepted'],result)

    def test_artist_must_identify_unique_observed_candidate(self):
        snapshot=reference_context({'music_goal':goal(presented=False)})
        self.assertTrue(validate_reference(decision(span='a do TAUZ'),'a do TAUZ',snapshot)['accepted'])
        snapshot['candidates'].append({**A,'video_id':'D4J8kJoS9lA','title':'TAUZ - GAARA','position':3})
        self.assertFalse(validate_reference(decision(span='a do TAUZ'),'a do TAUZ',snapshot)['accepted'])

    def test_one_presented_candidate_survives_inaccurate_query(self):
        snapshot=reference_context({'music_goal':goal()})
        result=validate_reference(decision(span='exatamente essa mídia que você encontrou'),
            'Quero que você toque exatamente essa mídia que você encontrou.',snapshot)
        self.assertTrue(result['accepted']);self.assertEqual(result['candidate']['video_id'],A['video_id'])
        self.assertEqual(result['query'],'');self.assertEqual(result['candidate']['url'],'https://www.youtube.com/watch?v='+A['video_id'])
        snapshot['created_at']=time.time()-901
        self.assertEqual(validate_reference(decision(),'Toque essa',snapshot)['reason'],'expired_context')

    def test_untrusted_urls_are_not_candidates(self):
        self.assertEqual(candidate_rows([{**A,'url':'https://example.org/watch?v='+A['video_id']}]),[])
        self.assertEqual(candidate_rows([{**A,'url':'https://www.youtube.com/watch?v='+B['video_id']}]),[])

    def test_title_acknowledgment_and_negation_cannot_become_playback(self):
        snapshot=reference_context({'music_goal':goal()})
        result=validate_reference(decision(span='essa'),'É essa mesmo',snapshot)
        self.assertEqual(result['action'],'confirm_title');self.assertTrue(result['accepted'])
        self.assertFalse(validate_reference(decision(),'Não toque essa',snapshot)['accepted'])
        result=validate_reference(decision('confirm_title',span='essa'),'Mesmo assim, toque essa',snapshot)
        self.assertTrue(result['accepted']);self.assertEqual(result['action'],'play_existing')


class ReferenceInterpreterTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_is_compact_and_ambiguous_reference_asks_actual_options(self):
        from core.music_intent import interpret,local_model,question
        with patch.object(local_model,'plan',AsyncMock(return_value=decision(candidate=B))) as model:
            result=await interpret('Toque essa',{'music_goal':goal(presented=False)})
        self.assertFalse(result['accepted']);self.assertIn('Happy',question(result));self.assertIn('MADARA',question(result))
        payload=json.loads(model.call_args_list[0].args[0][1]);self.assertEqual(payload['context']['id'],'observed-list')
        self.assertNotIn('url',payload['context']['candidates'][0]);self.assertEqual(result['query'],'')

    async def test_old_confirmation_is_not_presented_as_a_pending_question(self):
        from core.music_intent import interpret,local_model
        previous=goal();previous['confirmation']['state']='superseded'
        with patch.object(local_model,'plan',AsyncMock(return_value=decision())) as model:
            await interpret('Toque essa',{'music_goal':previous})
        compact=json.loads(model.call_args.args[0][1])['context']
        self.assertEqual(compact['pending_confirmation'],{})

    async def test_literal_reference_never_becomes_search_even_if_model_misclassifies(self):
        from core.music_intent import interpret,local_model
        proposal=decision('search_and_play',content_spans=['exatamente essa mídia que você encontrou'])
        with patch.object(local_model,'plan',AsyncMock(return_value=proposal)):
            result=await interpret('Quero que você toque exatamente essa mídia que você encontrou.',{'music_goal':goal()})
        self.assertFalse(result['accepted']);self.assertEqual(result['query'],'')

    async def test_new_title_that_looks_like_instruction_still_searches(self):
        from core.music_intent import interpret,local_model
        for text,title in [('Toque a música Essa Menina','Essa Menina'),
                           ('Toque a música "Essa mídia que você encontrou"','Essa mídia que você encontrou')]:
            with patch.object(local_model,'plan',AsyncMock(return_value=decision('search_and_play',content_spans=[title],title_span=title))):
                result=await interpret(text,{'music_goal':goal()})
            self.assertTrue(result['accepted'],result);self.assertEqual(result['query'],title)

    async def test_new_title_can_recover_when_model_overweights_old_candidate(self):
        from core.music_intent import interpret,local_model
        text='Agora toque a música Essa Menina.'
        stale=decision(span=text)
        replacement={'action':'search_and_play','content_spans':['Essa Menina'],'service':'unspecified','title_span':'Essa Menina','artist_span':''}
        with patch.object(local_model,'plan',AsyncMock(side_effect=[stale,replacement])) as model:
            result=await interpret(text,{'music_goal':goal()})
        self.assertTrue(result['accepted']);self.assertEqual(result['query'],'Essa Menina')
        self.assertEqual(result['model_calls'],2);self.assertEqual(model.await_count,2)

    async def test_referring_to_the_found_song_is_not_a_new_named_title(self):
        from core.music_intent import interpret,local_model
        text='Jarvis, toque a música que você encontrou.'
        with patch.object(local_model,'plan',AsyncMock(return_value=decision(span=text))) as model:
            result=await interpret(text,{'music_goal':goal()})
        self.assertTrue(result['accepted']);self.assertEqual(result['action'],'play_existing')
        self.assertEqual(result['query'],'');model.assert_awaited_once()

    async def test_model_copying_old_title_as_query_gets_one_validated_retry(self):
        from core.music_intent import interpret,local_model
        text='Reproduza exatamente essa mídia que você encontrou.'
        invalid=decision('search_and_play',candidate_id='',span=text,content_spans=[A['title']])
        with patch.object(local_model,'plan',AsyncMock(side_effect=[invalid,decision(span=text)])) as model:
            result=await interpret(text,{'music_goal':goal()})
        self.assertTrue(result['accepted']);self.assertEqual(result['action'],'play_existing')
        self.assertEqual(result['query'],'');self.assertEqual(model.await_count,2)
        self.assertEqual(result['reference_attempts'][0]['reason'],'ungrounded_content')

    async def test_failed_reference_keeps_real_choices_instead_of_asking_for_title(self):
        from core.music_intent import interpret,local_model,question
        invalid=decision('search_and_play',content_spans=['Title absent from the request'])
        with patch.object(local_model,'plan',AsyncMock(return_value=invalid)):
            result=await interpret('Reproduza exatamente essa mídia.',{'music_goal':goal()})
        self.assertFalse(result['accepted']);self.assertIn('MADARA',question(result));self.assertIn('Happy',question(result))

    async def test_repair_cannot_turn_a_bare_reference_into_a_query(self):
        from core.music_intent import interpret,local_model
        invalid=decision('search_and_play',content_spans=['essa'])
        with patch.object(local_model,'plan',AsyncMock(return_value=invalid)):
            result=await interpret('Toque essa',{'music_goal':goal(presented=False)})
        self.assertFalse(result['accepted']);self.assertEqual(result['query'],'')

    async def test_presented_candidate_executes_once_on_same_tab_after_page_change(self):
        from core.assistant_service import AssistantService
        from core.local_runtime import LocalRuntime
        from core.task_store import TaskStore
        from core.browser_control import BrowserControl
        from core.local_model import local_model
        session='reference-'+uuid.uuid4().hex;ctx=context_for(session);ctx.music_goal=goal(session)
        browser=BrowserControl(mode='chrome');page=Mock();page.url='https://www.google.com/'
        page.is_closed.return_value=False;page.locator.return_value.inner_text.return_value='Current page'
        page.goto.side_effect=lambda url,**kwargs:setattr(page,'url',url)
        browser.context=Mock();browser.context.pages=[page]
        browser.tool=lambda args,context,cancelled,progress=None:browser._tool(args,context,cancelled)
        playback={'verified':True,'video_id':A['video_id'],'title':A['title'],'position_seconds':1.3,
                  'playback_confirmed':True,'player_muted':False,'message':'Senhor, reprodução confirmada.'}
        try:
            with tempfile.TemporaryDirectory() as folder:
                events=[]
                async def broadcast(event):events.append(event)
                service=AssistantService(broadcast);service.store=TaskStore(Path(folder)/'tasks.db');service.local_runtime=LocalRuntime(service.store)
                service.store.create('source',session,'Toque rap uma dara');service.store.input_trace('source',{'music_goal':ctx.music_goal})
                service.store.update('source','completed',result='Senhor, você quis dizer '+A['title']+'?')
                with patch('core.assistant_service.settings',return_value={'provider':'local-cpu','model':'qwen3:1.7b','speech_enabled':True}),patch.object(service,'_say',AsyncMock(return_value={'state':'completed','delivered':True})) as say,patch('core.browser_control.browser_control',browser),patch.object(browser,'_start'),patch.object(browser,'_live_tabs',return_value={'tab':page}),patch.object(browser,'_tab_id',return_value='tab'),patch('core.media_control.player_state',return_value={'identity':'confirmed'}),patch('core.youtube_control.authentication_state',return_value={'authenticated':True}),patch('core.youtube_control._candidates') as candidates,patch('core.youtube_control._confirm_playback',return_value=playback),patch.object(local_model,'plan',AsyncMock(return_value=decision(span='exatamente essa mídia que você encontrou'))) as model:
                    await service.submit('Quero que você toque exatamente essa mídia que você encontrou.',session,'reference')
                    await service.runners['reference'];task=service.store.get('reference')
                    self.assertEqual(task['state'],'completed',task)
                    self.assertEqual(task['input']['music_goal']['confirmation']['state'],'consumed')
                    self.assertNotIn('music_search_queries',task['input']);self.assertEqual(task['input']['media_reference']['operation'],'play_existing')
                    self.assertEqual(task['input']['media_reference']['context']['id'],'observed-list')
                    self.assertEqual(page.goto.call_count,1);self.assertEqual(page.goto.call_args.args[0],'https://www.youtube.com/watch?v='+A['video_id'])
                    candidates.assert_not_called();browser.context.new_page.assert_not_called();model.assert_awaited_once();say.assert_awaited_once()
                    self.assertTrue(any(event.get('presentation',{}).get('request_id')=='reference' for event in events))
                    await service.submit('Sim',session,'duplicate');await service.runners['duplicate']
                    self.assertEqual(page.goto.call_count,1)
        finally:browser.context=None;browser.executor.shutdown(wait=True)

    async def test_title_acknowledgment_does_not_play_until_authorized(self):
        from core.local_runtime import LocalRuntime
        from core.task_store import TaskStore
        from core.music_intent import local_model
        session='title-'+uuid.uuid4().hex;ctx=context_for(session);ctx.music_goal=goal(session)
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('ack',session,'É essa mesmo')
            runtime=LocalRuntime(store)
            with patch.object(local_model,'plan',AsyncMock(return_value=decision('confirm_title',span='essa'))),patch('core.jarvis_tools.ToolService.execute') as execute:
                result=await runtime.run({'id':'ack','session':session,'command':'É essa mesmo'},AsyncMock())
            self.assertTrue(result['clarification']);self.assertIn('Deseja',result['response']);execute.assert_not_called()
            self.assertEqual(ctx.music_goal['confirmation']['authorization'],'title_only')

    async def test_ordinal_replaces_old_proposal_for_later_references(self):
        from core.local_runtime import LocalRuntime
        from core.task_store import TaskStore
        from core.music_intent import local_model
        session='position-'+uuid.uuid4().hex;ctx=context_for(session);ctx.music_goal=goal(session)
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('choose',session,'Toque a primeira opção')
            runtime=LocalRuntime(store)
            with patch.object(local_model,'plan',AsyncMock(return_value=decision('select_position',B,span='primeira'))),patch('core.jarvis_tools.ToolService.execute',return_value={'verified':True,'playback_confirmed':True,'message':'Senhor, reprodução confirmada.'}):
                await runtime.run({'id':'choose','session':session,'command':'Toque a primeira opção'},AsyncMock())
            ctx.music_goal['confirmation']['state']='consumed'
            current=reference_context(ctx)
            self.assertEqual(current['id'],'observed-list')
            self.assertEqual(current['presented_candidate_id'],B['video_id'])
            self.assertEqual(current['selected_candidate_id'],B['video_id'])
            result=validate_reference(decision(candidate=B),'Toque essa',current)
            self.assertTrue(result['accepted'],result)


class ReferenceExecutionTests(unittest.TestCase):
    def test_reconnection_uses_observed_chrome_tab_identity_after_page_change(self):
        from core.browser_control import BrowserControl
        session='reconnect';ctx=OperationalContext(session,music_goal=goal(session))
        target='a'*32
        ctx.music_goal['result_set']['target_id']=target
        ctx.music_goal['confirmation'].update(authorization='context_candidate',target_id=target)
        def record(value):ctx.music_goal['confirmation']=dict(value)
        ctx.record_music_confirmation=record
        browser=BrowserControl(mode='chrome');page=Mock();page.is_closed.return_value=False;page.url='https://www.youtube.com/'
        other=Mock();other.is_closed.return_value=False;other.url='https://www.google.com/'
        browser.context=Mock();browser.context.pages=[other,page]
        def confirm(page_arg,pending,cancelled,*args,**kwargs):
            self.assertIs(page_arg,page);kwargs['before_play']()
            return {'verified':True,'video_id':A['video_id'],'title':A['title'],'playback_confirmed':True}
        try:
            with patch.object(browser,'_start'),patch.object(browser,'_live_tabs',return_value={}),patch.object(browser,'_tab_id',return_value='new-tab'),patch.object(browser,'_target_identity',side_effect=lambda value:target if value==page else 'b'*32),patch('core.youtube_control.confirm_youtube',side_effect=confirm),patch('core.media_control.player_state',return_value={'identity':'confirmed'}):
                result=browser._tool({'action':'media','check':'confirm_music','query':ctx.music_goal['confirmation']['id']},ctx,lambda:False)
            self.assertTrue(result['verified']);self.assertEqual(result['tab_id'],'new-tab')
            self.assertEqual(ctx.music_goal['confirmation']['state'],'consumed');browser.context.new_page.assert_not_called()
        finally:browser.context=None;browser.executor.shutdown(wait=True)

    def test_wrong_player_id_never_triggers_play_or_success(self):
        from core.youtube_control import _confirm_playback
        page=Mock();page.is_closed.return_value=False
        state={'exists':True,'video_id':B['video_id'],'paused':True,'ready':4,'time':8}
        with patch('core.youtube_control.player_state',return_value=state),patch('core.youtube_control.time.monotonic',side_effect=[0,1,26]):
            result=_confirm_playback(page,A,lambda:False)
        self.assertFalse(result['verified']);self.assertEqual(result['stage'],'playback_identity_mismatch')
        page.locator.assert_not_called();page.evaluate.assert_not_called()

    def test_playback_failure_is_execution_failure_and_keeps_identity(self):
        from core.browser_control import BrowserControl
        ctx=OperationalContext('failure',music_goal=goal('failure'));ctx.music_goal['confirmation'].update(authorization='context_candidate')
        ctx.record_music_confirmation=Mock();browser=BrowserControl(mode='chrome');page=Mock();page.is_closed.return_value=False
        browser.context=Mock();browser.context.pages=[page]
        try:
            with patch.object(browser,'_start'),patch.object(browser,'_live_tabs',return_value={'tab':page}),patch('core.youtube_control.confirm_youtube',side_effect=RuntimeError('player unavailable')):
                result=browser._tool({'action':'media','check':'confirm_music','query':ctx.music_goal['confirmation']['id']},ctx,lambda:False)
            self.assertFalse(result['verified']);self.assertEqual(result['selected_candidate']['video_id'],A['video_id'])
            self.assertNotIn('não encontrei',result['message'].lower());self.assertEqual(ctx.music_goal['confirmation']['state'],'pending')
            page.goto.assert_not_called()
        finally:browser.context=None;browser.executor.shutdown(wait=True)


class ReferenceSupersessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_correction_cancels_pending_reference_and_suppresses_stale_events(self):
        from core.assistant_service import AssistantService
        from core.local_runtime import LocalRuntime
        from core.task_store import TaskStore
        from core.local_model import local_model
        session='correction-'+uuid.uuid4().hex;ctx=context_for(session);ctx.music_goal=goal(session)
        entered=asyncio.Event();events=[]
        async def model(*args,**kwargs):entered.set();await asyncio.Event().wait()
        async def broadcast(event):events.append(event)
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(broadcast);service.store=TaskStore(Path(folder)/'tasks.db');service.local_runtime=LocalRuntime(service.store)
            with patch('core.assistant_service.settings',return_value={'provider':'local-cpu','model':'qwen3:1.7b','speech_enabled':False}),patch.object(local_model,'plan',model),patch.object(local_model,'stop'),patch('core.jarvis_tools.ToolService.execute') as execute:
                await service.submit('Quero que você toque exatamente essa mídia que você encontrou',session,'old')
                old=service.runners['old'];await entered.wait()
                # submit performs the real supersession/cancellation; new work
                # is an isolated result so no second model or browser is used.
                actual_run=service.local_runtime.run
                async def next_run(request,*args,**kwargs):return {'response':'Senhor, pedido corrigido.'}
                service.local_runtime.run=next_run
                await service.submit('Não, eu disse outra música',session,'new');new=service.runners['new']
                await old;await new;service.local_runtime.run=actual_run
                await service.event('old',{'type':'progress','data':{'stage':'video_selected','candidate':A}})
            self.assertEqual(service.store.get('old')['state'],'cancelled');execute.assert_not_called()
            self.assertEqual(service.store.get('old')['input']['superseded_by'],'new')
            self.assertFalse(any(event.get('task_id')=='old' and event.get('presentation') for event in events))


if __name__=='__main__':unittest.main()
