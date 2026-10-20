"""Contract, admission and operational-context regressions.

Browser fixtures use real Chrome/HTML audio with intercepted local test content;
model responses in these unit tests are simulated. Live validation is separate.
"""
import asyncio
import base64
import io
import wave
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch,AsyncMock,Mock
from core.tool_registry import TOOLS,validate,register
from core.intents import media_intent
from core.operational_context import OperationalContext
from core.task_store import TaskStore
from core.jarvis_tools import ToolService
from core.local_runtime import LocalRuntime,direct_plan
from core.config import config


class IntentTests(unittest.TestCase):
    def test_greeting_and_address_do_not_disable_generic_composition(self):
        for greeting in ('Boa noite, Javis.','Boa tarde, Jarvis,','Olá, Jarvis!','Jarvis, boa noite.'):
            for artist in ('Guns and Rolls','Queen','Daft Punk'):
                command=f'{greeting} Abra o Google, entre no YouTube, toque uma música do {artist}.'
                plan=direct_plan(command)
                self.assertIsNotNone(plan,command)
                self.assertEqual([r['action'] for r in plan['steps']],['browser_open','browser_open','play_music'])
                self.assertEqual(plan['steps'][-1]['target'],artist)
        self.assertEqual(direct_plan('Boa noite, Javis.')['steps'],[])
        note=direct_plan('Anote que boa noite, Javis. Abra o Google')
        self.assertEqual(note['steps'][0]['content'],'boa noite, Javis. Abra o Google')

    def test_parameters_and_language_variations(self):
        cases={
            'Aumente um pouco o som.':('volume','relative','player',5),
            'Diminua para 30%.':('volume','absolute','player',30),
            'Abaixe o volume em 15 por cento':('volume','relative','player',-15),
            'Coloque o volume do sistema em 25%':('volume','absolute','system',25),
            'Qual o volume do sistema?':('volume','status','system',None),
            'Pause a música':('media','pause','player',None),
            'Pode pausar a música por favor?':('media','pause','player',None),
            'Continue.':('media','resume','player',None),
            'Passe para a próxima':('media','next','player',None),
            'Volte para a faixa anterior':('media','previous','player',None),
            'Qual música está tocando?':('media','status','player',None),
        }
        for command,expected in cases.items():
            with self.subTest(command=command):
                intent=media_intent(command)
                self.assertIsNotNone(intent)
                self.assertEqual((intent.action,intent.operation,intent.scope,intent.value),expected)
        with patch.dict('os.environ',{'JARVIS_VOLUME_STEP':'7'}):
            self.assertEqual(media_intent('Aumente um pouco o som').value,7)

    def test_uncertain_language_and_compounds_are_not_shortcuts(self):
        for command in ('Não pause a música','Se chover pause a música','Pause e depois abra o Google',
            'Pause o alarme','Continue o projeto','Aumente o volume da televisão'):
            self.assertIsNone(media_intent(command),command)
        self.assertEqual([row['action'] for row in direct_plan('Abra o Google, entre no YouTube e toque uma música do Queen')['steps']],['browser_open','browser_open','play_music'])
        self.assertEqual([r['action'] for r in direct_plan('Toque uma música do Queen no YouTube')['steps']],['play_music'])


