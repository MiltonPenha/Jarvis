"""Scoring/provenance tests; these do not claim model or hardware accuracy."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch


class EvaluationTests(unittest.IsolatedAsyncioTestCase):
    def test_natural_infinitives_route_to_the_same_music_extractor(self):
        from core.music_intent import requested
        self.assertTrue(requested('Você consegue colocar uma música do Artista Exemplo?'))
        self.assertTrue(requested('Quero botar Faixa Nova para ouvir'))
        self.assertFalse(requested('Colocar volume em 47%'))

    def test_reextraction_choices_are_literal_grounded_and_preserve_unknown_names(self):
        from core.music_intent import literal_boundary_options
        request='Jarvis, toca música 42 de Banda Incomum'
        result=literal_boundary_options({'action':'search_and_play','service':'unspecified','content_spans':['música 42 de Banda Incomum']},request)
        self.assertIn('42 de Banda Incomum',result)
        self.assertTrue(all('42' in text and 'Banda Incomum' in text and 'música' not in text for text in result))
        protected='Toque a música “Música Para Mim”'
        self.assertIn('Música Para Mim',literal_boundary_options({'action':'search_and_play','service':'unspecified','content_spans':['Música Para Mim']},protected))

    def test_medley_requires_each_work_and_does_not_break_slashes_in_artist_names(self):
        from core.music_resolution import evidence
        row={'video_id':'evalsong001','title':'Example Artist - First Song / Second Tune (Live)','channel':'Example Artist'}
        self.assertEqual(evidence('First Song Example Artist',row,{'title':'First Song','artist':'Example Artist'})['reason'],'combined_work_not_requested')
        self.assertTrue(evidence('First Song Second Tune Example Artist',row,{'title':'First Song Second Tune','artist':'Example Artist'})['eligible'])
        single={**row,'title':'AC/DC - Thunderstruck','channel':'AC/DC'}
        self.assertTrue(evidence('Thunderstruck AC/DC',single,{'title':'Thunderstruck','artist':'AC/DC'})['eligible'])

    def test_corpus_is_frozen_and_has_disjoint_works_and_artists(self):
        from core.music_evaluation import load_suite,runtime_snapshot
        suite=load_suite();self.assertEqual(len(suite['development']['cases']),14);self.assertEqual(len(suite['holdout']['cases']),12)
        self.assertIsInstance(runtime_snapshot()['model_manifests'],dict)
        self.assertEqual(sum(c.get('record',False) for group in suite.values() for c in group['cases']),6)

    def test_query_scorer_does_not_hide_instruction_residue_or_replace_names(self):
        from core.music_evaluation import query_matches
        self.assertTrue(query_matches('Razões e Emoções do NX Zero',['Razões e Emoções NX Zero']))
        self.assertFalse(query_matches('pra mim a música TAUZ MADARA',['TAUZ MADARA']))
        self.assertFalse(query_matches('TAUS MADARA',['TAUZ MADARA']))
        self.assertFalse(query_matches('Jungkook',['7 Jungkook']))
        self.assertTrue(query_matches('“Pra Mim”',['Pra Mim']))
        self.assertFalse(query_matches('Mim',['Pra Mim']))

    def test_wer_can_exceed_one_and_content_recall_is_separate(self):
        from core.music_evaluation import recognition_metrics
        metrics=recognition_metrics('toque Happy','toque Happy agora mais tarde',['Happy'])
        self.assertEqual(metrics['wer'],1.5);self.assertEqual(metrics['content_token_recall'],1.)
        metrics=recognition_metrics('toque TAUZ MADARA','toque TAUS MADARA',['TAUZ MADARA'])
        self.assertAlmostEqual(metrics['wer'],1/3);self.assertEqual(metrics['content_token_recall'],.5)

    def test_missing_coverage_is_not_a_pass_and_simulation_is_not_hardware(self):
        from core.music_evaluation import summarize
        rows=[{'split':'dev','stage':'feedback','environment':'simulated_audio_output','status':'passed'},
            {'split':'dev','stage':'feedback','environment':'real_audio_output','status':'blocked'}]
        result=summarize(rows);self.assertEqual(len(result),2)
        self.assertEqual(result[1]['coverage'],0);self.assertIsNone(result[1]['pass_rate'])

    def test_comparison_refuses_changed_labels_or_model(self):
        from core.music_evaluation import compare_reports
        report={'snapshot':{'dataset_hashes':{'dev':'hash'},'model':'qwen3:1.7b','model_manifests':{'m':'weights'},'code_hashes':{'runtime':'old'}},'results':[]}
        after=copy.deepcopy(report);after['snapshot']['code_hashes']['runtime']='new'
        self.assertEqual(compare_reports(report,after)['changed_sources'],['runtime'])
        after['snapshot']['dataset_hashes']['dev']='other'
        with self.assertRaisesRegex(ValueError,'corpus mudou'):compare_reports(report,after)
        after=copy.deepcopy(report);after['snapshot']['model_manifests']['m']='other'
        with self.assertRaisesRegex(ValueError,'modelo mudou'):compare_reports(report,after)
        after=copy.deepcopy(report);after['results']=[{'split':'dev','stage':'intent','environment':'text','id':'extra','status':'passed'}]
        with self.assertRaisesRegex(ValueError,'mesmos casos'):compare_reports(report,after)

    def test_report_replace_retries_transient_windows_file_locks(self):
        from core.music_evaluation import write_report
        original=Path.replace;calls=[]
        def replace(path,target):
            calls.append(path)
            if len(calls)<3:raise PermissionError('controlled indexer lock')
            return original(path,target)
        with tempfile.TemporaryDirectory() as folder:
            destination=Path(folder)/'report.json'
            with patch.object(Path,'replace',replace),patch('core.music_evaluation.time.sleep'):
                write_report({'results':[]},destination)
            self.assertEqual(json.loads(destination.read_text())['summary'],[])
            self.assertFalse(list(Path(folder).glob('*.tmp')))
        self.assertEqual(len(calls),3)

    async def test_unconfirmed_reference_does_not_become_a_scored_recording(self):
        from core.music_evaluation import evaluate_offline,load_suite
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);manifest=path/'manifest.json';manifest.write_text(json.dumps({'recordings':[{
                'id':'one','case_id':'dev-queen','source':'human','reference_status':'unverified'}]}),encoding='utf-8')
            report={'results':[]}
            with patch('core.audio_manager.AudioManager.transcribe_audio') as stt:
                await evaluate_offline(report,path/'report.json',load_suite(),['development'],['stt'],manifest)
            stt.assert_not_called();self.assertEqual(report['results'][0]['status'],'blocked')

    def test_controlled_execution_has_one_search_and_never_claims_wrong_video_as_success(self):
        from core.music_evaluation import execution_probe
        for scenario in ('playing','navigation_failure','player_failure','wrong_video','advertisement'):
            result=execution_probe(scenario);self.assertTrue(result['passed'],result);self.assertEqual(result['search_count'],1)
            self.assertTrue(result['player_is_mocked']);self.assertEqual(result['verified'],scenario=='playing')

    async def test_feedback_contract_marks_simulation_and_reports_failed_output(self):
        from core.music_evaluation import feedback_probe
        for scenario in ('success','failure','clarification','output_failure'):
            result=await feedback_probe(scenario);self.assertTrue(result['passed'],result)
            self.assertTrue(result['speech_is_mocked']);self.assertFalse(result['voice_quality_evaluated'])


if __name__=='__main__':unittest.main()
