"""Semantic extraction decisions are mocked here; real CPU/browser reports are separate."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock,Mock,patch

CASES=[
 ('Toca pra mim a música TAUZ MADARA',['TAUZ MADARA'],'TAUZ MADARA'),
 ('JARVIS, por favor, coloca TAUZ MADARA no YouTube',['TAUZ MADARA'],'TAUZ MADARA'),
 ('Quero ouvir Razões e Emoções do NX Zero',['Razões e Emoções','NX Zero'],'Razões e Emoções NX Zero'),
 ('Boa tarde, JARVIS, consegue tocar uma música do Guns N’ Roses pra mim?',['Guns N’ Roses'],'Guns N’ Roses'),
 ('Pesquisa por TAUZ MADARA e coloca pra tocar',['TAUZ MADARA'],'TAUZ MADARA'),
 ('Toque a música “Pra Mim”',['Pra Mim'],'Pra Mim'),
 ('Boa noite, Javis. Toca pra mim a música TAUS MADARA.',['TAUS MADARA'],'TAUS MADARA'),
 ('Toque a música "Toca"',['Toca'],'Toca'),
 ('Quero ouvir "Música Para Mim"',['Música Para Mim'],'Música Para Mim'),
 ('Coloca a música "Outra Deles"',['Outra Deles'],'Outra Deles'),
 ('Quero ouvir Toca Pra Mim',['Toca Pra Mim'],'Toca Pra Mim'),
 ('Toque a música Pra Mim',['Pra Mim'],'Pra Mim')]

def answer(parts,service='unspecified'):
    return {'action':'search_and_play','content_spans':parts,'service':service}

class MusicIntentTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_admission_replaces_a_later_wrong_model_query(self):
        from core.music_intent import validate
        from core.task_store import TaskStore
        from core.jarvis_tools import ToolService
        source='Toca pra mim a música TAUZ MADARA'
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('admission','music-admission',source)
            tools=ToolService('admission',store=store)
            tools.context.music_intent={**validate(answer(['TAUZ MADARA']),source),'original_transcription':source}
            try:
                with patch.object(tools,'_dispatch',return_value={'verified':True}) as effect:
                    tools.execute({'action':'play_music','query':'pra mim a música TAUS MADARA'})
                    self.assertEqual(effect.call_args.args[0]['query'],'TAUZ MADARA')
            finally:tools.context.music_intent={}

    async def test_final_query_recorder_matches_the_url_given_to_the_browser(self):
        from urllib.parse import parse_qs,urlparse
        from core.youtube_control import play_youtube
        rows=[{'video_id':f'tauz{i:07d}','title':'TAUZ MADARA','channel':'TAUZ','score':10,'coverage':1} for i in range(3)]
        page=Mock();record=Mock()
        with patch('core.youtube_control._candidates',return_value=rows),patch('core.youtube_control._confirm_playback',return_value={'verified':True,'playback_confirmed':True}):
            result=play_youtube(page,'TAUZ MADARA',record_query=record)
            first=page.goto.call_args_list[0].args[0]
            self.assertEqual(parse_qs(urlparse(first).query)['search_query'],['TAUZ MADARA'])
            record.assert_called_once_with('TAUZ MADARA');self.assertEqual(result['effective_query'],'TAUZ MADARA')

    async def test_source_spans_preserve_names_titles_and_remove_only_instructions(self):
        from core.music_intent import interpret,local_model,requested
        for source,spans,expected in CASES:
            with self.subTest(source=source),patch.object(local_model,'plan',AsyncMock(return_value=answer(spans))):
                self.assertTrue(requested(source))
                result=await interpret(source,{})
                self.assertTrue(result['accepted'],result);self.assertEqual(result['query'],expected)

    async def test_unsafe_empty_residual_or_rewritten_content_is_not_searched(self):
        from core.music_intent import validate
        for source,decision in [
            ('Toca pra mim a música TAUZ MADARA',answer(['pra mim a música TAUZ MADARA'])),
            ('Toca TAUZ MADARA',answer(['TAUS MADARA'])),
            ('Toca TAUZ MADARA',answer(['TAUZ'])),
            ('Toca TAUS MADARA',answer(['TAUZ MADARA'])),
            ('Toque uma música',answer(['uma música'])),
            ('Toque uma música',answer([])),
            ('Toca pra mim uma música',answer(['Toca pra mim uma música'])),
            ('Não toque TAUZ MADARA',answer(['TAUZ MADARA'])),
            ('Toque a música "Pra Mim"',answer(['Mim'])),
            ('Toca TAUZ MADARA no Spotify',answer(['TAUZ MADARA'],'unsupported'))]:
            with self.subTest(source=source):self.assertFalse(validate(decision,source)['accepted'])

    async def test_existing_controls_and_non_music_tasks_bypass_extraction(self):
        from core.music_intent import requested
        for source in ('Pause a música','Volume para 47%','Próxima música','Outra deles','Toque a primeira sugestão',
            'Anote: toca pra mim TAUZ MADARA','Coloca um alarme em 10 minutos','Abra o YouTube'):
            self.assertFalse(requested(source),source)

    async def test_runtime_and_admission_cannot_restore_the_old_conversational_query(self):
        from core.music_intent import validate
        from core.local_runtime import LocalRuntime
        from core.jarvis_tools import ToolService
        from core.task_store import TaskStore
        source='Toca pra mim a música TAUZ MADARA'
        intent={**validate(answer(['TAUZ MADARA']),source),'original_transcription':source,'model_attempted':True,'model_usage':{'input_tokens':50,'output_tokens':20,'vram_bytes':0}}
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('extract','extraction-regression',source)
            with patch('core.music_intent.interpret',AsyncMock(return_value=intent)),patch.object(ToolService,'_dispatch',return_value={'verified':True,'message':'Playing observed'}) as effect:
                result=await LocalRuntime(store).run({'id':'extract','command':source,'direct_plan':{'steps':[{'action':'play_music','target':'pra mim a música TAUS MADARA'}]}},AsyncMock())
                self.assertEqual(effect.call_args.args[0]['query'],'TAUZ MADARA');self.assertFalse(result.get('error'))
                trace=store.get('extract')['input'];self.assertEqual(trace['intent'][0]['query'],'TAUZ MADARA');self.assertEqual(trace['music_intent']['query'],'TAUZ MADARA')
                self.assertEqual(result['usage']['local_model_calls'],1)

    async def test_missing_content_or_model_failure_has_no_tool_effect(self):
        from core.local_runtime import LocalRuntime
        from core.jarvis_tools import ToolService
        from core.task_store import TaskStore
        for reason in ('missing_content','model_unavailable'):
            with tempfile.TemporaryDirectory() as folder:
                store=TaskStore(Path(folder)/'tasks.db');store.create('empty',reason,'Toca pra mim uma música')
                with patch('core.music_intent.interpret',AsyncMock(return_value={'accepted':False,'reason':reason,'query':''})),patch.object(ToolService,'_dispatch') as effect:
                    result=await LocalRuntime(store).run({'id':'empty','command':'Toca pra mim uma música'},AsyncMock())
                    effect.assert_not_called()
                    key='error' if reason=='model_unavailable' else 'response'
                    self.assertIn('Senhor',result[key])
