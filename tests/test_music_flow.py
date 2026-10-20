"""Controlled decisions, browser/audio doubles. Live validation is separate."""
import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch


def row(video,title,channel='TAUZ',position=1):return {'video_id':video,'title':title,'channel':channel,'position':position,'score':1,'coverage':.33}


def goal():return {'accepted':True,'query':'happy do Minecraft do Taus','title':'happy do Minecraft','artist':'Taus','original_transcription':'Toque happy do Minecraft do Taus'}


class ContextualChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_recorded_numeric_title_and_split_artist_reach_local_selection(self):
        from core.music_resolution import select_result,local_model,evidence
        rows=[row('QU9c0053UAU',"정국 (Jung Kook) 'Seven (feat. Latto)' Official MV",'HYBE LABELS'),
            row('1QYBiNRu1ok',"정국 (Jung Kook) 'Seven (feat. Latto)' Official Performance Video",'BANGTANTV',2),
            row('1l_BR1I4N5o','Jung Kook - Seven (feat. Latto) (Versão Explícita) (Tradução/Legendado)','Bruno Oliver',3)]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'QU9c0053UAU','confidence':'clear'})) as model:
            result=await select_result('7 de Jungkook',rows,{'query':'7 de Jungkook'})
        self.assertTrue(result['accepted'],result);model.assert_awaited_once();self.assertEqual(len(result['work_groups']),1)
        self.assertTrue(any(m.get('relation')=='number' for m in result['evidence']['QU9c0053UAU']['matches']))
        self.assertFalse(evidence('7 de Jungkook',row('other000001',"Jung Kook - Seventeen",'HYBE LABELS'))['eligible'])

    async def test_recorded_multiple_credits_keep_every_term_with_observed_spelling(self):
        from core.music_resolution import select_result,local_model
        rows=[row('c82zv_5GfV8','A CÚPULA - Hariel, Kadu, Don Juan, Tuto, Kako, Joãozinho VT, Marks, Perera DJ, DJ Boy e DJ GBR','GR6 EXPLODE')]
        query='acúpula de Hariel, Cadu, Don Juan, Tutu, Kaka, João, Zinho, VT, Max, Pereira, DJ, DJBoi e DJBbr'
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'c82zv_5GfV8','confidence':'clear'})):
            result=await select_result(query,rows,{'query':query})
        self.assertTrue(result['accepted'],result)
        self.assertEqual(result['corrected_content'].count('Joãozinho VT'),1)
        self.assertIn('Marks',result['corrected_content'])
        # The actual first YouTube card also used Joãzinho (one missing vowel),
        # independently of the transcriber's split João, Zinho.
        variant=[{**rows[0],'title':rows[0]['title'].replace('Joãozinho','Joãzinho')}]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'c82zv_5GfV8','confidence':'clear'})):
            result=await select_result(query,variant,{'query':query})
        self.assertTrue(result['accepted'],result);self.assertEqual(result['corrected_content'].count('Joãzinho'),1);self.assertIn('VT',result['corrected_content'])
        with patch.object(local_model,'plan',AsyncMock()) as model:
            missing=await select_result(query,[row('other000001','A Cúpula','MC Hariel')],{'query':query})
        self.assertFalse(missing['accepted']);model.assert_not_called()

    async def test_same_work_with_reordered_credits_on_different_channels_is_not_ambiguous(self):
        from core.music_resolution import select_result,local_model
        rows=[row('c82zv_5GfV8','A CÚPULA - Hariel, Kadu, Don Juan, Tuto, Kako, Joãozinho VT, Marks, Perera DJ, DJ Boy e DJ GBR','GR6 EXPLODE'),
            row('MTAjuiFTaA0','A Cúpula','MC Hariel',2),
            row('q2p7nygKCNM','Hariel, Kadu, Don Juan, Tuto, Kako, Joãozinho VT, Marks -A CÚPULA - Perera DJ, DJ Boy e DJ GBR','Som Funk Oficial',12)]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'q2p7nygKCNM','confidence':'clear'})):
            result=await select_result('acúpula de Hariel',rows,{'query':'acúpula de Hariel'})
        self.assertTrue(result['accepted'],result);self.assertEqual(result['candidate_id'],'q2p7nygKCNM');self.assertEqual(len(result['work_groups']),1)

    async def test_third_different_work_and_recording_versions_remain_ambiguous(self):
        from core.music_resolution import select_result,local_model
        for third in (row('happy000003','Mudvayne - Happy (Official Video)','Mudvayne',3),
                      row('happy000003','Pharrell Williams - Happy (Live)','Pharrell Williams',3)):
            rows=[row('happy000001','Pharrell Williams - Happy (Official Video)','Pharrell Williams'),
                row('happy000002','Happy','Pharrell Williams - Topic',2),third]
            with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'happy000001','confidence':'clear'})):
                result=await select_result('Happy',rows,{'query':'Happy','title':'Happy'})
            self.assertFalse(result['accepted'],result);self.assertEqual(result['reason'],'ambiguous_results')

    async def test_bare_instruction_word_gets_bounded_semantic_reextraction(self):
        from core.music_intent import interpret,local_model,validate
        first={'action':'search_and_play','content_spans':['música 7 de Jungkook'],'service':'unspecified'}
        with patch.object(local_model,'plan',AsyncMock(side_effect=[first,{**first,'content_spans':['7','Jungkook']}])) as model:
            result=await interpret('Jarvis, toca música 7 de Jungkook.')
        self.assertTrue(result['accepted'],result);self.assertEqual(result['query'],'7 Jungkook');self.assertEqual(model.await_count,2)
        for source in ('Toque a música Música Para Mim','Toque a música "Música Para Mim"'):
            self.assertTrue(validate({**first,'content_spans':['Música Para Mim']},source)['accepted'])

    async def test_model_role_boundaries_can_repair_leaked_introducer_but_not_drop_content(self):
        from core.music_intent import interpret,local_model,validate_interpretation
        decision={'action':'search_and_play','content_spans':['música 7 de Jungkook'],'title_span':'7','artist_span':'Jungkook','service':'unspecified'}
        with patch.object(local_model,'plan',AsyncMock(return_value=decision)) as model:
            result=await interpret('Jarvis, toca música 7 de Jungkook.')
        self.assertTrue(result['accepted']);self.assertEqual(result['query'],'7 Jungkook');model.assert_awaited_once()
        self.assertEqual(result['span_validation'],'model_literal_roles')
        bad={**decision,'content_spans':['música Rap do Minecraft TAUZ'],'title_span':'Rap','artist_span':'TAUZ'}
        self.assertFalse(validate_interpretation(bad,'Toque música Rap do Minecraft TAUZ')['accepted'])

    async def test_joined_words_are_resolved_only_with_content_and_artist_evidence(self):
        from core.music_resolution import select_result,local_model,evidence
        rows=[row('right000001','Rap do Minecraft | Tauz RapGame 06','Tauz',1)]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'right000001','confidence':'clear'})):
            result=await select_result('rápido Minecraft do Tauz',rows,{'title':'rápido Minecraft','artist':'Tauz'})
        self.assertTrue(result['accepted'],result);self.assertIn('Rap do Minecraft',result['corrected_content'])
        self.assertFalse(evidence('rápido',row('other000001','Rap do','Outro'))['eligible'])
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'right000001','confidence':'clear'})):
            joined=await select_result('rápido, Minecraft do Taus',rows,{'title':'','artist':''})
        self.assertTrue(joined['accepted'],joined);self.assertTrue(joined['evidence']['right000001']['artist_channel'])
        self.assertFalse(evidence('rápido Minecraft',row('other000001','Rap do Minecraft','Minecraft'))['eligible'])

    async def test_rejected_extraction_gets_one_literal_repair_without_losing_unknown_word(self):
        from core.music_intent import interpret,local_model
        first={'action':'search_and_play','content_spans':['Minecraft','Tauz'],'service':'unspecified','title_span':'Minecraft','artist_span':'Tauz'}
        second={**first,'content_spans':['rápido Minecraft','Tauz'],'title_span':'rápido Minecraft'}
        with patch.object(local_model,'plan',AsyncMock(side_effect=[first,second])) as model:
            result=await interpret('Jarvis, toque rápido Minecraft do Tauz')
        self.assertTrue(result['accepted'],result);self.assertIn('rápido',result['query']);self.assertEqual(result['model_calls'],2)
        self.assertEqual(model.await_count,2)
        constrained=model.await_args_list[1].args[1]['properties']['content_spans']['items']['enum']
        self.assertEqual(constrained,['rápido Minecraft do Tauz'])

    async def test_phonetic_terms_need_content_and_artist_and_not_literal_coverage(self):
        from core.music_resolution import select_result,local_model
        rows=[row('other000001','Outro - Rap do Minecraft','Outro',1),row('right000001','Rap do Minecraft | Tauz RapGame 06 (Oficial)','TAUZ',2),
            row('cover000001','TAUZ Rap do Minecraft cover','Cover',3)]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'right000001','confidence':'clear'})):
            result=await select_result(goal()['query'],rows,goal())
        self.assertTrue(result['accepted'],result);self.assertEqual(result['candidate_id'],'right000001')
        self.assertIn('Minecraft',result['corrected_content']);self.assertTrue(result['corrections'])
        self.assertFalse(result['evidence']['other000001']['eligible']);self.assertFalse(result['evidence']['cover000001']['eligible'])

    async def test_author_channel_outweighs_another_upload_with_more_literal_spelling(self):
        from core.music_resolution import select_result,local_model
        rows=[row('LVMHYzVS9Y4','Rap do Minecraft | Tauz RapGame 06','Tauz',1),
              row('8aCd55WCE08','Melhor RAP de MINECRAFT:PLAYER TAUS','Wali_Gamer BR',3)]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'LVMHYzVS9Y4','confidence':'clear'})) as model:
            result=await select_result(goal()['query'],rows,goal())
        self.assertTrue(result['accepted'],result)
        self.assertTrue(result['evidence']['LVMHYzVS9Y4']['artist_channel'])
        allowed=model.call_args.args[1]['properties']['candidate_id']['enum']
        self.assertNotIn('8aCd55WCE08',allowed)

    async def test_publisher_credits_and_topic_upload_do_not_make_same_title_ambiguous(self):
        from core.music_resolution import select_result,local_model
        rows=[row('LVMHYzVS9Y4','Rap do Minecraft | Tauz RapGame 06','Tauz',1),
              row('vfPOShd2PRI','Rap do Minecraft','Tauz - Topic',14)]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'LVMHYzVS9Y4','confidence':'clear'})):
            result=await select_result('rap do Minecraft do Taus',rows,{**goal(),'query':'rap do Minecraft do Taus','title':'rap'})
        self.assertTrue(result['accepted'],result)

    async def test_model_failure_is_failure_not_a_completed_clarification(self):
        from core.local_runtime import LocalRuntime
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('t','unavailable-model','Toque Rap do Minecraft do TAUZ')
            with patch('core.music_intent.interpret',AsyncMock(return_value={'accepted':False,'reason':'model_unavailable','model_attempted':True})):
                result=await LocalRuntime(store).run({'id':'t','command':'Toque Rap do Minecraft do TAUZ'},AsyncMock())
        self.assertIn('error',result);self.assertNotIn('response',result)

    async def test_happy_is_not_globally_replaced_and_ambiguous_matches_do_not_play(self):
        from core.music_resolution import select_result,local_model
        rows=[row('happy000001','Pharrell Williams - Happy (Official Video)','Pharrell Williams',2),row('rappp000001','Outro - Rap','Outro',1)]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'happy000001','confidence':'clear'})):
            result=await select_result('Happy Pharrell Williams',rows,{'query':'Happy Pharrell Williams','title':'Happy','artist':'Pharrell Williams'})
            self.assertTrue(result['accepted']);self.assertFalse(result['corrections'])
        rows=[row('happy000001','Artist A - Happy (Official)','Artist A'),row('happy000002','Artist B - Happy (Official)','Artist B',2)]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'happy000001','confidence':'clear'})):
            result=await select_result('Happy',rows,{'title':'Happy','query':'Happy'})
            self.assertFalse(result['accepted']);self.assertEqual(result['reason'],'ambiguous_results')

    async def test_command_like_words_are_still_title_content_during_selection(self):
        from core.music_resolution import select_result,local_model,evidence
        for title in ('Música','Pra Mim','Toca'):
            rows=[row('title000001',title,'Artist',1)]
            with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'title000001','confidence':'clear'})):
                result=await select_result(title,rows,{'title':title,'query':title,'protected_title':True})
            self.assertTrue(result['accepted'],result)
        self.assertFalse(evidence('Música',row('other000001','Artist - Outra Faixa','Artist'))['eligible'])

    async def test_unknown_id_and_missing_essential_name_are_rejected(self):
        from core.music_resolution import select_result,local_model,reformulate
        rows=[row('right000001','TAUZ - Rap do Minecraft')]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':'invented000','confidence':'clear'})):
            self.assertFalse((await select_result(goal()['query'],rows,goal()))['accepted'])
        with patch.object(local_model,'plan',AsyncMock()) as model:
            self.assertFalse((await select_result('Rap do Minecraft TAUZ',[row('other000001','TAUZ - Rap Game')],goal()))['accepted']);model.assert_not_called()
        self.assertEqual(reformulate('Rap do Minecraft do TAUZ'),'Rap Minecraft TAUZ')

    async def test_term_and_title_corrections_preserve_remaining_identity(self):
        from core.music_intent import apply_correction,is_correction
        text='É rap, não happy';self.assertTrue(is_correction(text))
        result=apply_correction({'action':'search_and_play','operation':'replace_terms','before':'happy','after_spans':['rap']},text,goal())
        self.assertTrue(result['accepted']);self.assertEqual(result['query'],'rap do Minecraft do Taus');self.assertEqual(result['artist'],'Taus')
        next_result=apply_correction({'action':'search_and_play','operation':'replace_title','before':'','after_spans':['Minecraft']},'A música é do Minecraft',result)
        self.assertEqual(next_result['query'],result['query'])
        result=apply_correction({'action':'search_and_play','operation':'replace_request','before':'','after_spans':['Taus Rap Game']},'Não, eu disse Rap do Minecraft do Taus Rap Game',goal())
        self.assertFalse(result['accepted'])
        self.assertEqual(apply_correction({},'É rap, não happy',{})['reason'],'missing_correction_context')


