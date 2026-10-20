import asyncio
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from unittest.mock import AsyncMock
from unittest.mock import Mock

def setUpModule():
    # test_jarvis establishes the isolated environment during discovery. Importing
    # config here keeps these tests from initializing production paths first.
    global prepare_speech,speech_chunks,content_update,needs_clarification,AudioManager
    from core.speech_text import prepare_speech,speech_chunks
    from core.feedback import content_update,needs_clarification
    from core.audio_manager import AudioManager

class SpeechPreparationTests(unittest.TestCase):
    def test_markup_numbers_and_names(self):
        text=prepare_speech("**Senhor**, volume em 47%. Alarme para 18:30. Happy, NX Zero, TAUZ e 99 Luftballons. [Detalhes](https://example.com)")
        self.assertIn('quarenta e sete por cento',text)
        self.assertIn('dezoito horas e trinta minutos',text)
        self.assertIn('Happy, NX Zero, TAUZ e 99 Luftballons',text)
        self.assertNotIn('https',text)
        self.assertEqual(prepare_speech(text),text)

    def test_chunks_preserve_complete_long_response(self):
        text=' '.join(['Senhor, este trecho contém informação necessária para concluir a explicação.']*8)
        chunks=speech_chunks(text)
        self.assertTrue(all(len(chunk)<=180 for chunk in chunks))
        self.assertEqual(' '.join(chunks),text)
        prepared=prepare_speech(text*3)
        self.assertLessEqual(len(prepared),700)
        self.assertEqual(prepare_speech(prepared),prepared)

    def test_long_qwen_uses_complete_phrases_and_native_rate(self):
        manager=AudioManager();spoken=[]
        text=' '.join(['Senhor, o pedido continua na tela, com todos os detalhes preservados.']*6)
        def fake(text,path,cancelled):
            spoken.append(text)
            with wave.open(str(path),'wb') as output:
                output.setparams((1,2,24000,0,'NONE','not compressed'));output.writeframes(b'\0\0'*240)
        with tempfile.TemporaryDirectory() as folder,patch('core.audio_manager.qwen_voice.synthesize',side_effect=fake):
            target=Path(folder)/'output.wav'
            asyncio.run(manager.synthesize(text,target,'qwen-local'))
            with wave.open(str(target)) as audio:
                self.assertEqual(audio.getframerate(),24000)
                self.assertEqual(audio.getnframes(),240*len(spoken)+2880*(len(spoken)-1))
        self.assertEqual(' '.join(spoken),prepare_speech(text))

class EvidenceTests(unittest.TestCase):
    def test_media_observer_reads_only_the_bound_player_without_connecting(self):
        from core.browser_control import BrowserControl
        control=BrowserControl(mode='isolated');control.context=object()
        page=Mock();page.is_closed.return_value=False;control.tabs={'bound':page}
        state={'exists':True,'ended':False,'paused':True,'ready':4,'title':'Observed player','volume':.47}
        try:
            with patch('core.media_control.player_state',return_value=state) as read:
                result=control.observe_media('bound')
                self.assertEqual(result['state'],'paused');self.assertEqual(result['volume'],.47)
                read.assert_called_once_with(page)
                control.context=None
                self.assertEqual(control.observe_media('bound')['state'],'unavailable')
                read.assert_called_once()
        finally:control.executor.shutdown(wait=True)

    def test_selected_is_not_confirmed(self):
        selected={'title':'Real observed title','video_id':'abcdefghijk'}
        update=content_update({'type':'progress','data':{'stage':'video_selected','candidate':selected}})
        self.assertEqual(update['stage'],'selected')
        for confirmed in (False,True):
            update=content_update({'type':'tool','data':{'result':{'verified':True,'playback_confirmed':confirmed,**selected}}})
            self.assertEqual(update['stage'],'confirmed' if confirmed else 'unconfirmed')

    def test_question_and_technical_failure_are_separate(self):
        self.assertTrue(needs_clarification({'stage':'ambiguous_results'}))
        self.assertFalse(needs_clarification({'stage':'playback_failed','message':'Quer tentar?'}))
        self.assertFalse(needs_clarification({'stage':'selection_unavailable'}))

    def test_windows_launch_is_not_presented_as_confirmed_open(self):
        result=content_update({'type':'tool','data':{'action':'project_open','result':{'verified':True,'launch_requested':True,'message':'Pasta solicitada'}}})
        self.assertEqual(result['stage'],'sent')

class CoordinationTests(unittest.IsolatedAsyncioTestCase):
    async def test_clarification_finishes_task_without_announcing_failure(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            service.store.create('question','s','Toque Happy')
            with patch('core.assistant_service.settings',return_value={'speech_enabled':False}):
                await service.finish('question','completed','Senhor, qual versão prefere?',clarification=True)
                await service.finish('question','completed','Duplicado')
            task=service.store.get('question')
            self.assertEqual(task['state'],'completed')
            self.assertEqual(task['input']['final_feedback']['outcome'],'clarification')
            events=[call.args[0] for call in service.broadcast.call_args_list]
            self.assertEqual(sum(e['type']=='jarvis_response' for e in events),1)
            self.assertEqual([e['state'] for e in events if e['type']=='state'],['WAITING'])

    async def test_chunk_budget_resets_without_cutting_started_playback(self):
        import time
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        from core.audio_manager import audio_manager
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db');service.store.create('t','s','Pedido')
            def voice(text,on_state,cancelled):
                for index in range(3):
                    audio_manager.last_speech={'phase':'generating','chunk':index+1,'chunks':3}
                    on_state('PROCESSING');time.sleep(.04)
                audio_manager.last_speech={'phase':'playing','audio_seconds':.03};on_state('SPEAKING');time.sleep(.03)
                return {'state':'completed','audio_seconds':.03}
            with patch('core.audio_manager.audio_manager.speak',side_effect=voice),patch('core.config.config.SPEECH_TIMEOUT',.07):
                result=await service._say('t','Pedido')
            self.assertTrue(result['delivered'])

    async def test_preview_uses_same_output_boundary_without_saving_voice(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            with patch.object(service,'_say',AsyncMock(return_value={'state':'completed','delivered':True})) as say:
                task=await service.preview_voice('s','Senhor, teste.','piper','natural')
                await service.runners[task['id']]
            self.assertEqual(say.await_args.kwargs['provider'],'piper')
            self.assertEqual(say.await_args.kwargs['profile'],'natural')
            self.assertEqual(service.store.get(task['id'])['usage']['api_calls'],0)
