"""Voice stages, semantic intent, lifecycle and cleanup regressions."""
import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock,AsyncMock


def setUpModule():
    global AudioManager,config,TaskStore,AssistantService,direct_plan,Plan,ground_plan,OperationalContext,ToolService,normalize_command
    from core.audio_manager import AudioManager
    from core.config import config
    from core.task_store import TaskStore
    from core.assistant_service import AssistantService
    from core.local_runtime import direct_plan,Plan,ground_plan
    from core.operational_context import OperationalContext
    from core.jarvis_tools import ToolService
    from core.command_text import normalize_command


class UtteranceTests(unittest.TestCase):
    def test_explicit_artist_correction_overrides_the_previous_model_query(self):
        context=OperationalContext('correction',pending_music_query='Gunner Rose')
        text='Jarvis, na verdade, o artista que estou procurando é guns and roses.'
        direct=direct_plan(text,context=context)
        self.assertEqual(direct['steps'][0]['target'],'guns and roses')
        stale=Plan.model_validate({'steps':[{'action':'browser_search','target':'Gunner Rose'},{'action':'browser_read'}]})
        grounded=ground_plan(stale,text,context)
        self.assertEqual([(step.action,step.target) for step in grounded.steps],[('play_music','guns and roses')])

    def test_unresolved_music_goal_can_be_recovered_without_dom_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('first','s','Toque artista')
            store.input_trace('first',{'intent':[{'action':'play_music','query':'Artista dito'}]})
            store.claim_tool('first','music','play_music');store.finish_tool('first','music',{'verified':False})
            self.assertEqual(store.pending_music('s'),'Artista dito')
            store.create('second','s','Toque artista correto')
            store.input_trace('second',{'intent':[{'action':'play_music','query':'Artista correto'}]})
            store.claim_tool('second','music','play_music');store.finish_tool('second','music',{'verified':True})
            self.assertEqual(store.pending_music('s'),'')
    def test_reported_transcripts_keep_the_complete_start_goal(self):
        samples=[
            ('Boa noite, Jarvis. Abra o YouTube e toque uma música do Guns N’ Roses.','Guns N’ Roses'),
            ('Jarvis, coloque uma música do Queen no YouTube.','Queen'),
            ('Abra o YouTube e toque Daft Punk.','Daft Punk'),
            ('Morote Jarls, abre o YouTube e toca uma música do Dancing Roses.','Dancing Roses'),
            ('Pô, noite, Jarnes. Abra o YouTube e toque no meu música do Guns and Roses.','Guns and Roses'),
        ]
        for text,artist in samples:
            with self.subTest(text=text):
                plan=direct_plan(text)
                self.assertIsNotNone(plan)
                grounded=ground_plan(Plan.model_validate(plan),text)
                self.assertEqual(grounded.steps[-1].action,'play_music')
                self.assertEqual(grounded.steps[-1].target,artist)
                self.assertNotIn('media',[row.action for row in grounded.steps])

    def test_approximation_cannot_rewrite_artists_or_note_contents(self):
        from core.command_text import music_request
        for text in ('Toque Jarls','Anote que Jarls é um nome','Não toque uma música do Queen','Se chover, Jarvis, toque Queen'):
            self.assertEqual(normalize_command(text),text)
        self.assertEqual(direct_plan('Anote que Jarls é um nome')['steps'][0]['content'],'Jarls é um nome')
        self.assertIsNone(music_request('Explique o que significa “toque uma música do Queen”'))
        self.assertIsNone(music_request('Não toque uma música do Queen'))

    def test_relative_band_uses_context_and_missing_context_asks(self):
        text='Por favor, Jarvis, toca uma música dessa banda.'
        context=OperationalContext('test',media_query='Nirvana')
        self.assertEqual(direct_plan(text,context=context)['steps'][0]['target'],'recommendation')
        self.assertEqual(direct_plan(text)['steps'][0]['target'],'recommendation')
        self.assertEqual(direct_plan('Coloque outra dessa banda')['steps'][0]['target'],'recommendation')

    def test_legacy_model_resume_is_replaced_before_first_effect(self):
        text='Pô, noite, Jarnes. Abra o YouTube e toque no meu música do Queen.'
        model=Plan.model_validate({'steps':[{'action':'browser_open','target':'youtube'},{'action':'media','target':'resume'}]})
        plan=ground_plan(model,text)
        self.assertEqual([(row.action,row.target) for row in plan.steps],[('browser_open','youtube'),('play_music','Queen')])
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('test','test',text)
            tools=ToolService('test',store=store)
            with patch.object(tools,'_dispatch',return_value={'verified':True,'message':'Playback observed'}) as effect:
                tools.execute({'action':'media','check':'resume'})
                self.assertEqual(effect.call_args.args[0],{'action':'play_music','query':'Queen'})