class ContractTests(unittest.TestCase):
    def test_url_selection_requires_literal_address_in_the_users_request(self):
        url='https://www.youtube.com/watch?v=XdglM81b4g8'
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('select','select-session','Liste as abas')
            service=ToolService('select',store=store)
            with patch.object(service,'_dispatch') as execute:
                result=service.execute({'action':'browser_select','query':url})
                self.assertFalse(result['verified']);self.assertIn('endereço explícito',result['error']);execute.assert_not_called()

    def test_planner_grammar_keeps_each_tool_enum_and_required_arguments(self):
        from core.local_runtime import planner_schema
        schema=planner_schema()
        media=schema['$defs']['call_media']
        self.assertEqual(media['properties']['action']['enum'],['media'])
        self.assertEqual(media['properties']['arguments']['properties']['check']['enum'],
            ['pause','resume','stop','next','previous','status','recommendation','suggestions','confirm_music','reject_music'])
        self.assertEqual(media['properties']['arguments']['required'],['check'])
        self.assertFalse(media['properties']['arguments']['additionalProperties'])

    def test_measured_token_cap_interrupts_official_agent(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from core.hermes_worker import enforce_token_budget
        agent=SimpleNamespace(session_input_tokens=100,session_output_tokens=20,interrupt=Mock())
        self.assertTrue(enforce_token_budget(agent,121));agent.interrupt.assert_not_called()
        self.assertFalse(enforce_token_budget(agent,120));agent.interrupt.assert_called_once_with(hard_cancel=True)

    def test_unknown_tool_wrong_type_and_cross_tool_fields_rejected(self):
        for args in ({'action':'shell','query':'anything'}, {'action':'volume','mode':'relative','value':'10'},
            {'action':'volume','mode':'absolute','value':True},{'action':'media','check':'play_pause'},
            {'action':'play_music','query':'Queen','path':'C:/Windows'}, {'action':'browser_fill','query':'1'}):
            with self.subTest(args=args),self.assertRaises(ValueError):validate(args)

    def test_duplicate_next_is_not_replayed_but_explicit_steps_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('t','s','test')
            tools=ToolService('t',store=store)
            args={'action':'media','check':'next'}
            with patch.object(tools,'_dispatch',return_value={'verified':True,'message':'Next observed'}) as effect:
                self.assertTrue(tools.execute(args,invocation_id='step:0')['verified'])
                self.assertTrue(tools.execute(args,invocation_id='step:0')['replayed_checkpoint'])
                tools.execute(args,invocation_id='step:1')
                self.assertEqual(effect.call_count,2)
            # An uncertain next is blocked, not retried with the same identifier.
            store.claim_tool('t','uncertain','media')
            with self.assertRaises(RuntimeError):store.claim_tool('t','uncertain','media')

    def test_budget_and_cancel_precede_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('t','limits','test')
            tools=ToolService('t',store=store);tools.deadline=time.monotonic()-1
            with patch.object(tools,'_dispatch') as effect:
                self.assertIn('error',tools.execute({'action':'media','check':'next'}));effect.assert_not_called()
            tools=ToolService('t',store=store,cancelled=lambda:True)
            with patch.object(tools,'_dispatch') as effect:
                self.assertIn('error',tools.execute({'action':'media','check':'next'}));effect.assert_not_called()


class PlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_reported_transcription_uses_music_extraction_without_general_planning(self):
        command='Boa noite, Javis. Abra o Google, entre no YouTube, toque uma música do Guns and Rolls.'
        results=[{'verified':True,'message':'Google observado'}, {'verified':True,'message':'YouTube observado'},
            {'verified':True,'playback_confirmed':True,'message':'Reprodução observada'}]
        result,count,executed=await self.run_with(command,None,results)
        self.assertEqual(count,0)
        self.assertEqual([call.args[0]['action'] for call in executed],['browser_open','browser_open','play_music'])
        self.assertEqual(executed[-1].args[0]['query'],'Guns and Rolls')
        self.assertEqual(result['usage']['local_model_calls'],1)

    async def run_with(self,command,plan,dispatch):
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('t','planner-fixture',command)
            engine=LocalRuntime(store)
            with patch('core.local_runtime.local_model.plan',AsyncMock(return_value=plan)) as model, \
                patch('core.music_intent.interpret',AsyncMock(return_value={'accepted':True,'query':'Guns and Rolls' if 'Guns and Rolls' in command else 'Queen','original_transcription':command,'model_attempted':True,'model_usage':{'input_tokens':100,'output_tokens':30,'vram_bytes':0}})), \
                patch.object(ToolService,'_dispatch',side_effect=dispatch) as execute:
                result=await engine.run({'id':'t','command':command},AsyncMock())
                return result,model.call_count,execute.call_args_list

    async def test_simple_controls_do_not_call_model(self):
        result,calls,executed=await self.run_with('Pause a música',None,[{'verified':True,'message':'Pausa observada'}])
        self.assertEqual(calls,0);self.assertEqual(result['usage']['api_calls'],0)
        self.assertEqual(executed[0].args[0],{'action':'media','check':'pause'})

    async def test_novel_composition_and_whole_plan_validation(self):
        command='Visite o endereço https://example.com; em seguida mostre o texto da página'
        plan={'steps':[{'action':'browser_open','arguments':{'query':'https://example.com'}},
            {'action':'browser_read','arguments':{}}],'question':''}
        result,calls,executed=await self.run_with(command,plan,[{'verified':True,'message':'Aberto'}, {'verified':True,'message':'Conteúdo observado'}])
        self.assertEqual(calls,1);self.assertEqual(len(executed),2);self.assertIn('Conteúdo observado',result['response'])
        bad={'steps':plan['steps']+[{'action':'shell'}],'question':''}
        with self.assertRaisesRegex(ValueError,'não autorizada'):
            await self.run_with(command,bad,[])

    async def test_observation_failure_stops_following_steps(self):
        plan={'steps':[{'action':'browser_open','target':'google'},{'action':'browser_open','target':'youtube'},
            {'action':'play_music','target':'Queen'}],'question':''}
        result,calls,executed=await self.run_with('Abra o Google, entre no YouTube e toque Queen',plan,
            [{'verified':False,'needs_manual_verification':True,'message':'Verificação humana'}])
        self.assertEqual(len(executed),1);self.assertIn('interrompi',result['response'])
        self.assertIn('Verificação humana',result['error'])

    async def test_resume_uses_admitted_plan_and_does_not_skip_two_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(Path(folder)/'tasks.db');store.create('t','resume-fixture','uma sequência nova')
            plan={'steps':[{'action':'media','target':'next'},{'action':'media','target':'status'}],'question':''}
            # Admit a plan and execute the first effect, as if interruption then
            # occurred before its second step. A resumed model must not replan.
            from core.local_runtime import Plan,ground_plan
            canonical=ground_plan(Plan.model_validate(plan),'uma sequência nova').model_dump()
            store.save_plan('t',canonical)
            tools=ToolService('t',store=store)
            with patch.object(tools,'_dispatch',return_value={'verified':True,'message':'Próxima confirmada'}):
                tools.execute({'action':'media','check':'next'},invocation_id='step:0')
            engine=LocalRuntime(store)
            with patch('core.local_runtime.local_model.plan',AsyncMock()) as model, \
                patch.object(ToolService,'_dispatch',return_value={'verified':True,'message':'Estado observado'}) as effect:
                result=await engine.run({'id':'t','command':'uma sequência nova'},AsyncMock())
                model.assert_not_called();self.assertEqual(effect.call_count,1)
                self.assertEqual(effect.call_args.args[0]['check'],'status')
                self.assertIn('Próxima confirmada',result['response'])

    async def test_direct_controls_work_with_cloud_selected_and_no_key(self):
        from core.assistant_service import AssistantService
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            service.local_runtime=LocalRuntime(service.store)
            selected={'provider':'gemini','model':'','speech_enabled':False}
            with patch('core.assistant_service.settings',return_value=selected),patch('core.assistant_service.provider_key',return_value=''), \
                patch.object(config,'MAX_DAILY_TASKS',0),patch.object(config,'MAX_DAILY_TOKENS',0), \
                patch.object(ToolService,'_dispatch',return_value={'verified':True,'message':'Pausa observada'}), \
                patch.object(service.runtime,'run',AsyncMock()) as cloud:
                await service.submit('Pause a música','cloud-direct','t');await service.runners['t']
                self.assertEqual(service.store.get('t')['state'],'completed');cloud.assert_not_called()

    async def test_token_budget_does_not_start_configured_fallback(self):
        from core.assistant_service import AssistantService
        with tempfile.TemporaryDirectory() as folder:
            service=AssistantService(AsyncMock());service.store=TaskStore(Path(folder)/'tasks.db')
            service.store.create('t','budget-fixture','Um pedido novo que exige o provedor')
            selected={'provider':'gemini','model':'fixture','speech_enabled':False,
                'fallback_provider':'openai-api','fallback_model':'fixture-fallback'}
            with patch('core.assistant_service.settings',return_value=selected),patch('core.assistant_service.provider_key',return_value='fixture'), \
                patch.object(service.runtime,'run',AsyncMock(return_value={'error':'Orçamento atingido','budget_exhausted':True,'usage':{'input_tokens':24000}})) as cloud:
                await service.execute('t')
                self.assertEqual(cloud.call_count,1);self.assertEqual(service.store.get('t')['state'],'failed')


class BrowserContextTests(unittest.TestCase):
    def test_search_reader_observes_classic_and_modern_cards_after_partial_loading(self):
        from core.youtube_control import _read_results
        def check():
            page=self.browser.page
            self.browser.context.unroute('**/*')
            body='''<style>ytd-video-renderer, yt-lockup-view-model {display:block}</style>
                <ytd-search><ytd-video-renderer><a id="video-title" title="Artist - Wrong" href="https://other.example/watch?v=wrong000001">Wrong</a><div id="channel-name"><a>Wrong Channel</a></div></ytd-video-renderer>
                <ytd-video-renderer id="partial"><a id="video-title" title="Artist - First" href="/watch?v=first000001&amp;list=RDfirst000001">First</a><div id="channel-name"><a></a></div></ytd-video-renderer>
                <yt-lockup-view-model><h3><a href="/watch?v=first000001&amp;list=RDfirst000001">Mix de Artist - First</a></h3></yt-lockup-view-model></ytd-search>
                <script>setTimeout(()=>{
                document.querySelector('#partial #channel-name a').textContent='Artist';
                document.querySelector('ytd-search').insertAdjacentHTML('beforeend',`<yt-lockup-view-model><h3><a href="/watch?v=later000001">Artist - Later (Official)</a></h3><a href="/@artist">Artist</a></yt-lockup-view-model>`);
                document.querySelector('ytd-video-renderer').remove();
                },400)</script>'''
            self.browser.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=body))
            page.goto('https://www.youtube.com/results?search_query=Artist')
            rows,snapshots=_read_results(page,'Artist',lambda:False,set())
            self.assertEqual({r['video_id'] for r in rows},{'first000001','later000001'})
            self.assertTrue(any(r.get('missing') for r in snapshots));self.assertEqual(snapshots[-1]['missing'],0)
            self.assertGreaterEqual(snapshots[-1]['non_video'],1)
            self.assertTrue(all(r['channel']=='Artist' and 'youtube.com/watch?' in r['url'] for r in rows))
            self.assertEqual(next(r['title'] for r in rows if r['video_id']=='later000001'),'Artist - Later (Official)')
        self.browser.executor.submit(check).result(15)

    def setUp(self):
        from core.browser_control import BrowserControl
        self.folder=tempfile.TemporaryDirectory(prefix='jarvis-media-contract-')
        self.browser=BrowserControl(Path(self.folder.name),headless=True,mute_audio=True)
        self.context=OperationalContext('browser-fixture')
        self.dns=patch('core.browser_control.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]);self.dns.start()
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\0\0'*8000*30)
        self.source='data:audio/wav;base64,'+base64.b64encode(buffer.getvalue()).decode()
        def prepare():
            self.browser._start()
            self.browser.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',
                body='<title>Player fixture</title><audio autoplay muted src="'+self.source+'"></audio><p>Pronto</p><a href="https://example.com/second">Contato</a><input type="search" aria-label="Pesquisar">'))
        self.browser.executor.submit(prepare).result(15)
        self.call('browser_open',query='https://example.com/first')

    def tearDown(self):
        self.browser.close();self.browser.executor.shutdown(wait=True);self.dns.stop();self.folder.cleanup()

    def call(self,action,**kwargs):
        args=validate({'action':action,**kwargs})
        return self.browser.tool(args,self.context)

    def test_pause_resume_volume_clamp_and_system_separation(self):
        self.assertTrue(self.call('media',check='pause')['state']['paused'])
        self.assertTrue(self.call('media',check='pause')['state']['paused'])
        self.assertFalse(self.call('media',check='resume')['state']['paused'])
        self.assertEqual(self.call('volume',mode='absolute',value=30)['volume_percent'],30)
        self.assertEqual(self.call('volume',mode='relative',value=100)['volume_percent'],100)
        self.assertEqual(self.call('volume',mode='relative',value=-200)['volume_percent'],1)
        self.assertTrue(self.call('volume',mode='mute')['state']['muted'])
        self.assertFalse(self.call('volume',mode='unmute')['state']['muted'])
        with patch('core.system_audio.endpoint_volume',return_value={'verified':True,'scope':'system'}) as system:
            from core.media_control import volume_tool
            volume_tool({'mode':'absolute','value':20,'scope':'system'},lambda:False,self.context)
            self.assertEqual(system.call_args.args,('absolute',20))
            self.assertTrue(callable(system.call_args.kwargs['cancelled']))

    def test_multiple_players_stale_binding_and_external_change(self):
        first=self.context.tab_id
        def extra():
            page=self.browser.context.new_page();page.goto('https://example.com/other')
        self.browser.executor.submit(extra).result(10)
        with self.assertRaisesRegex(ValueError,'Selecione'):self.call('media',check='pause')
        self.call('browser_select',query=first)
        self.assertTrue(self.call('media',check='pause')['verified'])
        self.browser.executor.submit(lambda:self.browser.page.evaluate("document.querySelector('audio').src+='changed'" )).result(5)
        with self.assertRaisesRegex(ValueError,'mudou'):self.call('media',check='pause')
        self.browser.executor.submit(lambda:self.browser.page.close()).result(5)
        with self.assertRaisesRegex(ValueError,'fechada'):self.call('media',check='next')
        with self.assertRaisesRegex(ValueError,'inválido'):self.call('media',check='pause')

    def test_volume_absolute_relative_ratio_and_mute_share_verified_policy(self):
        from core.media_control import preferences
        self.call('volume',mode='absolute',value=48)
        with patch('core.media_control.preferences',wraps=preferences) as write,patch('core.system_audio.endpoint_volume') as system:
            first=self.call('volume',mode='absolute',value=10)
            repeated=self.call('volume',mode='absolute',value=10)
            self.assertEqual(first['volume_percent'],10);self.assertEqual(repeated['volume_percent'],10)
            self.assertEqual(write.call_count,1);system.assert_not_called()
        self.assertEqual(self.call('volume',mode='relative',value=10)['volume_percent'],20)
        self.assertEqual(self.call('volume',mode='multiply',value=.5)['volume_percent'],10)
        self.assertEqual(self.call('volume',mode='multiply',value=0)['volume_percent'],1)
        self.assertTrue(self.call('volume',mode='mute')['muted'])
        self.assertFalse(self.call('volume',mode='absolute',value=10)['muted'])
        self.assertEqual(self.call('volume',mode='absolute',value=0)['volume_percent'],0)
        self.assertTrue(self.call('volume',mode='absolute',value=0)['muted'])

    def test_exact_voice_text_executes_absolute_twice_through_runtime_on_real_player(self):
        self.call('volume',mode='absolute',value=48)
        store=TaskStore(Path(self.folder.name)/'volume-runtime.db');engine=LocalRuntime(store)
        async def check():
            with patch('core.browser_control.browser_control',self.browser):
                for index,text in enumerate(('JARVIS, diminua o volume para 10%',
                    'JARVIS, diminua o volume para 10%')):
                    task='volume-'+str(index);store.create(task,'volume-'+Path(self.folder.name).name,text)
                    result=await engine.run({'id':task,'session':store.get(task)['session'],'command':text},AsyncMock())
                    self.assertFalse(result.get('error'));self.assertEqual(result['usage']['local_model_calls'],0)
                    observed=json.loads(store.get(task)['tools'][0]['result'])
                    self.assertEqual(observed['volume_percent'],10)
                    self.assertEqual(observed['volume_change']['operation'],'absolute')
                    self.assertEqual(observed['volume_change']['before_percent'],48 if index==0 else 10)
                    self.assertEqual(observed['volume_change']['text_received'],text)
                    self.assertEqual(len(store.get(task)['tools']),1)
        asyncio.run(check())

    def test_youtube_unmute_restoration_cannot_override_minimum_destination(self):
        # Simulate YouTube's unMute restoring 5% before setVolume, using real JS.
        def prepare():
            self.browser.page.evaluate('''() => {
                const audio=document.querySelector('audio'),video=document.createElement('video');
                video.src=audio.src;video.muted=true;
                const p=document.createElement('div');p.id='movie_player';audio.replaceWith(p);p.append(video);
                p.getVolume=()=>video.volume*100;p.isMuted=()=>video.muted;
                p.setVolume=value=>{video.volume=value/100};
                p.unMute=()=>{video.muted=false;video.volume=Math.max(.05,video.volume)};
                p.mute=()=>{video.muted=true};
            }''')
        self.browser.executor.submit(prepare).result(5)
        result=self.call('volume',mode='absolute',value=1)
        self.assertTrue(result['verified']);self.assertEqual(result['volume_percent'],1);self.assertFalse(result['muted'])

    def test_tabs_observable_wait_fill_and_reference_scope(self):
        self.assertEqual(len(self.call('browser_tabs')['tabs']),1)
        self.assertTrue(self.call('browser_wait',condition='text',query='Pronto')['verified'])
        self.assertTrue(self.call('browser_fill',query='Pesquisar',content='astronomia')['verified'])
        first=self.context.tab_id
        self.browser.executor.submit(lambda:self.browser.context.new_page().goto('https://example.com/first')).result(10)
        rows=self.call('browser_tabs')['tabs'];other=next(row['id'] for row in rows if row['id']!=first)
        self.call('browser_select',query=other)
        self.browser.executor.submit(lambda:setattr(self.browser,'page',self.browser.tabs[first])).result(5)
        with self.assertRaisesRegex(ValueError,'mudou'):
            self.browser.executor.submit(self.browser._find,'1').result(5)

    def test_stale_reference_remaps_semantics_after_dom_reorder(self):
        snapshot=self.call('browser_state')
        reference=next(row['id'] for row in snapshot['elements'] if row['label']=='Pesquisar')
        def reorder():
            self.browser.page.evaluate("document.querySelector('body').prepend(document.createElement('input'));document.querySelector('input').setAttribute('aria-label','Outro')")
            self.browser._snapshot()
        self.browser.executor.submit(reorder).result(5)
        self.assertTrue(self.call('browser_fill',query=reference,content='teste')['verified'])
        value=self.browser.executor.submit(lambda:self.browser.page.locator('[aria-label="Pesquisar"]').input_value()).result(5)
        self.assertEqual(value,'teste')

    def test_hidden_and_equivalent_duplicate_elements_are_narrowed(self):
        def duplicate():
            self.browser.page.evaluate("document.body.insertAdjacentHTML('afterbegin','<input style=\"display:none\" aria-label=\"Pesquisar\"><a href=\"https://example.com/second\">Contato</a>')")
        self.browser.executor.submit(duplicate).result(5)
        self.assertTrue(self.call('browser_fill',query='Pesquisar',content='visível')['verified'])
        self.assertTrue(self.call('browser_click',query='Contato')['verified'])

    def test_youtube_login_is_site_state_not_chrome_sync(self):
        from core.youtube_control import authentication_state,play_youtube
        def check():
            self.browser.page.set_content('<ytd-masthead><a href="https://accounts.google.com/ServiceLogin">Fazer login</a></ytd-masthead>')
            self.browser.page.goto('https://www.youtube.com/')
            self.browser.page.set_content('<ytd-masthead><a href="https://accounts.google.com/ServiceLogin">Fazer login</a></ytd-masthead>')
            result=play_youtube(self.browser.page,'Queen',require_login=True)
            self.assertFalse(result['verified']);self.assertEqual(result['stage'],'login_required')
            self.assertFalse(result['playback_confirmed']);self.assertNotIn('/results',self.browser.page.url)
            self.browser.page.set_content('<ytd-masthead><button id="avatar-btn">Conta</button></ytd-masthead>')
            self.assertTrue(authentication_state(self.browser.page)['authenticated'])
            self.browser.page.set_content('<ytd-masthead></ytd-masthead><script>window.ytcfg={get:key=>key===\"LOGGED_IN\"?true:undefined}</script>')
            self.assertEqual(authentication_state(self.browser.page)['evidence'],'site_session_flag')
        self.browser.executor.submit(check).result(15)

    def prepare_suggestions_fixture(self,playlist=False):
        import html
        from urllib.parse import parse_qs,urlparse
        tracks={'cur00000001':'NX Zero - Razões e Emoções','rec00000001':'Queen - Somebody To Love',
            'rec00000002':'NX Zero - Cedo ou Tarde (Clipe Oficial)','playlist001':'Outra banda - Música da fila'}
        def prepare():
            def card(video,title,channel='Universal Music',kind='ytd-compact-video-renderer',extra=''):
                return f'<{kind} {extra}><a id="video-title" title="{html.escape(title)}" href="/watch?v={video}">{html.escape(title)}</a><div id="channel-name"><a>{channel}</a></div></{kind}>'
            def serve(route):
                video=parse_qs(urlparse(route.request.url).query).get('v',['cur00000001'])[0]
                recs=card('rec00000001',tracks['rec00000001'],'Queen')+card('rec00000002',tracks['rec00000002'],kind='yt-lockup-view-model')
                recs+='<ytd-ad-slot-renderer>'+card('advert00001','NX Zero - Ad')+'</ytd-ad-slot-renderer>'
                recs+=card('cur00000001','NX Zero - Atual')+card('cover000001','NX Zero Cover')
                recs+='<yt-lockup-view-model><a href="/watch?v=radio000001&amp;list=RDradio000001&amp;start_radio=1"><h3>NX Zero - Só Rezo</h3></a><div class="yt-content-metadata-view-model-wiz__metadata-row">NXZeroVEVO</div></yt-lockup-view-model>'
                recs+='<yt-lockup-view-model><a href="/watch?v=mixes000001&amp;list=RDmixes000001"><h3>Mix de NX Zero</h3></a></yt-lockup-view-model>'
                queue='<ytd-playlist-panel-renderer>'+card('cur00000001',tracks['cur00000001'],kind='ytd-playlist-panel-video-renderer',extra='selected')+card('playlist001',tracks['playlist001'],kind='ytd-playlist-panel-video-renderer')+'</ytd-playlist-panel-renderer>' if playlist else ''
                body='<style>ytd-compact-video-renderer,yt-lockup-view-model,ytd-playlist-panel-renderer,ytd-playlist-panel-video-renderer{display:block}</style>'
                body+='<title>'+tracks.get(video,'Fixture')+'</title><div id="movie_player"><video autoplay muted src="'+self.source+'"></video></div>'
                body+='<script>document.querySelector("#movie_player").getVideoData=()=>('+json.dumps({'video_id':video,'title':tracks.get(video,'Fixture'),'author':'Universal Music'})+')</script>'
                body+='<ytd-watch-flexy><div id="secondary"><div id="related">'+recs+'</div>'+queue+'</div></ytd-watch-flexy>'
                route.fulfill(status=200,content_type='text/html',body=body)
            self.browser.context.unroute('**/*');self.browser.context.route('**/*',serve)
            self.browser.page.goto('https://www.youtube.com/watch?v=cur00000001')
        self.browser.executor.submit(prepare).result(10)

    def test_suggestion_snapshot_separates_playlist_and_filters_ads_current_and_cover(self):
        from core.youtube_suggestions import snapshot
        self.prepare_suggestions_fixture(playlist=True)
        state=self.browser.executor.submit(snapshot,self.browser.page).result(5)
        self.assertEqual([r['id'] for r in state['recommendations']],['rec00000001','rec00000002','radio000001'])
        self.assertEqual([r['position'] for r in state['recommendations']],[1,2,6])
        self.assertEqual(state['recommendations'][2]['url'],'https://www.youtube.com/watch?v=radio000001')
        self.assertEqual(state['recommendations'][2]['channel'],'NXZeroVEVO')
        self.assertEqual(state['upcoming'][0]['id'],'playlist001')
        self.assertEqual(state['current']['channel'],'Universal Music')

    def test_selected_sidebar_video_uses_same_tab_and_requires_real_playhead_progress(self):
        self.prepare_suggestions_fixture(playlist=True)
        self.context.select_music=Mock(return_value={'accepted':True,'candidate_id':'rec00000002','source':'recommendations','model_attempted':True})
        result=self.call('media',check='recommendation',query='Toque a primeira sugestão da mesma banda')
        self.assertTrue(result['verified']);self.assertTrue(result['playback_confirmed'])
        self.assertEqual(result['video_id'],'rec00000002');self.assertEqual(result['previous_video_id'],'cur00000001')
        self.assertEqual(result['selection_source'],'recommendations');self.assertGreaterEqual(result['position_seconds'],.3)
        self.context.select_music.assert_called_once()

    def test_artist_resolution_requeries_and_confirms_real_media_progress(self):
        from urllib.parse import urlparse
        from core.youtube_control import play_youtube
        searches=[]
        def check():
            def serve(route):
                url=route.request.url
                if '/results?' in url:
                    searches.append(url)
                    rows=''.join('<ytd-video-renderer><a id="video-title" title="Guns N Roses '+str(n)+'" href="/watch?v=fixture000'+str(n)+'">Faixa</a><div id="channel-name"><a>Guns N\' Roses</a></div></ytd-video-renderer>' for n in range(5))
                    body='<style>ytd-video-renderer{display:block}</style>'+rows
                else:
                    body='<title>Guns N Roses fixture</title><div id="movie_player"><video autoplay muted src="'+self.source+'"></video></div><script>document.querySelector("#movie_player").getVideoData=()=>({video_id:new URLSearchParams(location.search).get("v"),title:"Guns N Roses fixture"})</script>'
                route.fulfill(status=200,content_type='text/html',body=body)
            self.browser.context.unroute('**/*')
            self.browser.context.route('**/*',serve)
            resolve=Mock(return_value={'accepted':True,'query':"Guns N' Roses",'source':'test-fixture'})
            result=play_youtube(self.browser.page,'Gunner Rose',resolve=resolve)
            self.assertTrue(result['playback_confirmed']);self.assertTrue(result['verified'])
            self.assertGreaterEqual(result['position_seconds'],.3)
            self.assertEqual(result['effective_query'],"Guns N' Roses")
            self.assertEqual(result['requested_query'],'Gunner Rose')
            self.assertEqual(len(searches),2);resolve.assert_called_once()
            self.assertEqual(urlparse(self.browser.page.url).path,'/watch')
        self.browser.executor.submit(check).result(20)


if __name__=='__main__': unittest.main()
