"""Deterministic tests, isolated vault/data. No remote generation calls."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

TEST_DIR = tempfile.TemporaryDirectory(prefix='jarvis-test-')
ROOT = Path(TEST_DIR.name)
os.environ.update(JARVIS_DATA_DIR=str(ROOT/'data'),JARVIS_HERMES_HOME=str(ROOT/'hermes'),
                  JARVIS_PROVIDER='openai-api',JARVIS_MODEL='',JARVIS_FALLBACK_PROVIDER='',JARVIS_FALLBACK_MODEL='',
                  JARVIS_TTS_PROVIDER='piper',JARVIS_STT_PROVIDER='whisper-local',
                  OBSIDIAN_VAULT_PATH=str(ROOT/'vault'),JARVIS_WORKSPACE_ROOTS=str(ROOT/'workspace'))
(ROOT/'workspace').mkdir()

from core.config import config,settings
from core.task_store import TaskStore
from core.memory_obsidian import ObsidianMemory
from core.jarvis_tools import ToolService
from core.hermes_runtime import HermesRuntime,runtime,worker_env
from core.hermes_worker import bounded_history
from core.audio_manager import speech_text,AudioManager

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_vault_search_update_restart_delete(self):
        v = ObsidianMemory(self.base/'vault',self.base/'idx.sqlite')
        result = v.write('Knowledge/Preferência.md','# Café\nPrefiro café sem açúcar.\n')
        self.assertTrue(result['verified'])
        self.assertEqual(len(v.search('cafe')),1)
        fresh = ObsidianMemory(self.base/'vault',self.base/'idx.sqlite')
        read = fresh.read('Knowledge/Preferência.md')
        self.assertIn('sem açúcar',read['content'])
        fresh.write(read['path'],'# Chá\nAgora prefiro chá.',read['sha256'])
        self.assertFalse(fresh.search('açúcar'))
        self.assertTrue(fresh.search('prefiro'))
        (fresh.vault_dir/read['path']).unlink()
        self.assertFalse(fresh.search('prefiro'))

    def test_vault_optimistic_write_and_paths(self):
        v = ObsidianMemory(self.base/'vault',self.base/'idx.sqlite')
        v.write('Nota.md','Original')
        with self.assertRaises(ValueError):v.write('Nota.md','lost update')
        for path in ('../escape.md','.env','../vault2/escape.md','.obsidian/x.md'):
            with self.assertRaises((PermissionError,ValueError)):v.write(path,'x')

    def test_no_secrets_in_vault(self):
        v=ObsidianMemory(self.base/'vault',self.base/'idx.sqlite')
        with patch.dict(os.environ,{'PRIVATE_API_KEY':'very-private-fixture-123456'}):
            v.write('safe.md','key: very-private-fixture-123456')
            self.assertNotIn('very-private',v.read('safe.md')['content'])

    def test_ledger_duplicate_and_restart(self):
        store = TaskStore(self.base/'tasks.sqlite')
        self.assertTrue(store.create('one','session','test'))
        self.assertFalse(store.create('one','session','test'))
        with self.assertRaises(ValueError):store.create('one','session','different')
        store.update('one','running')
        fresh=TaskStore(self.base/'tasks.sqlite');fresh.recover()
        self.assertEqual(fresh.get('one')['state'],'interrupted')

    def test_tool_effect_once_and_uncertain(self):
        store=TaskStore(self.base/'tasks.sqlite');store.create('one','s','write')
        tool=ToolService('one',store=store)
        request={'action':'file_write','path':'once.txt','content':'hello'}
        result=tool.execute(request)
        self.assertTrue(result['verified'])
        replay=tool.execute(request)
        self.assertTrue(replay['replayed_checkpoint'])
        self.assertEqual((ROOT/'workspace/once.txt').read_text(),'hello')
        store.claim_tool('one','uncertain','file_write')
        with self.assertRaises(RuntimeError):store.claim_tool('one','uncertain','file_write')

    def test_file_hash_and_command_verification(self):
        store=TaskStore(self.base/'tasks.sqlite');store.create('two','s','test')
        tool=ToolService('two',store=store)
        result=tool.execute({'action':'file_write','path':'test_sample.py','content':'import unittest\nclass Works(unittest.TestCase):\n def test_ok(self): self.assertEqual(2+2,4)\n'})
        self.assertTrue(result['verified'])
        read=tool.execute({'action':'file_read','path':'test_sample.py'})
        self.assertEqual(read['sha256'],result['sha256'])
        checked=tool.execute({'action':'run_check','check':'unittest'})
        self.assertEqual(checked['exit_code'],0)
        self.assertIn('OK',checked['output'])
        fail=tool.execute({'action':'file_write','path':'test_sample.py','content':'replacement'})
        self.assertFalse(fail['verified'])

    def test_memory_native_restarts_correct_delete(self):
        async def check():
            bridge=HermesRuntime()
            async def call(**args):return await bridge.run({'operation':'memory','args':args},timeout=40)
            result=await call(action='memory_add',content='Prefiro respostas concisas de teste.',source='user_statement')
            self.assertTrue(result['verified'])
            read=await call(action='memory_list')
            self.assertTrue(any('concisas de teste' in t for t in read['user']))
            corrected=await call(action='memory_patch',target='user',old_text='concisas de teste',content='detalhadas de teste')
            self.assertTrue(corrected['verified'])
            deleted=await call(action='memory_remove',target='user',old_text='detalhadas de teste')
            self.assertTrue(deleted['verified'])
            final=await call(action='memory_list')
            self.assertFalse(any('de teste' in t for t in final['user']))
        asyncio.run(check())

    def test_complete_turn_context_bound(self):
        messages=[{'role':'user','content':'old'*1000},{'role':'assistant','tool_calls':[{'id':'call1'}]},
            {'role':'tool','tool_call_id':'call1','content':'result'}, {'role':'assistant','content':'done'},
            {'role':'user','content':'new'},{'role':'assistant','content':'answer'}]
        reduced=bounded_history(messages,1000)
        self.assertEqual(len(reduced),2)
        self.assertEqual(reduced[0]['content'],'new')

    def test_speech_cleanup_and_limit(self):
        text=speech_text('# Olá **senhor**.\n```python\nprint(1)\n```\n[fonte](https://x.com)\nhttps://x.com')
        self.assertNotIn('print',text);self.assertNotIn('https',text);self.assertNotIn('*',text)
        self.assertLess(len(speech_text('Olá. '*1000)),800)

    def test_cancel_during_synthesis_never_plays(self):
        audio=AudioManager();started=threading.Event();release=threading.Event()
        async def synth(*args):
            started.set();await asyncio.to_thread(release.wait)
        with patch.object(audio,'synthesize',synth),patch('sounddevice.play') as play:
            worker=threading.Thread(target=audio.speak,args=('Teste',))
            worker.start();self.assertTrue(started.wait(5));audio.stop();release.set();worker.join(5)
            self.assertFalse(worker.is_alive());play.assert_not_called()

class LocalAudioTests(unittest.TestCase):
    def test_neural_voice_loads_once_from_local_files_on_cpu(self):
        from core.neural_voice import NeuralVoice
        folder=ROOT/'piper-fixture';folder.mkdir(exist_ok=True)
        model=folder/'voice.onnx';model.write_bytes(b'fixture')
        model.with_suffix('.onnx.json').write_text('{}',encoding='utf-8')
        voice=NeuralVoice()
        with patch.object(config,'PIPER_MODEL_PATH',model),patch('onnxruntime.InferenceSession') as session, \
             patch('piper.PiperConfig.from_dict'),patch('piper.PiperVoice') as piper, \
             patch('socket.create_connection',side_effect=AssertionError('Voz deve ser local.')):
            self.assertIs(voice.prepare(),voice.prepare())
            session.assert_called_once();piper.assert_called_once()
            self.assertEqual(session.call_args.kwargs['providers'],['CPUExecutionProvider'])

    def test_neural_voice_missing_assets_fails_without_network(self):
        from core.neural_voice import NeuralVoice
        with patch.object(config,'PIPER_MODEL_PATH',ROOT/'missing.onnx'), \
             patch('socket.create_connection',side_effect=AssertionError('Não baixar durante a fala.')):
            with self.assertRaisesRegex(ValueError,'setup_voice'):NeuralVoice().prepare()

    def test_whisper_loads_once_from_prepared_files_without_downloads(self):
        folder=ROOT/'whisper-fixture';folder.mkdir(exist_ok=True);(folder/'model.bin').write_bytes(b'fixture')
        audio=AudioManager()
        with patch.object(config,'WHISPER_PATH',folder),patch('faster_whisper.WhisperModel') as model:
            self.assertIs(audio.prepare_local_transcriber(),audio.prepare_local_transcriber())
            model.assert_called_once()
            self.assertTrue(model.call_args.kwargs['local_files_only'])
            self.assertEqual(model.call_args.kwargs['device'],'cpu')

    def test_missing_local_model_fails_without_downloading(self):
        audio=AudioManager()
        with patch.object(config,'WHISPER_PATH',ROOT/'missing-whisper'),patch('faster_whisper.WhisperModel') as model:
            with self.assertRaisesRegex(ValueError,'setup_voice'):audio.prepare_local_transcriber()
            model.assert_not_called()

    def test_native_rate_audio_is_resampled_for_local_transcription(self):
        import numpy as np
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        audio=AudioManager();transcriber=MagicMock()
        transcriber.transcribe.return_value=([SimpleNamespace(text='Olá, Jarvis.')],None)
        with patch('core.audio_manager.settings',return_value={'stt_provider':'whisper-local'}), \
             patch.object(audio,'prepare_local_transcriber',return_value=transcriber), \
             patch('socket.create_connection',side_effect=AssertionError('Transcrição deve ser local.')):
            self.assertEqual(audio.transcribe_audio(np.zeros((48000,1),dtype=np.float32),48000),'Olá, Jarvis.')
        samples=transcriber.transcribe.call_args.args[0]
        self.assertEqual(len(samples),16000)
        self.assertEqual(samples.dtype,np.float32)

class ModelCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_gemini_catalog_excludes_specialized_models(self):
        import httpx
        from unittest.mock import AsyncMock
        from core.hermes_runtime import list_models
        entries=[{'name':'models/'+name,'supportedGenerationMethods':['generateContent']} for name in
                 ('gemini-2.5-flash','gemini-2.5-flash-image','gemini-2.5-pro-preview-tts',
                  'gemini-3.5-transcribe','lyria-3-pro-preview','gemini-2.5-flash')]
        entries.append({'name':'models/gemini-embedding','supportedGenerationMethods':['embedContent']})
        response=httpx.Response(200,json={'models':entries})
        with patch('core.hermes_runtime.provider_key',return_value='fixture'),patch('core.hermes_runtime.httpx.AsyncClient') as client:
            client.return_value.__aenter__.return_value.get=AsyncMock(return_value=response)
            self.assertEqual(await list_models('gemini'),['gemini-2.5-flash'])

    async def test_catalog_authentication_error_is_actionable_and_redacted(self):
        import httpx
        from unittest.mock import AsyncMock
        from core.hermes_runtime import list_models
        response=httpx.Response(403,json={'error':{'message':'fixture-secret'}})
        with patch('core.hermes_runtime.provider_key',return_value='fixture-secret'),patch('core.hermes_runtime.httpx.AsyncClient') as client:
            client.return_value.__aenter__.return_value.get=AsyncMock(return_value=response)
            with self.assertRaisesRegex(ValueError,'gemini: HTTP 403') as error:await list_models('gemini')
            self.assertNotIn('fixture-secret',str(error.exception))

class MicrophoneTests(unittest.TestCase):
    def test_saved_headset_survives_device_index_changes(self):
        from core.audio_devices import resolve_input
        devices=[{'id':'WASAPI::controller','index':1,'name':'controller','hostapi':'Windows WASAPI'},
                 {'id':'WASAPI::headset','index':30,'name':'headset','hostapi':'Windows WASAPI'}]
        with patch('core.audio_devices.input_devices',return_value=devices),patch('sounddevice.default.device',[1,6]):
            self.assertEqual(resolve_input()['name'],'controller')
            self.assertEqual(resolve_input('WASAPI::headset')['name'],'headset')
            devices[1]['index']=42
            self.assertEqual(resolve_input('WASAPI::headset')['index'],42)
            with self.assertRaisesRegex(ValueError,'indisponível'):resolve_input('unplugged headset')

    def test_headset_uses_native_rate_when_16khz_is_unsupported(self):
        import sounddevice as sd
        from core.audio_devices import capture_parameters
        device={'index':30,'sample_rate':48000}
        with patch('core.audio_devices.resolve_input',return_value=device), \
             patch('sounddevice.check_input_settings',side_effect=[sd.PortAudioError('Invalid sample rate'),None]) as check:
            self.assertEqual(capture_parameters('headset'),(device,48000))
            self.assertEqual([c.kwargs['samplerate'] for c in check.call_args_list],[16000,48000])

    def test_quiet_voice_captured_at_native_rate_then_stops_on_silence(self):
        import itertools
        import numpy as np
        from unittest.mock import MagicMock
        audio=AudioManager();device={'index':30,'name':'headset','hostapi':'Windows WASAPI'}
        stream=MagicMock();stream.__enter__.return_value=stream
        speech=np.full((2400,1),.006,dtype=np.float32)
        quiet=np.zeros_like(speech)
        stream.read.side_effect=itertools.chain([(speech,False)],itertools.repeat((quiet,False)))
        with patch('core.audio_devices.capture_parameters',return_value=(device,48000)), \
             patch('sounddevice.InputStream',return_value=stream) as opened, \
             patch('core.audio_manager.time.monotonic',side_effect=itertools.count(0,.05)), \
             patch.object(config,'VAD_THRESHOLD',.004):
            captured=audio.record_phrase()
        self.assertIsNotNone(captured)
        self.assertGreater(float(captured.max()),.005)
        self.assertEqual(opened.call_args.kwargs['samplerate'],48000)
        self.assertTrue(audio.last_capture['speech_detected'])
        self.assertEqual(audio.last_capture['reason'],'silence')

    def test_transcription_receives_actual_capture_rate_and_skips_no_signal(self):
        audio=AudioManager();audio.last_capture={'sample_rate':48000}
        samples=object()
        with patch.object(audio,'record_phrase',return_value=samples), \
             patch.object(audio,'transcribe_audio',return_value='Olá Jarvis') as transcribe:
            self.assertEqual(audio.listen_and_transcribe(),'Olá Jarvis')
            transcribe.assert_called_once_with(samples,samplerate=48000)
        with patch.object(audio,'record_phrase',return_value=None),patch.object(audio,'transcribe_audio') as transcribe:
            self.assertIsNone(audio.listen_and_transcribe())
            transcribe.assert_not_called()

class QwenVoiceTests(unittest.TestCase):
    def test_cancel_before_loading_does_not_spawn(self):
        from core.qwen_voice import QwenVoice,QwenVoiceCancelled
        event=threading.Event();event.set();voice=QwenVoice()
        with patch('core.qwen_voice.subprocess.Popen') as spawn:
            with self.assertRaises(QwenVoiceCancelled):voice.prepare(event)
            spawn.assert_not_called()

    def test_worker_env_has_no_api_keys_and_gpu_handshake_is_rejected(self):
        import io
        from unittest.mock import MagicMock
        from core.qwen_voice import QwenVoice,QwenVoiceError
        base=ROOT/'qwen-fixture';folder=base/'.runtime/voice-lab/model';folder.mkdir(parents=True,exist_ok=True)
        (folder/'manifest.json').write_text('{}')
        process=MagicMock();process.poll.return_value=None
        process.stdout=io.StringIO(json.dumps({'state':'ready','providers':['CUDAExecutionProvider']})+'\n')
        voice=QwenVoice()
        with patch.object(config,'BASE_DIR',base),patch.dict(os.environ,{'PRIVATE_API_KEY':'fixture-secret'}), \
             patch('core.qwen_voice.subprocess.Popen',return_value=process) as spawn,patch.object(voice,'close') as close:
            with self.assertRaisesRegex(QwenVoiceError,'CPU'):voice.prepare()
            env=spawn.call_args.kwargs['env']
            self.assertEqual(env['CUDA_VISIBLE_DEVICES'],'-1');self.assertNotIn('PRIVATE_API_KEY',env)
            self.assertNotIn('GEMINI_API_KEY',env);self.assertNotIn('FISH_API_KEY',env)
            self.assertGreaterEqual(close.call_count,2)

    def test_prepared_worker_is_reused_without_loading_again(self):
        from unittest.mock import MagicMock
        from core.qwen_voice import QwenVoice
        voice=QwenVoice();voice._process=MagicMock();voice._process.poll.return_value=None
        voice._ready=True;voice._channel=object()
        with patch('core.qwen_voice.subprocess.Popen') as spawn,patch.object(voice,'_release_later'):
            voice.prepare();voice.prepare();spawn.assert_not_called()

    def test_memory_pressure_stops_inference_wait(self):
        import queue
        from types import SimpleNamespace
        from core.qwen_voice import QwenVoice,QwenVoiceError
        with patch('core.qwen_voice.psutil.virtual_memory',return_value=SimpleNamespace(available=1024**3)):
            with self.assertRaisesRegex(QwenVoiceError,'RAM'):QwenVoice()._wait(queue.Queue(),None,float('inf'))

    def test_cancel_removes_partial_output_and_closes_worker(self):
        import queue
        from unittest.mock import MagicMock
        from core.qwen_voice import QwenVoice,QwenVoiceCancelled
        voice=QwenVoice();voice._process=MagicMock();path=ROOT/'partial-qwen.wav';path.write_bytes(b'partial')
        with patch.object(voice,'_prepare',return_value=queue.Queue()), \
             patch.object(voice,'_wait',side_effect=QwenVoiceCancelled),patch.object(voice,'close') as close:
            with self.assertRaises(QwenVoiceCancelled):voice.synthesize('Senhor.',path)
            close.assert_called_once();self.assertFalse(path.exists())

    def test_cancel_while_waiting_for_worker_eof_is_not_a_failure(self):
        from unittest.mock import MagicMock
        from core.qwen_voice import QwenVoice,QwenVoiceCancelled
        event=threading.Event();channel=MagicMock()
        def eof(**kwargs):
            event.set()
            return {'state':'closed'}
        channel.get.side_effect=eof
        with self.assertRaises(QwenVoiceCancelled):QwenVoice()._wait(channel,event,float('inf'))

    def test_idle_release_waits_until_request_finishes(self):
        from core.qwen_voice import QwenVoice
        voice=QwenVoice()
        with patch.object(voice,'close') as close:
            with voice._request_lock:
                other=threading.Thread(target=voice._idle);other.start();other.join(2)
                close.assert_not_called()
            voice._idle();close.assert_called_once()


class FishAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_voice_and_explicit_engine_are_sent_with_backend_key(self):
        import httpx
        from core.fish_voice import synthesize,VOICE_ID
        calls=[]
        def handle(request):
            calls.append(request)
            self.assertEqual(str(request.url),'https://api.fish.audio/v1/tts')
            self.assertEqual(request.headers['Authorization'],'Bearer fixture-fish-key')
            self.assertEqual(request.headers['model'],'s2.1-pro-free')
            self.assertEqual(json.loads(request.content)['reference_id'],VOICE_ID)
            self.assertEqual(VOICE_ID,'a5b93aeddcc948c19ea04f0afe9d178c')
            return httpx.Response(200,headers={'content-type':'audio/mpeg'},content=b'fixture-audio')
        path=ROOT/'fish.mp3'
        with patch('core.fish_voice.provider_key',return_value='fixture-fish-key'),patch.object(config,'FISH_TTS_MODEL','s2.1-pro-free'):
            await synthesize('Às suas ordens, Senhor.',path,transport=httpx.MockTransport(handle))
        self.assertEqual(path.read_bytes(),b'fixture-audio');self.assertEqual(len(calls),1)

    async def test_missing_key_or_invalid_engine_does_not_contact_service(self):
        from core.fish_voice import synthesize,FishVoiceError
        with patch('core.fish_voice.provider_key',return_value=''),patch('core.fish_voice.httpx.AsyncClient') as client:
            with self.assertRaisesRegex(FishVoiceError,'FISH_API_KEY'):await synthesize('teste',ROOT/'unused.mp3')
            client.assert_not_called()
        with patch('core.fish_voice.provider_key',return_value='fixture'),patch.object(config,'FISH_TTS_MODEL','typo'), \
             patch('core.fish_voice.httpx.AsyncClient') as client:
            with self.assertRaisesRegex(FishVoiceError,'FISH_TTS_MODEL'):await synthesize('teste',ROOT/'unused.mp3')
            client.assert_not_called()

    async def test_service_errors_never_retry_or_expose_provider_body(self):
        import httpx
        from core.fish_voice import synthesize,FishVoiceError
        for status in (401,402,403,404,429,503):
            with self.subTest(status=status):
                calls=[]
                def handle(request):
                    calls.append(request)
                    return httpx.Response(status,json={'message':'private-provider-fixture'})
                with patch('core.fish_voice.provider_key',return_value='fixture'):
                    with self.assertRaises(FishVoiceError) as error:
                        await synthesize('teste',ROOT/'error.mp3',transport=httpx.MockTransport(handle))
                self.assertNotIn('private-provider-fixture',str(error.exception))
                self.assertEqual(len(calls),1)
                self.assertFalse((ROOT/'error.mp3').exists())

    async def test_cancel_pending_request_closes_it_without_audio(self):
        import httpx
        from core.fish_voice import synthesize,FishVoiceCancelled
        cancel=threading.Event();started=asyncio.Event();closed=asyncio.Event()
        async def handle(request):
            started.set()
            try:await asyncio.Event().wait()
            finally:closed.set()
        with patch('core.fish_voice.provider_key',return_value='fixture'):
            task=asyncio.create_task(synthesize('teste',ROOT/'cancel.mp3',cancel,transport=httpx.MockTransport(handle)))
            await asyncio.wait_for(started.wait(),2);cancel.set()
            with self.assertRaises(FishVoiceCancelled):await asyncio.wait_for(task,2)
        self.assertTrue(closed.is_set());self.assertFalse((ROOT/'cancel.mp3').exists())

    async def test_non_audio_and_empty_response_are_rejected(self):
        import httpx
        from core.fish_voice import synthesize,FishVoiceError
        for headers,content in (({'content-type':'application/json'},b'{}'),({'content-type':'audio/mpeg'},b'')):
            with patch('core.fish_voice.provider_key',return_value='fixture'):
                with self.assertRaises(FishVoiceError):
                    await synthesize('teste',ROOT/'invalid.mp3',transport=httpx.MockTransport(lambda r:httpx.Response(200,headers=headers,content=content)))
            self.assertFalse((ROOT/'invalid.mp3').exists())

    async def test_missing_key_is_visible_to_user_without_playback(self):
        audio=AudioManager()
        with patch('core.audio_manager.settings',return_value={'tts_provider':'fish-audio'}), \
             patch('core.fish_voice.provider_key',return_value=''),patch('sounddevice.play') as play:
            result=await asyncio.to_thread(audio.speak,'Senhor, estou pronto.')
        self.assertEqual(result['state'],'failed');self.assertIn('FISH_API_KEY',result['error'])
        play.assert_not_called()


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import server
        cls.server=server
        cls.client=TestClient(server.app)
        cls.client.__enter__()
        cls.client.get('/')
    @classmethod
    def tearDownClass(cls):cls.client.__exit__(None,None,None)

    def test_origin_and_cookie_guards(self):
        from fastapi.testclient import TestClient
        other=TestClient(self.server.app)
        self.assertEqual(other.get('/api/settings').status_code,403)
        self.assertEqual(self.client.post('/api/shutdown',headers={'Origin':'https://attacker.invalid'}).status_code,403)
        self.assertEqual(self.client.get('/api/settings',headers={'Host':'attacker.invalid'}).status_code,403)

    def test_secret_settings_rejected(self):
        self.assertEqual(self.client.post('/api/settings',json={'OPENAI_API_KEY':'fixture'}).status_code,400)
        response=self.client.get('/api/settings')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('OPENAI_API_KEY',response.text)

    def test_neural_voice_selection_preserves_ai_and_microphone(self):
        before=settings()
        response=self.client.post('/api/settings',json={'tts_provider':'piper'})
        self.assertEqual(response.status_code,200)
        after=settings()
        for key in ('provider','model','input_device','stt_provider'):
            self.assertEqual(before[key],after[key])

    def test_fish_voice_preserves_ai_microphone_and_hides_key(self):
        before=settings()
        with patch.dict(os.environ,{'FISH_API_KEY':'private-fish-api-fixture'}):
            response=self.client.post('/api/settings',json={'tts_provider':'fish-audio'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['fish_voice']['voice_id'],'a5b93aeddcc948c19ea04f0afe9d178c')
        self.assertTrue(response.json()['credentials']['fish-audio'])
        self.assertNotIn('private-fish-api-fixture',response.text)
        for key in ('provider','model','input_device','stt_provider'):
            self.assertEqual(before[key],settings()[key])
        self.assertEqual(self.client.post('/api/settings',json={'FISH_API_KEY':'fixture'}).status_code,400)

    def test_qwen_selection_preserves_ai_stt_and_microphone(self):
        before=settings()
        response=self.client.post('/api/settings',json={'tts_provider':'qwen-local'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['qwen_voice']['device'],'CPU')
        for key in ('provider','model','input_device','stt_provider'):
            self.assertEqual(before[key],settings()[key])

    def test_microphone_selection_is_validated_and_persisted(self):
        device={'id':'WASAPI::fixture headset','name':'fixture headset','index':42}
        with patch('core.audio_devices.resolve_input',return_value=device), \
             patch('core.audio_devices.input_devices',return_value=[device]):
            response=self.client.post('/api/settings',json={'input_device':device['id']})
            self.assertEqual(response.status_code,200)
            self.assertEqual(settings()['input_device'],device['id'])
            listing=self.client.get('/api/audio/devices').json()
            self.assertEqual(listing['selected'],device['id'])
        with patch('core.audio_devices.resolve_input',side_effect=ValueError('Microfone indisponível')):
            self.assertEqual(self.client.post('/api/settings',json={'input_device':'missing'}).status_code,400)
        self.client.post('/api/settings',json={'input_device':''})

    def test_task_without_model_fails_visibly_and_deduplicates(self):
        body={'id':'api-no-model','session':'api','command':'Olá'}
        first=self.client.post('/api/command',json=body)
        self.assertEqual(first.status_code,202)
        second=self.client.post('/api/command',json=body)
        self.assertEqual(second.json()['id'],body['id'])
        import time
        for _ in range(20):
            task=self.client.get('/api/tasks/'+body['id']).json()
            if task['state']=='failed':break
            time.sleep(.05)
        self.assertEqual(task['state'],'failed');self.assertIn('modelo',task['error'])

    def test_websocket_authenticated(self):
        with self.client.websocket_connect('/ws') as ws:
            self.assertEqual(ws.receive_json()['type'],'init')

    def test_deterministic_shortcut_no_model(self):
        req={'id':'local-status','session':'api','action':'status'}
        first=self.client.post('/api/actions',json=req)
        self.assertEqual(first.status_code,200)
        self.assertEqual(first.json()['state'],'completed')
        self.assertEqual(first.json()['usage']['api_calls'],0)
        self.assertEqual(self.client.post('/api/actions',json=req).json()['id'],req['id'])

class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from core.assistant_service import AssistantService
        self.events=[]
        async def emit(event):self.events.append(event)
        self.service=AssistantService(emit)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT)
        self.service.store=TaskStore(Path(self.temp.name)/'tasks.sqlite')
        self.s={**settings(),'model':'scripted','provider':'openai-api','speech_enabled':False}
        self.patch_settings=patch('core.assistant_service.settings',lambda:self.s);self.patch_settings.start()
        self.patch_keys=patch('core.assistant_service.provider_key',lambda p:'fixture');self.patch_keys.start()
    async def asyncTearDown(self):
        await self.service.close();self.patch_settings.stop();self.patch_keys.stop();self.temp.cleanup()
    async def finish(self,task):
        runner=self.service.runners.get(task['id'])
        if runner:await runner
        return self.service.store.get(task['id'])

    async def test_fallback_visible_before_effects(self):
        calls=[]
        async def run(request,*a,**k):
            calls.append(request['settings']['provider'])
            if len(calls)==1:raise RuntimeError('Simulated authentication failure')
            return {'response':'OK','usage':{'input_tokens':10,'output_tokens':2}}
        self.service.runtime.run=run
        self.s.update(fallback_provider='gemini',fallback_model='scripted-fallback')
        task=await self.service.submit('Teste','s','fallback-test');done=await self.finish(task)
        self.assertEqual(done['state'],'completed');self.assertEqual(calls,['openai-api','gemini'])
        self.assertTrue(any('Fallback configurado' in e.get('text','') for e in self.events))

    async def test_no_fallback_after_effect(self):
        calls=[]
        async def run(request,*a,**k):
            calls.append(1)
            self.service.store.claim_tool(request['id'],'effect','file_write')
            self.service.store.finish_tool(request['id'],'effect',{'verified':True})
            raise RuntimeError('Simulated provider outage after effect')
        self.service.runtime.run=run;self.s.update(fallback_provider='gemini',fallback_model='scripted')
        done=await self.finish(await self.service.submit('Teste','s','effect-fallback'))
        self.assertEqual(done['state'],'failed');self.assertEqual(len(calls),1)

    async def test_cancel_running(self):
        began=asyncio.Event();release=asyncio.Event()
        async def run(*a,**k):began.set();await release.wait();return {'response':'ignored'}
        async def cancel(*a):release.set()
        self.service.runtime.run=run;self.service.runtime.cancel=cancel
        task=await self.service.submit('Teste','s','cancel-test');await began.wait()
        await self.service.cancel(task['id']);done=await self.finish(task)
        self.assertEqual(done['state'],'cancelled')

    async def test_budget_and_timeout_are_failures(self):
        async def run(*a,**k):raise TimeoutError()
        self.service.runtime.run=run
        done=await self.finish(await self.service.submit('Teste','s','timeout-test'))
        self.assertEqual(done['state'],'failed')
        self.assertIn('Tempo limite',done['error'])
        with patch.object(config,'MAX_DAILY_TASKS',0):
            with self.assertRaises(ValueError):await self.service.submit('Teste novo','s','budget-test')

    async def test_failed_tool_cannot_report_done(self):
        async def run(request,*a,**k):
            self.service.store.claim_tool(request['id'],'bad','file_write')
            self.service.store.finish_tool(request['id'],'bad',{'error':'Simulated write failure'})
            return {'response':'Arquivo criado com sucesso!','usage':{'input_tokens':1}}
        self.service.runtime.run=run
        done=await self.finish(await self.service.submit('Teste','s','false-success'))
        self.assertEqual(done['state'],'failed');self.assertIsNone(done['result'])
        self.assertFalse(any(e['type']=='jarvis_response' for e in self.events))

    async def test_resume_with_checkpoints_and_uncertain_block(self):
        self.service.store.create('resume-test','s','Teste')
        self.service.store.update('resume-test','interrupted')
        self.service.store.claim_tool('resume-test','effect','file_write')
        self.service.store.finish_tool('resume-test','effect',{'verified':True})
        async def run(*a,**k):return {'response':'Retomada verificada.'}
        self.service.runtime.run=run
        done=await self.finish(await self.service.resume('resume-test'))
        self.assertEqual(done['state'],'completed')
        self.service.store.create('uncertain','s','Teste')
        self.service.store.update('uncertain','interrupted')
        self.service.store.claim_tool('uncertain','effect','file_write')
        with self.assertRaises(ValueError):await self.service.resume('uncertain')

class HostBridgeTests(unittest.TestCase):
    def test_pdf_text_has_page_source(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter();page=writer.add_blank_page(width=300,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 80 Td (Jarvis document evidence) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
        path=ROOT/'workspace/evidence.pdf';writer.write(path)
        store=TaskStore();store.create('pdf-read','s','read PDF')
        result=ToolService('pdf-read').execute({'action':'file_read','path':'evidence.pdf'})
        self.assertIn('document evidence',result['content']);self.assertEqual(result['page'],1)

    def test_empty_test_suite_is_not_verified(self):
        folder=ROOT/'workspace/empty-tests';folder.mkdir(exist_ok=True)
        store=TaskStore();store.create('empty-tests','s','run tests')
        result=ToolService('empty-tests').execute({'action':'run_check','check':'unittest','path':'empty-tests'})
        self.assertIn(result['exit_code'],(0,5));self.assertFalse(result['verified']);self.assertEqual(result['tests_run'],0)

    def test_skill_requires_behavioral_test_evidence(self):
        store=TaskStore();store.create('syntax-only','s','compile')
        store.claim_tool('syntax-only','check','run_check')
        store.finish_tool('syntax-only','check',{'verified':True,'exit_code':0,'check':'compile','tests_run':0})
        store.update('syntax-only','completed')
        store.create('skill-attempt','s','save skill')
        result=ToolService('skill-attempt').execute({'action':'skill_save','path':'should-not-exist','content':'---\nname: Example\n---\nProcedure','evidence_task':'syntax-only'})
        self.assertIn('error',result);self.assertFalse((config.HERMES_HOME/'skills/should-not-exist/SKILL.md').exists())

    def test_worker_host_document_and_web_dependencies(self):
        # Real worker/host protocol: extraction libraries intentionally live on host.
        from docx import Document
        file=ROOT/'workspace/source.docx'
        document=Document();document.add_paragraph('Preferência de documento: chá verde.');document.save(file)
        async def check():
            store=TaskStore();store.create('host-read','s','Leia documento')
            result=await HermesRuntime().run({'operation':'tool','id':'host-read','args':{'action':'file_read','path':'source.docx'}},timeout=45)
            self.assertIn('chá verde',result['content']);self.assertEqual(result['line'],1)
            self.assertEqual(result['path'],'source.docx')
        asyncio.run(check())

class ScriptedHermesTests(unittest.TestCase):
    """Real Hermes loop + real tools + scripted local provider; NOT cloud validation."""
    def test_hermes_calls_tool_then_interprets_result(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(request)
                has_result=any(m.get('role')=='tool' for m in request.get('messages',[]))
                message=({'role':'assistant','content':'O arquivo foi criado e verificado.'} if has_result else
                    {'role':'assistant','content':None,'tool_calls':[{'id':'jarvis-call-1','type':'function','function':{'name':'jarvis','arguments':json.dumps({'action':'file_write','path':'hermes-proof.txt','content':'Hermes executou esta ferramenta.'})}}]})
                payload={'id':'scripted','object':'chat.completion','created':1,'model':'jarvis-scripted-test','choices':[{'index':0,'message':message,'finish_reason':'stop' if has_result else 'tool_calls'}],'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
                if request.get('stream'):
                    delta=dict(message)
                    if delta.get('tool_calls'):
                        delta['tool_calls']=[{'index':0,**delta['tool_calls'][0]}]
                    chunk={'id':'scripted','object':'chat.completion.chunk','created':1,'model':'jarvis-scripted-test','choices':[{'index':0,'delta':delta,'finish_reason':None}]}
                    final={**chunk,'choices':[{'index':0,'delta':{},'finish_reason':'stop' if has_result else 'tool_calls'}],'usage':payload['usage']}
                    data=('data: '+json.dumps(chunk)+'\n\ndata: '+json.dumps(final)+'\n\ndata: [DONE]\n\n').encode()
                    content_type='text/event-stream'
                else:
                    data=json.dumps(payload).encode();content_type='application/json'
                self.send_response(200);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        store=TaskStore();store.create('hermes-scripted','hermes-session','Crie o arquivo de prova.')
        # Direct official library API, only the test transport is scripted.
        script=Path(__file__).with_name('hermes_probe.py')
        env=worker_env();env['JARVIS_PROBE_URL']=f'http://127.0.0.1:{http.server_port}/v1'
        try:
            result=subprocess.run([runtime()['executable'],str(script)],env=env,cwd=config.BASE_DIR,capture_output=True,text=True,encoding='utf-8',timeout=75)
            self.assertEqual(result.returncode,0,result.stderr[-3000:]+result.stdout[-1000:])
            self.assertTrue((ROOT/'workspace/hermes-proof.txt').exists())
            self.assertGreaterEqual(len(requests),2)
            tool_results=[m for r in requests for m in r.get('messages',[]) if m.get('role')=='tool']
            self.assertTrue(any(m.get('tool_call_id')=='jarvis-call-1' for m in tool_results))
            self.assertTrue(any('verified' in m.get('content','') for m in tool_results))
        finally:
            http.shutdown();http.server_close();thread.join(3)

if __name__=='__main__':unittest.main()
