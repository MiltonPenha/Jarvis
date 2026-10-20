"""Volume semantics, live-state policy, model grounding and effect deduplication."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


class VolumeTests(unittest.TestCase):
    def test_requested_examples_retain_relationships_and_scope(self):
        from core.volume_intent import parse_volume
        cases={
            'JARVIS, diminua o volume para 10%':('absolute',10),
            'Jarvis, eu quero que você diminua o volume da música para 10%.':('absolute',10),
            'Jarvis diminu o volume da música para 10%.':('absolute',10),
            'De novo, volume para 10% Jarvis.':('absolute',10),
            'Coloque o volume em 10%':('absolute',10),'Diminua para 10%':('absolute',10),
            'Aumente para 10%':('absolute',10),'Deixe o som nos 20':('absolute',20),
            'Volume em cinquenta por cento':('absolute',50),'Coloque o volume pela metade':('absolute',50),
            'Volume mínimo':('absolute',1),'no mínimo, mas sem mutar':('absolute',1),
            'Volume máximo':('absolute',100),'volume zero':('absolute',0),
            'Aumente 10%':('relative',10),'diminua em 10%':('relative',-10),
            'Aumente um pouco':('relative',5),'Diminua um pouco':('relative',-5),
            'Aumente o volume':('relative',5),'Diminua o volume':('relative',-5),
            'Dobre o volume':('multiply',2),'aumente para o dobro do que está':('multiply',2),
            'Reduza à metade do que está':('multiply',.5),'Diminua pela metade':('multiply',.5),
            'Aumente em 50% do volume atual':('multiply',1.5),'reduza em 50% do volume atual':('multiply',.5),
            'Boa tarde, Jarvis. Coloque o áudio em quarenta e oito por cento.':('absolute',48),
            'Silencie o som':('mute',None),'Desmute o som':('unmute',None),
        }
        with patch.dict('os.environ',{'JARVIS_VOLUME_STEP':'5','JARVIS_MIN_AUDIBLE_VOLUME':'1'}):
            for text,expected in cases.items():
                with self.subTest(text=text):
                    intent=parse_volume(text)
                    self.assertIsNotNone(intent);self.assertFalse(intent.question)
                    self.assertEqual((intent.operation,intent.value),expected)
                    self.assertEqual(intent.scope,'player')
        for target in ('Windows','sistema','computador','PC'):
            self.assertEqual(parse_volume(f'Coloque o volume do {target} em vinte e cinco').scope,'system')

    def test_unknown_relationships_ask_without_inventing_an_operation(self):
        from core.volume_intent import parse_volume
        from core.local_runtime import direct_plan
        for text in ('Volume 10 ou 20','Ajuste o volume razoavelmente','Aumente em dez vinte por cento','Não diminua o volume','Volume do Windows ou do YouTube em 10%'):
            with self.subTest(text=text):
                intent=parse_volume(text);self.assertTrue(intent.question)
                plan=direct_plan(text);self.assertEqual(plan['steps'],[]);self.assertTrue(plan['question'])
        for text in ('10','Anote: volume em 10%','Toque uma música do NX Zero'):
            self.assertIsNone(parse_volume(text))

    def test_one_policy_computes_limits_rounding_and_explicit_silence(self):
        from core.volume_control import destination
        cases=[(48,'absolute',10,10),(48,'relative',10,58),(48,'relative',-10,38),
            (30,'multiply',2,60),(60,'multiply',.5,30),(40,'multiply',1.5,60),
            (49,'multiply',.5,25),(98,'relative',5,100),(100,'multiply',2,100),
            (2,'relative',-5,1),(2,'multiply',0,1),(70,'absolute',0,0),
            (70,'absolute',1000,100)]
        for current,mode,value,expected in cases:
            with self.subTest(current=current,mode=mode,value=value):
                target,muted=destination(mode,value,{'volume_percent':current,'muted':True})
                self.assertEqual(target,expected);self.assertEqual(muted,expected==0)
        self.assertEqual(destination('mute',None,{'volume_percent':40,'muted':False}),(40,True))
        self.assertEqual(destination('unmute',None,{'volume_percent':0,'muted':True}),(1,False))
        with patch.dict('os.environ',{'JARVIS_MIN_AUDIBLE_VOLUME':'3'}):
            self.assertEqual(destination('relative',-100,{'volume_percent':10,'muted':False}),(3,False))

    def test_real_state_is_reread_and_repeated_absolute_command_is_idempotent(self):
        from core.volume_control import adjust
        state={'volume_percent':48,'muted':True};writes=[]
        def read():return dict(state)
        def write(value,muted):writes.append((value,muted));state.update(volume_percent=value,muted=muted)
        first=adjust('absolute',10,read,write);again=adjust('absolute',10,read,write)
        self.assertEqual(writes,[(10,False)]);self.assertTrue(first['verified']);self.assertFalse(again['volume_change']['applied'])
        state['volume_percent']=40
        result=adjust('multiply',1.5,read,write)
        self.assertEqual(result['volume_percent'],60)
        self.assertEqual(result['volume_change']['before_percent'],40)
        failed=adjust('absolute',10,read,lambda *args:None,timeout=0)
        self.assertFalse(failed['verified']);self.assertNotIn('ajustado',failed['message'])
        def broken_write(*args):raise OSError('device unavailable')
        failed=adjust('absolute',10,read,broken_write)
        self.assertFalse(failed['verified']);self.assertIn('OSError',failed['error'])
        self.assertEqual(failed['volume_change']['destination_percent'],10)
        self.assertEqual(failed['volume_change']['observed_percent'],60)
        count=len(writes)
        with self.assertRaises(ValueError):adjust('relative',5,read,write,cancelled=lambda:True)
        self.assertEqual(len(writes),count)

    def test_model_cannot_change_absolute_target_or_duplicate_one_volume_request(self):
        from core.local_runtime import Plan,ground_plan,direct_plan
        from core.jarvis_tools import ToolService
        from core.task_store import TaskStore
        command='Jarvis, eu quero que você diminua o volume da música para 10%.'
        wrong={'action':'volume','mode':'relative','value':10,'scope':'system'}
        grounded=ground_plan(Plan.model_validate({'steps':[wrong]}),command)
        self.assertEqual((grounded.steps[0].mode,grounded.steps[0].value,grounded.steps[0].scope),('absolute',10,'player'))
        self.assertEqual(direct_plan(command)['steps'][0]['mode'],'absolute')
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('v','volume',command)
            tools=ToolService('v',store=store)
            result={'verified':True,'volume_change':{'operation':'absolute','before_percent':48,'destination_percent':10,'observed_percent':10}}
            with patch.object(tools,'_dispatch',return_value=result) as execute:
                tools.execute(wrong,invocation_id='first-event');cached=tools.execute(wrong,invocation_id='duplicate-event')
                execute.assert_called_once_with({'action':'volume','mode':'absolute','value':10,'scope':'player'})
            self.assertTrue(cached['replayed_checkpoint'])
            self.assertEqual(store.get('v')['input']['volume_change']['text_received'],command)

    def test_duplicate_relative_request_never_adds_twice_and_fraction_is_typed(self):
        from core.task_store import TaskStore
        from core.jarvis_tools import ToolService
        from core.tool_registry import validate
        validate({'action':'volume','mode':'multiply','value':.5})
        for value in (True,'0.5',float('nan'),float('inf')):
            with self.assertRaises(ValueError):validate({'action':'volume','mode':'multiply','value':value})
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('v','volume','Aumente em 10%')
            tools=ToolService('v',store=store)
            with patch.object(tools,'_dispatch',return_value={'verified':True}) as execute:
                tools.execute({'action':'volume','mode':'relative','value':10},invocation_id='one')
                tools.execute({'action':'volume','mode':'relative','value':10},invocation_id='two')
                self.assertEqual(execute.call_count,1)

    def test_playback_recovery_needs_confirmed_same_session_evidence(self):
        import json
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('play','session','Toque música')
            store.claim_tool('play','key','play_music')
            result={'verified':True,'url':'https://www.youtube.com/watch?v=known000001','video_id':'known000001'}
            store.finish_tool('play','key',result)
            self.assertEqual(store.last_playback('session')['video_id'],'known000001')
            self.assertIsNone(store.last_playback('other-session'))
            store.finish_tool('play','key',{**result,'verified':False})
            self.assertIsNone(store.last_playback('session'))


if __name__=='__main__':unittest.main()
