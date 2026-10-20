"""Behavioral coverage for local commands, real durable timers and browser navigation."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, AsyncMock

from core.local_runtime import direct_plan, LocalRuntime, Plan, SYSTEM, ACTIONS, ground_plan
from core.reminders import ReminderStore, parse_when
from core.task_store import TaskStore
from core.config import config


class LocalCommandTests(unittest.TestCase):
    def test_reported_music_sequence_and_transcription_do_not_touch_reminders(self):
        for command in ('Jarvis, abra o Google, entre no YouTube e toque uma música do Guns and Roses.',
                        'Javis, abro o Google, entre no YouTube e toque uma música do Guns and Roses.'):
            self.assertEqual([row['action'] for row in direct_plan(command)['steps']],['browser_open','browser_open','play_music']) # composed independently; no recipe
        plan=Plan.model_validate(direct_plan('já avisava para o youtube'))
        self.assertEqual([(item.action,item.target) for item in plan.steps],[('browser_open','youtube')])

    def test_model_cannot_dismiss_reminders_for_a_youtube_request(self):
        plan=Plan.model_validate({'steps':[{'action':'reminder_dismiss','target':'atual','content':'','when':''}],'question':''})
        with self.assertRaisesRegex(ValueError,'encerrar avisos'):
            ground_plan(plan,'já avisava para o youtube')

    def test_notes_and_alarm_labels_cannot_be_invented_by_model(self):
        command='Guarde uma anotação: comprar café amanhã'
        plan=Plan.model_validate({'steps':[{'action':'note_create','target':'Café','content':'inventado','when':''}],'question':''})
        self.assertEqual(ground_plan(plan,command).steps[0].content,'comprar café amanhã')
        plan=Plan.model_validate({'steps':[{'action':'reminder_create','target':'alarm','content':'beber água','when':'amanhã às 9:30'}],'question':''})
        self.assertEqual(ground_plan(plan,'Preciso de um alarme para amanhã às 9:30').steps[0].content,'Alarme')

    def test_model_invented_time_is_rejected_before_any_effect(self):
        plan=Plan.model_validate({'steps':[{'action':'reminder_create','target':'alarm','content':'Alarme','when':'amanhã às 9:30'}],'question':''})
        with self.assertRaisesRegex(ValueError,'horário'):
            ground_plan(plan,'Quero um alarme mas ainda não escolhi o horário')

    def test_direct_commands_need_no_model(self):
        cases={'abra a calculadora':'open_target','abra o google':'browser_open',
            'pesquise sobre astronomia':'browser_search','clique no resultado 2':'browser_click',
            'anote que comprar leite':'note_create','qual o tempo agora?':'weather',
            'me lembre de beber água em 10 minutos':'reminder_create',
            'crie um alarme amanhã às 8:30':'reminder_create','meus lembretes':'reminder_list'}
        for text, action in cases.items():
            with self.subTest(text=text):
                plan=Plan.model_validate(direct_plan(text))
                self.assertEqual(plan.steps[0].action,action)
        self.assertIsNone(direct_plan('Dá para deixar o bloco de notas aberto para mim?'))

    def test_relative_and_absolute_alarm_times_and_missing_time(self):
        now=datetime.now().astimezone().replace(hour=13,minute=0,second=0,microsecond=0)
        self.assertEqual(parse_when('em 10 minutos',now), (now+timedelta(minutes=10)).astimezone(timezone.utc))
        result=parse_when('amanhã às 8:30',now).astimezone(now.tzinfo)
        self.assertEqual((result.day,result.hour,result.minute),((now+timedelta(days=1)).day,8,30))
        self.assertEqual(parse_when('às 14:30',now).astimezone(now.tzinfo).hour,14)
        with self.assertRaises(ValueError): parse_when('amanhã',now)
        with self.assertRaises(ValueError): parse_when('em 0 minutos',now)
        with self.assertRaises(ValueError): parse_when('ontem às 8:00',now)

    def test_reminder_survives_restart_becomes_due_and_is_dismissed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'timers.db'
            store=ReminderStore(path)
            created=store.create('beber água','em 5 segundos')
            restarted=ReminderStore(path)
            self.assertEqual(restarted.list()[0]['text'],'beber água')
            future=datetime.now(timezone.utc)+timedelta(seconds=10)
            self.assertEqual(restarted.tick(future)[0]['state'],'due')
            self.assertEqual(len(restarted.tick(future)),1)
            restarted.dismiss(created['id'])
            self.assertFalse(ReminderStore(path).list())

    def test_note_checkpoint_prevents_duplicate_note_after_retry(self):
        from core.jarvis_tools import ToolService
        from core.memory_obsidian import ObsidianMemory
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); store=TaskStore(base/'tasks.db');store.create('a','s','anotar')
            vault=ObsidianMemory(base/'vault',base/'index.db')
            with patch('core.basic_tools.obsidian_memory',vault):
                tool=ToolService('a',store=store)
                args={'action':'note_create','query':'Teste','content':'Comprar leite'}
                self.assertTrue(tool.execute(args)['verified'])
                self.assertTrue(tool.execute(args)['replayed_checkpoint'])
                self.assertEqual(len(list((base/'vault').rglob('*.md'))),1)

    def test_private_browser_destinations_blocked(self):
        from core.browser_control import public_url
        for target in ('http://127.0.0.1','http://192.168.1.1','http://localhost','https://user:pass@example.com','file:///C:/Windows'):
            with self.subTest(target=target), self.assertRaises((PermissionError,ValueError)):
                public_url(target)


class LocalExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_alarm_is_broadcast_and_sound_stops_after_dismissal(self):
        import server
        with tempfile.TemporaryDirectory() as directory:
            store=ReminderStore(Path(directory)/'alarms.db')
            created=store.create('Alarme de teste','em 1 segundo','alarm')
            delivered=asyncio.Event()
            async def broadcast(event):
                if event.get('type')=='reminder_due': delivered.set()
            with patch.object(server,'reminders',store),patch.object(server,'broadcast',broadcast), \
                 patch('winsound.MessageBeep') as sound:
                loop=asyncio.create_task(server.reminder_loop())
                try:
                    await asyncio.wait_for(delivered.wait(),4)
                    await asyncio.sleep(.1)
                    sound.assert_called_once()
                    store.dismiss(created['id'])
                    await asyncio.sleep(1.1)
                    sound.assert_called_once()
                    self.assertFalse(store.list())
                finally:
                    loop.cancel();await asyncio.gather(loop,return_exceptions=True)

    async def test_paid_limits_do_not_block_local_tasks_or_count_their_tokens(self):
        from core.assistant_service import AssistantService
        with tempfile.TemporaryDirectory() as directory:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(directory)/'tasks.db')
            selected={'provider':'local-cpu','model':'qwen3:1.7b','speech_enabled':False}
            with patch('core.assistant_service.settings',return_value=selected), \
                 patch.object(config,'MAX_DAILY_TASKS',0),patch.object(config,'MAX_DAILY_TOKENS',0), \
                 patch.object(service.local_runtime,'run',AsyncMock(return_value={'response':'Senhor, pronto.',
                    'usage':{'provider':'local-cpu','input_tokens':1000,'output_tokens':100,'estimated_usd':0}})):
                await service.submit('teste local','s','a')
                await service.runners['a']
                self.assertEqual(service.store.get('a')['state'],'completed')
                self.assertEqual(service.store.daily_usage()['tokens'],0)
                self.assertEqual(service.store.daily_usage()['tasks'],0)

    async def test_local_cancellation_cannot_execute_a_pending_model_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            store=TaskStore(Path(directory)/'tasks.db');store.create('a','s','pedido sem atalho')
            service=LocalRuntime(store)
            entered=asyncio.Event()
            async def pending(*args):
                entered.set();await asyncio.Event().wait()
            with patch('core.local_runtime.local_model.plan',pending), \
                 patch('core.local_runtime.local_model.stop') as stop, \
                 patch('core.local_runtime.ToolService.execute') as execute:
                task=asyncio.create_task(service.run({'id':'a','command':'um pedido sem atalho'},AsyncMock()))
                await asyncio.wait_for(entered.wait(),10)
                await service.cancel('a')
                self.assertTrue((await asyncio.wait_for(task,3))['cancelled'])
                stop.assert_called_once();execute.assert_not_called()

    async def test_model_cannot_execute_an_unlisted_action(self):
        with tempfile.TemporaryDirectory() as directory:
            store=TaskStore(Path(directory)/'tasks.db'); store.create('a','s','faca algo')
            engine=LocalRuntime(store)
            with patch('core.local_runtime.local_model.plan',AsyncMock(return_value={
                'steps':[{'action':'shell','target':'cmd','content':'','when':''}],'question':''})), \
                 patch('core.local_runtime.ToolService.execute') as execute:
                with self.assertRaisesRegex(ValueError,'não autorizada'):
                    await engine.run({'id':'a','command':'execute algo'},AsyncMock())
                execute.assert_not_called()

    async def test_local_task_finishes_without_api_key_and_preserves_tool_result(self):
        from core.assistant_service import AssistantService
        with tempfile.TemporaryDirectory() as directory:
            service=AssistantService(AsyncMock()); service.store=TaskStore(Path(directory)/'tasks.db')
            service.local_runtime=LocalRuntime(service.store)
            service.store.create('a','s','qual o tempo agora?')
            selected={'provider':'local-cpu','model':'qwen3:1.7b','fallback_provider':'gemini',
                'fallback_model':'must-not-run','speech_enabled':False}
            with patch('core.assistant_service.settings',return_value=selected), \
                 patch('core.assistant_service.provider_key',return_value=''), \
                 patch('core.weather.weather',return_value={'verified':True,'message':'Senhor, 25 °C observados.'}), \
                 patch.object(service.runtime,'run',AsyncMock()) as cloud:
                await service.execute('a')
                result=service.store.get('a')
                self.assertEqual(result['state'],'completed')
                self.assertIn('25 °C',result['result'])
                self.assertEqual(result['usage']['api_calls'],0)
                cloud.assert_not_called()

    async def test_local_failure_never_uses_configured_paid_fallback(self):
        from core.assistant_service import AssistantService
        with tempfile.TemporaryDirectory() as directory:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(directory)/'tasks.db')
            service.local_runtime=LocalRuntime(service.store);service.store.create('a','s','qual o tempo agora?')
            selected={'provider':'local-cpu','model':'qwen3:1.7b','fallback_provider':'gemini','fallback_model':'unused','speech_enabled':False}
            with patch('core.assistant_service.settings',return_value=selected), \
                 patch('core.weather.weather',side_effect=RuntimeError('Sem rede')), \
                 patch.object(service.runtime,'run',AsyncMock()) as cloud:
                await service.execute('a')
                self.assertEqual(service.store.get('a')['state'],'failed');cloud.assert_not_called()


class BrowserRecoveryTests(unittest.TestCase):
    def setUp(self):
        from core.browser_control import BrowserControl
        self.folder=tempfile.TemporaryDirectory(prefix='jarvis-browser-regression-')
        self.browser=BrowserControl(Path(self.folder.name),headless=True,mute_audio=True)
        self.dns=patch('core.browser_control.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))])
        self.dns.start()

    def tearDown(self):
        self.browser.close();self.browser.executor.shutdown(wait=True)
        self.dns.stop();self.folder.cleanup()

    def fixture(self,late=None):
        def prepare():
            self.browser._start()
            def route(request):
                url=request.request.url
                if '/late' in url:
                    if late: late.set()
                    body='OK'
                else:
                    body='<html><title>Fixture</title><body>Pronto<script>setTimeout(()=>fetch("/late"),300)</script></body></html>'
                request.fulfill(status=200,body=body,content_type='text/html')
            self.browser.context.route('**/*',route)
        self.browser.executor.submit(prepare).result(15)

    def test_routes_continue_between_commands(self):
        fetched=threading.Event();self.fixture(fetched)
        self.browser.execute('browser_open','https://example.com/')
        self.assertTrue(fetched.wait(3),'A requisição ficou parada até o próximo comando.')

    def test_closed_window_is_reopened_by_a_new_navigation(self):
        self.fixture()
        self.browser.execute('browser_open','https://example.com/')
        self.browser.executor.submit(lambda:self.browser.context.close()).result(10)
        # The new context intentionally has no fixture route; about:blank startup
        # and the supplied one-shot route keep the regression fully offline.
        from core.browser_control import BrowserControl
        original=BrowserControl._start
        def start(instance):
            original(instance)
            instance.context.route('https://example.com/**',lambda route:route.fulfill(status=200,body='<title>Recuperado</title>'))
        with patch.object(BrowserControl,'_start',start):
            result=self.browser.execute('browser_open','https://example.com/')
        self.assertEqual(result['title'],'Recuperado')

    def test_cancellation_prevents_opening_a_new_window(self):
        with self.assertRaisesRegex(ValueError,'interrompida'):
            self.browser.execute('browser_open','https://example.com/',cancelled=lambda:True)
        self.assertIsNone(self.browser.context)

    def test_real_media_progress_is_required_before_playback_confirmation(self):
        import base64,io,wave
        audio=io.BytesIO()
        with wave.open(audio,'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(b'\x00\x00'*8000*5)
        source='data:audio/wav;base64,'+base64.b64encode(audio.getvalue()).decode()
        def prepare():
            self.browser._start()
            def route(request):
                if '/results?' in request.request.url:
                    body='''<title>Busca</title><ytd-video-renderer><a id="video-title" title="Guns N Roses cover" href="/watch?v=fan00000000">Cover</a><div id="channel-name"><a>Outro canal</a></div></ytd-video-renderer><ytd-video-renderer><a id="video-title" title="Guns N Roses - Faixa" href="/watch?v=official001">Faixa</a><div id="channel-name"><a>Guns N' Roses</a></div></ytd-video-renderer>'''
                else:
                    body='<title>Player</title><div id="movie_player" class="ad-showing"><video autoplay muted src="'+source+'"></video></div><script>document.getElementById("movie_player").getVideoData=()=>({video_id:"official001",title:"Guns N Roses - Faixa"});setTimeout(()=>document.getElementById("movie_player").classList.remove("ad-showing"),1000)</script>'
                request.fulfill(status=200,body=body,content_type='text/html')
            self.browser.context.route('**/*',route)
        self.browser.executor.submit(prepare).result(15)
        started=time.monotonic()
        result=self.browser.execute('youtube_play','Guns and Roses')
        self.assertTrue(result['playback_confirmed'])
        self.assertEqual(result['video_id'],'official001')
        self.assertGreater(time.monotonic()-started,1)
        self.assertGreater(result['position_seconds'],.3)


if __name__=='__main__': unittest.main()
