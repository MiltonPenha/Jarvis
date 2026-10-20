"""Controlled tests: approval binds the offered video, never a fresh search."""
import asyncio
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch

from core.music_followup import confirmation_reply,confirmation_plan,offer_confirmation
from core.operational_context import OperationalContext,context_for


VIDEO={'video_id':'ZbZSe6N_BXs','title':'Pharrell Williams - Happy (Official Video)','channel':'Pharrell Williams','position':1}
SEARCH='https://www.youtube.com/results?search_query=Happy'


def fixture(session):
    pending={**offer_confirmation(VIDEO,'Happy','source',SEARCH),'session':session,'tab_id':'tab'}
    return {'accepted':True,'query':'Happy','task_id':'source','tab_url':SEARCH,'confirmation':pending}


class ReplyTests(unittest.TestCase):
    def test_affirmatives_negatives_and_new_content(self):
        for text in ('e isso Jarvis, exatamente esta música.','É isso, JARVIS, exatamente esta música.','Sim','Isso mesmo','Confirmo','Sim, pode tocar','Essa mesma'):
            self.assertEqual(confirmation_reply(text),'accept',text)
        for text in ('Não','Não, essa não','Não é essa música'):
            self.assertEqual(confirmation_reply(text),'reject',text)
        for text in ('Sim, mas toque outra música','Anote: sim, essa música','Sim, abra o Google','Não, eu disse Happy do Mudvayne','É essa música?'):
            self.assertIsNone(confirmation_reply(text),text)
        self.assertIsNone(confirmation_plan('sim',OperationalContext('empty')))

    def test_plan_is_bound_to_pending_id_and_does_not_reask_after_consumption(self):
        from core.local_runtime import direct_plan,ground_plan,Plan,Step
        ctx=OperationalContext('binding',music_goal=fixture('binding'))
        text='e isso Jarvis, exatamente esta música.'
        plan=direct_plan(text,context=ctx)
        self.assertEqual(plan['steps'][0]['target'],'confirm_music')
        self.assertEqual(plan['steps'][0]['arguments']['query'],ctx.music_goal['confirmation']['id'])
        grounded=ground_plan(Plan(steps=[Step(action='play_music',target='Happy')]),text,ctx)
        self.assertEqual(grounded.steps[0].target,'confirm_music')
        ctx.music_goal['confirmation']['state']='consumed'
        self.assertFalse(direct_plan(text,context=ctx)['steps'])
        self.assertNotIn('você quis dizer',direct_plan(text,context=ctx)['question'])
        ctx.music_goal['confirmation'].update(state='pending',created_at=time.time()-901)
        self.assertFalse(direct_plan(text,context=ctx)['steps'])


class ConfirmationChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_named_ambiguity_stores_the_same_candidate_that_was_asked_about(self):
        from core.music_resolution import select_result,local_model
        from core.youtube_control import play_youtube
        rows=[VIDEO,{'video_id':'anbrb2u9GYI','title':'Mudvayne - Happy? (Official HD Video)','channel':'Mudvayne','position':2}]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':VIDEO['video_id'],'confidence':'clear'})):
            decision=await select_result('Happy',rows,{'query':'Happy'})
        page=Mock();page.url=SEARCH
        page.locator.return_value.inner_text.return_value='Search results'
        with patch('core.youtube_control._candidates',return_value=rows*2):
            result=play_youtube(page,'Happy',select_result=lambda *args:decision,goal={'query':'Happy','task_id':'source'})
        self.assertFalse(result['verified']);self.assertEqual(result['music_confirmation']['candidate']['video_id'],VIDEO['video_id'])
        self.assertEqual(result['message'],'Senhor, você quis dizer '+VIDEO['title']+'?')
        self.assertEqual(page.goto.call_count,1);self.assertIn('/results?',page.goto.call_args.args[0])

    async def test_final_question_is_not_duplicated_as_an_error_notice(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        message='Senhor, você quis dizer '+VIDEO['title']+'?'
        with tempfile.TemporaryDirectory() as folder:
            events=[]
            async def broadcast(event):events.append(event)
            service=AssistantService(broadcast);service.store=TaskStore(Path(folder)/'tasks.db')
            service.store.create('question','feedback-'+uuid.uuid4().hex,'Pedido de teste')
            service.runtime.run=AsyncMock(return_value={'error':message})
            with patch('core.assistant_service.settings',return_value={'provider':'gemini','model':'fixture','speech_enabled':False}),patch('core.assistant_service.provider_key',return_value='fixture'):
                await service.execute('question')
            self.assertEqual(len([event for event in events if event.get('response')==message or event.get('text')==message]),1)

    async def test_acceptance_consumes_once_without_model_or_search_and_survives_restart(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        from core.browser_control import BrowserControl
        from core.local_model import local_model
        session='confirmation-'+uuid.uuid4().hex;ctx=context_for(session);ctx.music_goal=fixture(session)
        browser=BrowserControl(mode='chrome');page=Mock();page.url=SEARCH;page.is_closed.return_value=False
        page.locator.return_value.inner_text.return_value='Observed YouTube results'
        def navigate(url,**kwargs):page.url=url
        page.goto.side_effect=navigate;browser.context=Mock();browser.context.pages=[page]
        browser.tool=lambda args,context,cancelled,progress=None:browser._tool(args,context,cancelled)
        playback={'verified':True,'video_id':VIDEO['video_id'],'title':VIDEO['title'],'position_seconds':1.2,'playback_confirmed':True,'player_muted':False,'message':'Senhor, reprodução confirmada.'}
        try:
            with tempfile.TemporaryDirectory() as folder:
                service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
                from core.local_runtime import LocalRuntime
                service.local_runtime=LocalRuntime(service.store)
                service.store.create('source',session,'Toque Happy');service.store.input_trace('source',{'music_goal':ctx.music_goal})
                service.store.update('source','failed',result='Senhor, você quis dizer '+VIDEO['title']+'?')
                with patch('core.assistant_service.settings',return_value={'provider':'local-cpu','model':'qwen3:1.7b','speech_enabled':False}),patch('core.browser_control.browser_control',browser),patch.object(browser,'_start'),patch.object(browser,'_live_tabs',return_value={'tab':page}),patch.object(browser,'_tab_id',return_value='tab'),patch('core.media_control.player_state',return_value={'identity':'confirmed'}),patch('core.youtube_control.authentication_state',return_value={'authenticated':True}),patch('core.youtube_control._candidates',return_value=[VIDEO]) as candidates,patch('core.youtube_control._confirm_playback',return_value=playback) as verify,patch.object(local_model,'plan',AsyncMock(side_effect=AssertionError('No inference for approval'))):
                    await service.submit('e isso Jarvis, exatamente esta música.',session,'yes')
                    await service.runners['yes']
                    task=service.store.get('yes');self.assertEqual(task['state'],'completed',task)
                    self.assertEqual(task['usage']['local_model_calls'],0)
                    self.assertEqual(task['input']['music_goal']['confirmation']['state'],'consumed')
                    self.assertNotIn('music_search_queries',task['input'])
                    self.assertEqual(page.goto.call_count,1);self.assertIn('watch?v=ZbZSe6N_BXs',page.goto.call_args.args[0])
                    candidates.assert_called_once();verify.assert_called_once();browser.context.new_page.assert_not_called()
                    restored=service.store.last_music_goal(session)
                    self.assertEqual(restored['confirmation']['state'],'consumed')
                    ctx.music_goal=restored
                    await service.submit('Sim',session,'again');await service.runners['again']
                    self.assertFalse(service.store.get('again')['tools']);self.assertEqual(page.goto.call_count,1)
        finally:browser.context=None;browser.executor.shutdown(wait=True)

    async def test_duplicate_reply_does_not_cancel_the_confirmation_in_flight(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        session='double-'+uuid.uuid4().hex;ctx=context_for(session);ctx.music_goal=fixture(session)
        entered=asyncio.Event();release=asyncio.Event()
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            async def run(request,*args,**kwargs):
                if request['id']=='first':
                    ctx.music_goal['confirmation']['state']='executing';entered.set();await release.wait();ctx.music_goal['confirmation']['state']='consumed'
                return {'response':'Senhor, concluído.'}
            service.local_runtime.run=run;service.local_runtime.cancel=AsyncMock()
            with patch('core.assistant_service.settings',return_value={'provider':'local-cpu','model':'qwen3:1.7b','speech_enabled':False}):
                await service.submit('Sim',session,'first');first=service.runners['first'];await entered.wait()
                await service.submit('É isso, exatamente essa música',session,'second');second=service.runners['second']
                service.local_runtime.cancel.assert_not_awaited();release.set();await first;await second
                self.assertEqual(service.store.get('first')['state'],'completed')

    async def test_new_request_invalidates_the_offer_and_other_sessions_cannot_use_it(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        from core.jarvis_tools import ToolService
        session='new-'+uuid.uuid4().hex;ctx=context_for(session);ctx.music_goal=fixture(session)
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            service.local_runtime.run=AsyncMock(return_value={'response':'Senhor, anotado.'})
            with patch('core.assistant_service.settings',return_value={'provider':'local-cpu','model':'qwen3:1.7b','speech_enabled':False}):
                await service.submit('Anote: testar depois',session,'note');await service.runners['note']
            self.assertEqual(service.store.last_music_goal(session)['confirmation']['state'],'superseded')
            service.store.create('foreign','other-session','Sim')
            tool=ToolService('foreign',store=service.store)
            with patch.object(tool,'_dispatch') as dispatch:
                result=tool.execute({'action':'media','check':'confirm_music','query':ctx.music_goal['confirmation']['id']})
            self.assertFalse(result['verified']);dispatch.assert_not_called()


class BrowserChecks(unittest.TestCase):
    def test_missing_or_changed_candidate_never_navigates_or_consumes(self):
        from core.youtube_control import confirm_youtube
        pending=fixture('stale')['confirmation'];page=Mock();page.url=SEARCH
        page.locator.return_value.inner_text.return_value='Search results'
        for rows in ([],[{**VIDEO,'title':'Different title'}]):
            claim=Mock()
            with patch('core.youtube_control._candidates',return_value=rows):
                with self.assertRaisesRegex(ValueError,'mudou|saiu'):confirm_youtube(page,pending,lambda:False,before_play=claim)
            page.goto.assert_not_called();claim.assert_not_called()

    def test_rejection_needs_no_player_browser_or_new_search(self):
        from core.browser_control import BrowserControl
        ctx=OperationalContext('reject',music_goal=fixture('reject'));ctx.record_music_confirmation=Mock()
        b=BrowserControl(mode='chrome')
        try:
            with patch.object(b,'_start') as start:
                result=b._tool({'action':'media','check':'reject_music','query':ctx.music_goal['confirmation']['id']},ctx,lambda:False)
            self.assertTrue(result['verified']);self.assertEqual(result['stage'],'confirmation_rejected');start.assert_not_called()
            self.assertEqual(ctx.record_music_confirmation.call_args.args[0]['state'],'rejected')
        finally:b.executor.shutdown(wait=True)

    def test_legacy_named_question_recovers_exact_id_but_generic_question_does_not(self):
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('old','legacy','Toque Happy')
            goal={'accepted':True,'query':'Happy','tab_url':SEARCH}
            selection={'decision':{'suggested_title':VIDEO['title'],'suggested_artist':VIDEO['channel'],'observed':[VIDEO],'evidence':{VIDEO['video_id']:{'eligible':True}}}}
            store.input_trace('old',{'music_goal':goal,'music_selection':selection})
            store.update('old','failed',result='Senhor, você quis dizer '+VIDEO['title']+'?')
            restored=store.last_music_goal('legacy');self.assertEqual(restored['confirmation']['candidate']['video_id'],VIDEO['video_id'])
            self.assertEqual(restored['confirmation']['id'],store.last_music_goal('legacy')['confirmation']['id'])
            store.update('old','failed',result='Qual artista deseja?');self.assertNotIn('confirmation',store.last_music_goal('legacy'))


if __name__=='__main__':unittest.main()
