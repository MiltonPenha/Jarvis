"""Controlled model decisions and page snapshots; real-site validation is separate."""
import copy
import unittest
from unittest.mock import Mock,patch,AsyncMock


def row(video,title,channel='Gravadora',position=1):
    return {'id':video,'video_id':video,'title':title,'channel':channel,'position':position,'url':'https://www.youtube.com/watch?v='+video,'area':'recommendations'}


def sample():
    return {'fingerprint':'stable','current':{'video_id':'current0001','title':'NX Zero - Razões e Emoções','channel':'Universal Music','artists':[],
        'volume':.13,'muted':False,'ad':False},'recommendations':[
            row('queen000001','Queen - Somebody To Love','Queen Official',1),
            row('nxzero00001','NX Zero - Cedo ou Tarde (Clipe Oficial)','Universal Music',2),
            row('nxzero00002','NX Zero - Além de Mim (Audio Oficial)','Outra gravadora',3)],
        'upcoming':[],'queue_source':'playlist'}


def decision(candidate,criterion='first_eligible',artist=0):
    return {'intent':{'first_eligible':'recommendation','same_artist':'same_artist','requested_artist':'artist'}[criterion],
        'criterion':criterion,'artist_id':artist,'candidate_id':candidate,'confidence':'clear'}


class SelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_song_explanations_and_behind_the_song_are_not_performances(self):
        from core.youtube_suggestions import choose,individual,local_model
        snap=sample();excluded=[row('explain0001','DI EXPLICA A MÚSICA: RAZÕES E EMOÇÕES','',1),row('behind00001','Cedo ou Tarde - NX Zero (Por Trás da Canção)','',2)]
        for item in excluded:self.assertFalse(individual(item,'current0001'))
        snap['recommendations']=excluded+snap['recommendations']
        with patch.object(local_model,'plan',AsyncMock(return_value=decision('nxzero00001','same_artist',1))):
            self.assertTrue((await choose('Outra deles',snap,{}))['accepted'])

    async def test_non_music_scene_is_skipped_before_the_first_observed_song(self):
        from core.youtube_suggestions import choose,local_model
        snap=sample();snap['recommendations'].insert(0,row('scene000001','Um Símbolo | Cena de um filme','',1))
        with patch.object(local_model,'plan',AsyncMock(return_value=decision('queen000001'))):
            result=await choose('Toque a primeira sugestão',snap,{})
            self.assertTrue(result['accepted']);self.assertEqual(result['candidate_id'],'queen000001')

    async def test_first_artist_collaboration_and_compact_spelling_are_eligible(self):
        from core.youtube_suggestions import choose,artist_match,local_model
        snap=sample();snap['recommendations'][0]=row('collab00001','NX Zero, Rick Bonadio - Cedo Ou Tarde','',1)
        self.assertTrue(artist_match(row('compact0001','NXZero - Pela última vez!',''),'NX Zero'))
        self.assertFalse(artist_match(row('wrong000001','Outro - Entrevista com NX Zero',''),'NX Zero'))
        with patch.object(local_model,'plan',AsyncMock(return_value=decision('collab00001','same_artist',1))):
            self.assertTrue((await choose('Outra deles',snap,{}))['accepted'])

    async def test_later_batch_is_examined_in_order_and_metrics_are_combined(self):
        from core.youtube_suggestions import choose,local_model
        snap=sample();snap['recommendations']=[row(f'queen{i:06d}','Queen - Song','Queen',i+1) for i in range(20)]+[snap['recommendations'][1]]
        replies=[{**decision('','same_artist',0),'confidence':'uncertain'},decision('nxzero00001','same_artist',1)]
        with patch.object(local_model,'plan',AsyncMock(side_effect=replies)) as infer:
            result=await choose('Outra deles',snap,{})
            self.assertTrue(result['accepted']);self.assertEqual(infer.await_count,2);self.assertEqual(len(result['batches']),2)

    async def test_missing_current_artist_asks_instead_of_inventing_and_recent_context_can_resolve(self):
        from core.youtube_suggestions import choose,local_model
        snap=sample();snap['current'].update(title='Razões e Emoções',channel='',artists=[])
        with patch.object(local_model,'plan',AsyncMock(return_value=decision('nxzero00001','same_artist',1))) as infer:
            self.assertEqual((await choose('Outra deles',snap,{}))['reason'],'artist_unknown');infer.assert_not_called()
            result=await choose('Outra deles',snap,{'media_query':'NX Zero'})
            self.assertTrue(result['accepted'],result)

    async def test_first_is_unrestricted_but_same_band_uses_title_on_label_channel(self):
        from core.youtube_suggestions import choose,local_model
        for request,expected,criterion,artist in [('Toque a primeira sugestão','queen000001','first_eligible',0),
            ('Outra deles','nxzero00001','same_artist',1),
            ('Toque a primeira sugestão da mesma banda','nxzero00001','same_artist',1),
            ('Coloque outra do NX Zero pelas sugestões','nxzero00001','requested_artist',1),
            ('Jarvis passa para a próxima reprodução da DENX Zero.','nxzero00001','requested_artist',1)]:
            with self.subTest(request=request),patch.object(local_model,'plan',AsyncMock(return_value=decision(expected,criterion,artist))) as infer:
                result=await choose(request,sample(),{'media_query':'Razões e Emoções do NX Zero'})
                self.assertTrue(result['accepted'],result);self.assertEqual(result['candidate_id'],expected)
                self.assertIn('recommendations',infer.call_args.args[0][1]);self.assertIn(request,infer.call_args.args[0][1])

    async def test_unknown_later_cover_and_unrelated_artist_cannot_be_selected(self):
        from core.youtube_suggestions import choose,local_model
        cases=[('invento0001','same_artist',1),('nxzero00002','same_artist',1),('queen000001','same_artist',1)]
        for video,criterion,artist in cases:
            with patch.object(local_model,'plan',AsyncMock(return_value=decision(video,criterion,artist))):
                self.assertFalse((await choose('Outra deles',sample(),{}))['accepted'])
        snap=sample();snap['recommendations'][1]['title']='Cover NX Zero - Cedo ou Tarde (Clipe Oficial)'
        with patch.object(local_model,'plan',AsyncMock(return_value=decision('nxzero00001','same_artist',1))):
            self.assertFalse((await choose('Outra deles',snap,{}))['accepted'])
        snap['recommendations']=snap['recommendations'][:1]
        with patch.object(local_model,'plan',AsyncMock(return_value=decision('queen000001','same_artist',1))):
            self.assertFalse((await choose('Outra deles',snap,{}))['accepted'])

    async def test_no_options_and_uncertainty_do_not_guess(self):
        from core.youtube_suggestions import choose,local_model
        snap=sample();snap['recommendations']=[]
        with patch.object(local_model,'plan',AsyncMock()) as infer:
            self.assertFalse((await choose('Outra deles',snap,{}))['accepted']);infer.assert_not_called()
        with patch.object(local_model,'plan',AsyncMock(return_value={**decision('nxzero00001','same_artist',1),'confidence':'uncertain'})):
            self.assertFalse((await choose('Outra deles',sample(),{}))['accepted'])