class AudioTests(unittest.TestCase):
    def test_resampling_filters_aliases_and_keeps_speech_band(self):
        import numpy as np
        audio=AudioManager();transcriber=Mock();transcriber.transcribe.return_value=([SimpleNamespace(text='Teste')],None)
        samples=np.sin(2*np.pi*12000*np.arange(48000)/48000).astype(np.float32)
        with patch.object(audio,'prepare_local_transcriber',return_value=transcriber):
            self.assertEqual(audio.transcribe_audio(samples,48000),'Teste')
            filtered=transcriber.transcribe.call_args.args[0]
            self.assertEqual(len(filtered),16000)
            self.assertLess(float(np.sqrt(np.mean(filtered[100:-100]**2))),.01)

    def test_configured_pause_does_not_cut_after_greeting(self):
        import numpy as np,itertools
        audio=AudioManager();device={'index':1,'name':'test','hostapi':'test'}
        voice=np.full((800,1),.02,dtype=np.float32);silence=np.zeros_like(voice)
        blocks=[voice]*20+[silence]*23+[voice]*50+[silence]*35
        stream=Mock();stream.__enter__=Mock(return_value=stream);stream.__exit__=Mock(return_value=False)
        stream.read.side_effect=[(chunk,False) for chunk in blocks]
        with patch('core.audio_devices.capture_parameters',return_value=(device,16000)),patch('sounddevice.InputStream',return_value=stream),patch('core.audio_manager.time.monotonic',side_effect=itertools.count(0,.05)),patch.object(config,'VOICE_SILENCE_SECONDS',1.5):
            result=audio.record_phrase()
        self.assertGreater(len(result),800*90)
        self.assertEqual(audio.last_capture['reason'],'silence')

    def test_speech_cleanup_failure_cannot_leave_busy_lock(self):
        audio=AudioManager()
        async def fail(*args):raise RuntimeError('synthesis failed')
        with patch.object(audio,'synthesize',fail),patch('core.audio_manager.Path.unlink',side_effect=PermissionError('locked')):
            audio.speak('Teste')
        self.assertFalse(audio.is_speaking);self.assertFalse(audio._speech_lock.locked())


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_time_does_not_cut_a_started_playback(self):
        from core.audio_manager import audio_manager
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            service.store.create('t','s','Pedido de teste')
            service.runtime.run=AsyncMock(return_value={'response':'Resultado observado'})
            def speak(*args,on_state=None,**kwargs):
                import time
                time.sleep(.02)
                audio_manager.last_speech={'audio_seconds':.1}
                on_state('SPEAKING')
                time.sleep(.1)
                return {'state':'completed'}
            selected={'provider':'gemini','model':'fixture','speech_enabled':True}
            with patch('core.assistant_service.settings',return_value=selected),patch('core.assistant_service.provider_key',return_value='fixture'),patch.object(config,'SPEECH_TIMEOUT',.06),patch.object(audio_manager,'speak',side_effect=speak),patch.object(audio_manager,'stop') as stop:
                await service.execute('t')
                stop.assert_not_called()
            self.assertEqual(service.store.get('t')['input']['speech_result']['state'],'completed')

    async def test_speech_timeout_stops_audio_and_releases_task(self):
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            service.store.create('t','s','Pedido de teste')
            service.runtime.run=AsyncMock(return_value={'response':'Resultado observado'})
            release=threading.Event()
            def speak(*args,**kwargs):release.wait(3);return {'state':'cancelled'}
            selected={'provider':'gemini','model':'fixture','speech_enabled':True}
            with patch('core.assistant_service.settings',return_value=selected),patch('core.assistant_service.provider_key',return_value='fixture'),patch.object(config,'SPEECH_TIMEOUT',.03),patch('core.audio_manager.audio_manager.speak',side_effect=speak),patch('core.audio_manager.audio_manager.stop',side_effect=release.set) as stop:
                await service.execute('t')
                stop.assert_called_once()
            self.assertFalse(service.lock.locked());self.assertEqual(service.store.get('t')['state'],'completed')
            self.assertTrue(any('tempo limite' in call.args[0].get('text','') for call in service.broadcast.call_args_list))

    async def test_task_is_running_until_voice_finishes_and_speech_error_releases_it(self):
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            service.store.create('t','s','Pedido de teste')
            service.runtime.run=AsyncMock(return_value={'response':'Resultado observado'})
            entered=threading.Event();release=threading.Event()
            def speak(*args,**kwargs):entered.set();release.wait(3);return {'state':'failed','error':'Voice failure'}
            selected={'provider':'gemini','model':'fixture','speech_enabled':True}
            with patch('core.assistant_service.settings',return_value=selected),patch('core.assistant_service.provider_key',return_value='fixture'),patch('core.audio_manager.audio_manager.speak',side_effect=speak):
                task=asyncio.create_task(service.execute('t'));service.runners['t']=task
                while not entered.is_set():await asyncio.sleep(.01)
                self.assertEqual(service.store.get('t')['state'],'running');self.assertTrue(service.lock.locked())
                release.set();await task
            self.assertEqual(service.store.get('t')['state'],'completed');self.assertFalse(service.lock.locked());self.assertFalse(service.runners)

    async def test_manual_voice_can_correct_a_running_search_and_submits_once(self):
        import server
        events=[];submits=[];gate=asyncio.Lock();await gate.acquire()
        async def broadcast(value):events.append(value)
        async def submit(text,session,identifier,**kwargs):submits.append((text,kwargs));return {'id':identifier}
        manager=SimpleNamespace(is_speaking=False,last_capture={'sample_rate':48000},listen_and_transcribe=lambda **kwargs:'Boa noite, Jarvis. Toque Queen')
        fake=SimpleNamespace(lock=gate,runners={},submit=submit)
        with patch.object(server,'assistant',fake),patch.object(server,'audio_manager',manager),patch.object(server,'broadcast',broadcast):
            task=asyncio.create_task(server.listen('s',request_id='utterance'))
            await asyncio.sleep(.05);self.assertEqual(len(submits),1)
            gate.release();await task
        self.assertEqual(len(submits),1)
        self.assertEqual(submits[0][1]['input_data']['normalized_text'],'Toque Queen')
        self.assertEqual(len([e for e in events if e['type']=='transcription']),1)

    async def test_cancelled_capture_never_submits_a_late_transcript(self):
        import server
        entered=threading.Event();release=threading.Event();submit=AsyncMock()
        def capture(**kwargs):entered.set();release.wait(3);return 'Toque Queen'
        manager=SimpleNamespace(is_speaking=False,last_capture={},listen_and_transcribe=capture)
        fake=SimpleNamespace(lock=asyncio.Lock(),runners={},submit=submit)
        with patch.object(server,'assistant',fake),patch.object(server,'audio_manager',manager),patch.object(server,'broadcast',AsyncMock()):
            task=asyncio.create_task(server.listen('s',request_id='stale'))
            while not entered.is_set():await asyncio.sleep(.01)
            server.voice_epoch+=1;release.set();await task
        submit.assert_not_called()

    async def test_continuous_capture_waits_until_running_task_finishes(self):
        import server
        gate=asyncio.Lock();await gate.acquire();captured=[]
        def capture(**kwargs):captured.append(True);return 'Jarvis, toque Queen'
        async def submit(*args,**kwargs):server.voice_continuous=False;return {'id':'continuous'}
        manager=SimpleNamespace(is_speaking=False,last_capture={},listen_and_transcribe=capture)
        fake=SimpleNamespace(lock=gate,runners={},submit=submit)
        with patch.object(server,'voice_continuous',False),patch.object(server,'assistant',fake),patch.object(server,'audio_manager',manager),patch.object(server,'broadcast',AsyncMock()):
            task=asyncio.create_task(server.listen('continuous-fixture',continuous=True))
            await asyncio.sleep(.05);self.assertFalse(captured)
            gate.release();await asyncio.wait_for(task,2)
        self.assertEqual(len(captured),1)
