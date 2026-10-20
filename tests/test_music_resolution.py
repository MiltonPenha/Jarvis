"""Semantic choices must be grounded in observed music, not a substitution list."""
import unittest
from unittest.mock import patch,AsyncMock


class MusicResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_similar_observed_artist_can_be_selected_by_local_model(self):
        from core.music_resolution import resolve,local_model
        rows=[{'channel':"Guns N' Roses",'title':title} for title in ('Welcome To The Jungle','Paradise City','Patience')]
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':1,'confidence':'clear'})) as infer,patch.object(local_model,'last_metrics',{'vram_bytes':0,'input_tokens':180,'output_tokens':15}):
            result=await resolve('Gunner Rose',rows)
        self.assertTrue(result['accepted']);self.assertEqual(result['query'],"Guns N' Roses")
        self.assertEqual(result['model_usage']['vram_bytes'],0)
        self.assertEqual(infer.call_args.kwargs['max_tokens'],60)

    async def test_unrelated_names_and_unknown_candidate_ids_are_not_rewritten(self):
        from core.music_resolution import resolve,local_model
        rows=[{'channel':"Guns N' Roses",'title':'Paradise City'}]*3
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':1,'confidence':'clear'})) as infer:
            result=await resolve('Dancing Elephants',rows)
            self.assertFalse(result['accepted']);infer.assert_not_called()
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':999,'confidence':'clear'})):
            self.assertFalse((await resolve('Gunner Rose',rows))['accepted'])

    async def test_uncertainty_is_not_authority_to_start_a_different_artist(self):
        from core.music_resolution import resolve,local_model
        rows=[{'channel':'Linkin Park','title':'Numb'}]*3
        with patch.object(local_model,'plan',AsyncMock(return_value={'candidate_id':1,'confidence':'uncertain'})):
            self.assertFalse((await resolve('Lincoln Park',rows))['accepted'])