class RoutingAndTransitionTests(unittest.TestCase):
    def test_full_utterances_cannot_become_global_search_or_generic_queue_skip(self):
        from core.local_runtime import direct_plan,ground_plan,Plan
        from core.command_text import music_request
        phrases=('Toque a primeira sugestão','Siga a primeira recomendação','Toque a primeira sugestão da mesma banda',
            'Coloque outra do NX Zero pelas sugestões','Outra deles','Mais uma dessa banda','Próxima da mesma banda')
        for text in phrases:
            with self.subTest(text=text):
                plan=direct_plan(text);self.assertEqual(plan['steps'][0]['target'],'recommendation')
                self.assertIsNone(music_request(text))
                wrong=Plan.model_validate({'steps':[{'action':'play_music','target':'outra música'},{'action':'media','target':'next'}]})
                result=ground_plan(wrong,text)
                self.assertEqual(len(result.steps),1);self.assertEqual(result.steps[0].target,'recommendation')
        self.assertEqual(direct_plan('Próxima música')['steps'][0]['target'],'next')
        self.assertEqual(direct_plan('Outra música')['steps'][0]['target'],'next')
        self.assertEqual(direct_plan('Toque uma música do Queen')['steps'][0]['action'],'play_music')

    def transition(self,text,snapshots,selected=None):
        from core.youtube_suggestions import transition
        from core.media_control import MediaSession
        page=Mock();select=Mock(return_value={'accepted':True,'candidate_id':selected or 'queen000001','source':'recommendations','model_attempted':True})
        def confirm(page,chosen,*args,**kwargs):return {'verified':True,'playback_confirmed':True,'title':chosen['title'],'video_id':chosen['video_id']}
        with patch('core.youtube_suggestions.snapshot',side_effect=snapshots),patch('core.youtube_control._confirm_playback',side_effect=confirm):
            result=transition(page,MediaSession(),text,select,{},lambda:False,lambda event:None)
        return result,page,select

    def test_no_playlist_uses_actual_recommendations_and_explicit_overrides_playlist(self):
        snap=sample()
        result,page,select=self.transition('Próxima música',[snap,snap])
        self.assertTrue(result['playback_confirmed']);select.assert_called_once();self.assertEqual(result['previous_video_id'],'current0001')
        page.goto.assert_called_once_with(snap['recommendations'][0]['url'],wait_until='domcontentloaded')
        snap['upcoming']=[row('queue000001','Próxima da playlist')]
        result,page,select=self.transition('Próxima música',[snap,snap])
        select.assert_not_called();self.assertEqual(result['selection_source'],'playlist')
        result,page,select=self.transition('Toque a primeira sugestão',[snap,snap])
        self.assertEqual(result['selection_source'],'recommendations');select.assert_called_once()
        self.assertNotIn('/results',page.goto.call_args.args[0])

    def test_page_change_reextracts_once_before_one_navigation_and_persistent_change_stops(self):
        old=sample();old['fingerprint']='old';fresh=copy.deepcopy(old);fresh['fingerprint']='fresh'
        fresh['recommendations']=fresh['recommendations'][1:]
        result,page,select=self.transition('Outra deles',[old,fresh,fresh,fresh],'nxzero00001')
        self.assertTrue(result['verified']);self.assertEqual(select.call_count,2);page.goto.assert_called_once()
        different=copy.deepcopy(fresh);different['fingerprint']='third'
        result,page,select=self.transition('Outra deles',[old,fresh,fresh,different],'nxzero00001')
        self.assertFalse(result['verified']);page.goto.assert_not_called()

    def test_filter_excludes_ad_short_mix_navigation_current_and_non_music_mentions(self):
        from core.youtube_suggestions import individual
        good=row('nxzero00001','NX Zero - Cedo ou Tarde (Clipe Oficial)')
        self.assertTrue(individual(good,'current0001'))
        for changes in ({'ad':True},{'short':True},{'mix':True},{'url':'https://example.com/watch?v=nxzero00001'},
            {'video_id':'current0001'},{'title':'Entrevista NX Zero'},{'title':'Reaction NX Zero'},{'title':'NX Zero Cover'}):
            self.assertFalse(individual({**good,**changes},'current0001'))

    def test_model_abstention_never_starts_a_global_search(self):
        from core.youtube_suggestions import transition
        from core.media_control import MediaSession
        page=Mock()
        with patch('core.youtube_suggestions.snapshot',return_value=sample()):
            result=transition(page,MediaSession(),'Outra deles',lambda *args:{'accepted':False,'reason':'no_match'}, {},lambda:False,lambda event:None)
        self.assertFalse(result['verified']);self.assertIn('busque',result['message']);page.goto.assert_not_called()