class ExecutionTests(unittest.TestCase):
    def test_partial_read_recovers_without_repeating_search_and_executes_the_accepted_id(self):
        from core.youtube_control import play_youtube,CandidateRows
        page=Mock();page.url='https://www.youtube.com/results';record=Mock()
        desired=row('right000001','Artist - Canção! (Official Video)','Artist',4)
        unrelated=row('other000001','Another track','Other')
        observations=[CandidateRows([],{ 'cards':0,'loading':True}),CandidateRows([unrelated],{'cards':2,'missing':1}),
            *[CandidateRows([unrelated,desired],{'cards':2,'missing':0}) for _ in range(4)]]
        selected=Mock(return_value={'accepted':True,'candidate_id':desired['video_id'],'reason':'observed_content_and_artist'})
        with patch('core.youtube_control._candidates',side_effect=observations),patch('core.youtube_control._manual_gate',return_value=None),patch('core.youtube_control._confirm_playback',return_value={'verified':True,'title':desired['title'],'stage':'playing'}) as player:
            result=play_youtube(page,'Canção Artist',select_result=selected,record_query=record,goal={'task_id':'trace-1','query':'Canção Artist'})
        self.assertTrue(result['verified']);record.assert_called_once_with('Canção Artist')
        self.assertEqual(page.goto.call_count,2);self.assertIn('v=right000001',page.goto.call_args.args[0])
        self.assertEqual(player.call_args.args[1]['video_id'],'right000001');selected.assert_called_once()
        trace=result['music_pipeline'];self.assertEqual(trace['task_id'],'trace-1')
        self.assertEqual([e['stage'] for e in trace['events']],['search_navigation','results_read','selection','video_navigation','playback_verification','final'])
        self.assertEqual(len(trace['events'][1]['snapshots']),6)

    def test_stale_search_document_is_not_used_for_selection(self):
        from core.youtube_control import play_youtube,CandidateRows
        page=Mock();page.url='https://www.youtube.com/results';select=Mock()
        rows=CandidateRows([row('right000001','Artist - Song','Artist')],{'url':'https://www.youtube.com/results?search_query=old'})
        with patch('core.youtube_control._candidates',return_value=rows):
            result=play_youtube(page,'Song Artist',select_result=select)
        self.assertEqual(result['stage'],'results_read_failed');select.assert_not_called();self.assertEqual(page.goto.call_count,1)

    def test_empty_unreadable_page_and_explicit_no_results_have_distinct_outcomes(self):
        from core.youtube_control import play_youtube,CandidateRows
        for explicit in (False,True):
            with self.subTest(explicit=explicit):
                page=Mock();page.url='https://www.youtube.com/results';select=Mock()
                with patch('core.youtube_control._candidates',return_value=CandidateRows([],{'cards':0,'no_results':explicit})),patch('core.youtube_control._manual_gate',return_value=None):
                    result=play_youtube(page,'Song Artist',select_result=select)
                self.assertEqual(result['stage'],'no_results' if explicit else 'results_read_failed');select.assert_not_called()
                self.assertEqual(page.goto.call_count,1)

    def test_no_evidence_never_repeats_connector_only_search_or_claims_ambiguity(self):
        from core.youtube_control import play_youtube
        page=Mock();page.url='https://www.youtube.com/results';record=Mock()
        with patch('core.youtube_control._candidates',return_value=[row('other000001','Other Track','Other')]):
            result=play_youtube(page,'Rap do Minecraft do TAUZ',select_result=lambda *a:{'accepted':False,'reason':'insufficient_evidence'},record_query=record)
        self.assertEqual(result['stage'],'no_matching_result');self.assertEqual(page.goto.call_count,1);record.assert_called_once()
        self.assertEqual(result['search_queries'],['Rap do Minecraft do TAUZ'])

    def test_navigation_and_player_failures_keep_the_selected_stage_and_do_not_research(self):
        from core.youtube_control import play_youtube
        for phase in ('navigation','player','navigation_timeout_after_commit'):
            with self.subTest(phase=phase):
                page=Mock();page.url='https://www.youtube.com/results';desired=row('right000001','Artist - Song','Artist')
                def navigate(url,**kwargs):
                    if '/watch?' in url and phase!='player':
                        if phase=='navigation_timeout_after_commit':page.url=url
                        raise TimeoutError('navigation timeout')
                page.goto.side_effect=navigate
                with patch('core.youtube_control._candidates',return_value=[desired]),patch('core.youtube_control._confirm_playback',side_effect=RuntimeError('player unavailable')) as verify:
                    result=play_youtube(page,'Song Artist',select_result=lambda *a:{'accepted':True,'candidate_id':'right000001'})
                self.assertFalse(result['verified']);self.assertEqual(page.goto.call_count,2)
                self.assertEqual(result['stage'],'video_navigation_failed' if phase=='navigation' else 'playback_failed')
                self.assertIn('encontrei',result['message']);self.assertNotIn('não encontrei',result['message'])
                self.assertEqual(verify.call_count,0 if phase=='navigation' else 1)

    def test_duplicate_tool_event_replays_checkpoint_without_a_second_search(self):
        from core.jarvis_tools import ToolService
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('duplicate-music','duplicate-session','Toque Song Artist')
            tools=ToolService('duplicate-music',store=store);dispatch=Mock(return_value={'verified':True,'search_queries':['Song Artist']})
            with patch.object(tools,'_dispatch',dispatch):
                args={'action':'play_music','query':'Song Artist'}
                tools.execute(args,invocation_id='step:0');replay=tools.execute(args,invocation_id='step:0')
            self.assertTrue(replay['replayed_checkpoint']);dispatch.assert_called_once()

    def test_recognizer_uses_portuguese_and_context_but_keeps_the_raw_transcript(self):
        import numpy as np
        from core.audio_manager import AudioManager
        from core.config import config
        audio=AudioManager();transcriber=Mock();transcriber.transcribe.return_value=([SimpleNamespace(text=' happy do Minecraft do Taus',avg_logprob=-.4)],None)
        with patch('core.audio_manager.settings',return_value={'stt_provider':'whisper-local'}),patch.object(audio,'prepare_local_transcriber',return_value=transcriber):
            text=audio.transcribe_audio(np.zeros((1600,1),dtype=np.float32),vocabulary='Rap do Minecraft TAUZ')
        self.assertEqual(text,'happy do Minecraft do Taus')
        args=transcriber.transcribe.call_args.kwargs;self.assertEqual(args['language'],'pt');self.assertEqual(args['hotwords'],'Rap do Minecraft TAUZ')
        self.assertEqual(args['beam_size'],config.WHISPER_BEAM_SIZE);self.assertFalse(args['condition_on_previous_text'])

    def test_tts_reserves_microphone_until_output_is_drained(self):
        import itertools
        import numpy as np
        from core.audio_manager import AudioManager
        audio=AudioManager()
        async def synthesize(*args):pass
        def output(*args,**kwargs):
            self.assertTrue(audio._mic_lock.locked());self.assertIsNone(audio.listen_and_transcribe())
        with patch('core.audio_manager.settings',return_value={'tts_provider':'qwen-local'}),patch.object(audio,'synthesize',synthesize),patch('soundfile.read',return_value=(np.zeros(20),20)),patch('sounddevice.play',side_effect=output),patch('sounddevice.wait',return_value=None) as drain,patch('core.audio_manager.time.monotonic',side_effect=itertools.count(0,2)):
            result=audio.speak('Senhor, teste de exclusão de captura.')
        self.assertTrue(result['delivered']);drain.assert_called_once();self.assertFalse(audio._mic_lock.locked())

    def test_output_failure_records_cause_and_releases_capture(self):
        import numpy as np
        from core.audio_manager import AudioManager
        audio=AudioManager()
        async def fail(*args):raise RuntimeError('Output device disconnected')
        with patch('core.audio_manager.settings',return_value={'tts_provider':'qwen-local'}),patch.object(audio,'synthesize',fail):
            result=audio.speak('Senhor, teste de falha.')
        self.assertFalse(result['delivered']);self.assertIn('Output device disconnected',result['cause'])
        self.assertFalse(audio._speech_lock.locked());self.assertFalse(audio._mic_lock.locked())
        async def generated(*args):pass
        states=[]
        with patch('core.audio_manager.settings',return_value={'tts_provider':'qwen-local'}),patch.object(audio,'synthesize',generated),patch('soundfile.read',return_value=(np.zeros(20),24000)),patch('sounddevice.play',side_effect=RuntimeError('Output device disconnected')):
            result=audio.speak('Senhor, falha ao iniciar a saída.',on_state=states.append)
        self.assertFalse(result['delivered']);self.assertNotIn('SPEAKING',states)
        self.assertFalse(audio._speech_lock.locked());self.assertFalse(audio._mic_lock.locked())

    def test_cancel_after_model_selection_prevents_late_navigation(self):
        from core.youtube_control import play_youtube
        stop=threading.Event();page=Mock();page.url='https://www.youtube.com/results'
        rows=[row('right000001','TAUZ - Rap do Minecraft')]*3
        def choose(*args):stop.set();return {'accepted':True,'candidate_id':'right000001'}
        with patch('core.youtube_control._candidates',return_value=rows):
            with self.assertRaisesRegex(ValueError,'interrompida'):play_youtube(page,goal()['query'],cancelled=stop.is_set,select_result=choose,goal=goal())
        self.assertEqual(page.goto.call_count,1);self.assertIn('/results?',page.goto.call_args.args[0])

    def test_search_read_failure_is_not_music_not_found(self):
        from core.youtube_control import play_youtube
        page=Mock();page.url='https://www.youtube.com/results'
        with patch('core.youtube_control._candidates',side_effect=RuntimeError('DOM changed')):
            result=play_youtube(page,'Rap Minecraft TAUZ',select_result=Mock(),goal=goal())
        self.assertEqual(result['stage'],'results_read_failed');self.assertFalse(result['verified'])

    def test_existing_search_tab_is_reused_even_without_a_live_player(self):
        from core.browser_control import BrowserControl
        from core.operational_context import OperationalContext
        b=BrowserControl(mode='chrome');page=Mock();page.url='https://www.youtube.com/results?search_query=old';page.is_closed.return_value=False
        other=Mock();other.url='https://www.youtube.com/watch?v=other000001';other.is_closed.return_value=False
        b.context=Mock();b.context.pages=[page,other];ctx=OperationalContext('reuse',media_tab_id='known')
        try:
            with patch.object(b,'_live_tabs',return_value={'known':page}):self.assertIs(b._music_page(ctx),page)
            ctx.media_tab_id='';ctx.music_goal={'last_search_query':'old'}
            with patch.object(b,'_live_tabs',return_value={}):self.assertIs(b._music_page(ctx),page)
            b.context.new_page.assert_not_called();page.goto.assert_not_called()
        finally:b.context=None;b.executor.shutdown(wait=True)


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_failure_clarification_and_tts_failure_have_one_final_boundary(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        from core.audio_manager import audio_manager
        selected={'provider':'gemini','model':'fixture','speech_enabled':True}
        for index,result in enumerate(({'response':'Reprodução confirmada'}, {'error':'Encontrei o vídeo, mas a reprodução falhou'}, {'response':'Qual artista deseja ouvir?'})):
            with tempfile.TemporaryDirectory() as folder:
                service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db');service.store.create('task',f'feedback-{index}','Pedido de teste')
                service.runtime.run=AsyncMock(return_value=result)
                with patch('core.assistant_service.settings',return_value=selected),patch('core.assistant_service.provider_key',return_value='fixture'),patch.object(audio_manager,'speak',return_value={'state':'completed'}) as speak:
                    await service.execute('task');await service.finish('task','completed','Duplicada')
                    speak.assert_called_once();self.assertTrue(service.store.get('task')['input']['final_feedback']['delivered'])
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db');service.store.create('task','tts-failure','Pedido de teste')
            service.runtime.run=AsyncMock(return_value={'response':'Resultado observado'})
            with patch('core.assistant_service.settings',return_value=selected),patch('core.assistant_service.provider_key',return_value='fixture'),patch.object(audio_manager,'speak',side_effect=RuntimeError('Output disconnected')):
                await service.execute('task')
            trace=service.store.get('task')['input'];self.assertFalse(trace['final_feedback']['delivered']);self.assertIn('Output disconnected',trace['speech_result']['error'])

    async def test_correction_supersedes_pending_task_without_stale_speech(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        from core.audio_manager import audio_manager
        from core.operational_context import context_for
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db');entered=asyncio.Event();release=asyncio.Event()
            async def run(request,*args,**kwargs):
                if request['id']=='old':
                    ctx=context_for('supersession-fixture');ctx.music_goal={**goal(),'task_id':'old'};entered.set();await release.wait();return {'response':'Confirmação antiga'}
                return {'response':'Pedido corrigido'}
            async def cancel(*args):release.set()
            service.local_runtime.run=run;service.local_runtime.cancel=cancel
            with patch('core.assistant_service.settings',return_value={'provider':'local-cpu','model':'qwen3:1.7b','speech_enabled':True}),patch.object(audio_manager,'speak',return_value={'state':'completed'}) as speak:
                old=await service.submit('Toque happy do Minecraft do Taus','supersession-fixture','old');old_runner=service.runners['old'];await entered.wait()
                new=await service.submit('É rap, não happy','supersession-fixture','new');new_runner=service.runners['new']
                await old_runner;await new_runner
                self.assertEqual(service.store.get('old')['state'],'cancelled');self.assertFalse(service.store.get('old')['input']['final_feedback']['delivered'])
                speak.assert_called_once();self.assertIn('Pedido corrigido',speak.call_args.args[0]);self.assertEqual(service.store.get('new')['input']['correction_context']['music_goal']['query'],goal()['query'])

    async def test_user_cancel_is_spoken_once(self):
        from core.assistant_service import AssistantService
        from core.task_store import TaskStore
        from core.audio_manager import audio_manager
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db');service.store.create('task','cancel-speech','Pedido de teste')
            service.cancelled.add('task')
            with patch('core.assistant_service.settings',return_value={'speech_enabled':True}),patch.object(audio_manager,'speak',return_value={'state':'completed'}) as speak:
                await service.execute('task');speak.assert_called_once();self.assertIn('cancelada',speak.call_args.args[0])
            self.assertEqual(service.store.get('task')['state'],'cancelled')
