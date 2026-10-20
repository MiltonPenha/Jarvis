"""Authorized session boundaries and recovery; live playback is tested separately."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

def setUpModule():
    # Discovery imports test_jarvis to configure its isolated data directory.
    # Do not initialize the application config before that module is loaded.
    global connection_status,Plan,ground_plan,direct_plan,BrowserControl
    from core.chrome_session import connection_status
    from core.local_runtime import Plan,ground_plan,direct_plan
    from core.browser_control import BrowserControl


class ChromeConnectionTests(unittest.TestCase):
    def test_native_websocket_resolution_is_limited_to_configured_port(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'DevToolsActivePort').write_text('9222\n/devtools/browser/published-id')
            catalog={'root':root,'profiles':[{'directory':'Default','name':'Test'}]}
            with patch('core.chrome_session.profile_catalog',return_value=catalog),patch('core.chrome_session.browser_settings',return_value={'endpoint':'http://127.0.0.1:9222'}):
                self.assertEqual(connection_status()['resolved_endpoint'],'ws://127.0.0.1:9222/devtools/browser/published-id')
            with patch('core.chrome_session.profile_catalog',return_value=catalog),patch('core.chrome_session.browser_settings',return_value={'endpoint':'http://127.0.0.1:9333'}):
                self.assertEqual(connection_status()['resolved_endpoint'],'http://127.0.0.1:9333')

    def test_shared_context_disconnect_never_closes_user_pages(self):
        b=BrowserControl(mode='chrome');ctx=Mock();driver=Mock()
        b.context=ctx;b.playwright=driver
        try:
            b.close()
            ctx.close.assert_not_called();driver.stop.assert_called_once()
        finally:b.executor.shutdown(wait=True)

    def test_cdp_uses_existing_context_verifies_profile_and_reuses_youtube(self):
        b=BrowserControl(mode='chrome')
        page=Mock();page.url='https://www.youtube.com/';page.is_closed.return_value=False
        unrelated=Mock();unrelated.url='https://example.com/';unrelated.is_closed.return_value=False
        probe=Mock();probe.locator.return_value.inner_text.return_value='C:/Chrome/User Data/Default'
        ctx=Mock();ctx.pages=[unrelated,page];ctx.new_page.return_value=probe
        browser=Mock();browser.contexts=[ctx]
        driver=Mock();driver.chromium.connect_over_cdp.return_value=browser
        status={'endpoint':'chrome','resolved_endpoint':'chrome','authorization_available':True,'profile':'Default'}
        try:
            with patch('playwright.sync_api.sync_playwright') as start,patch('core.browser_control.connection_status',return_value=status),patch.object(b,'_queue_pump'):
                start.return_value.start.return_value=driver
                b._start()
                b._start()
                driver.chromium.connect_over_cdp.assert_called_once_with('chrome',no_defaults=True,timeout=30000)
                self.assertIs(b.context,ctx);self.assertIs(b.page,page)
                self.assertEqual(b.managed_pages,{page});probe.close.assert_called_once()
                unrelated.evaluate.assert_not_called();unrelated.close.assert_not_called()
        finally:b.close();b.executor.shutdown(wait=True)

    def test_missing_authorization_never_launches_anonymous_chrome(self):
        b=BrowserControl(mode='chrome')
        try:
            with patch('playwright.sync_api.sync_playwright') as start,patch('core.browser_control.connection_status',return_value={'endpoint':'chrome','authorization_available':False}):
                with self.assertRaisesRegex(ValueError,'autorize'):b._start()
                start.return_value.start.return_value.chromium.launch_persistent_context.assert_not_called()
        finally:b.close();b.executor.shutdown(wait=True)

    def test_restarted_media_can_rebind_only_the_unique_confirmed_video(self):
        from core.operational_context import OperationalContext
        b=BrowserControl(mode='chrome');context=OperationalContext('same-conversation')
        matched=Mock();matched.url='https://www.youtube.com/watch?v=known000001';matched.is_closed.return_value=False
        unrelated=Mock();unrelated.url='https://www.youtube.com/watch?v=other000001';unrelated.is_closed.return_value=False
        b.context=Mock();b.context.pages=[unrelated,matched]
        state={'exists':True,'count':1,'video_id':'known000001','identity':'known000001','error':''}
        try:
            with patch('core.task_store.TaskStore.last_playback',return_value={'video_id':'known000001'}) as known,patch('core.media_control.player_state',return_value=state) as observe:
                self.assertTrue(b._recover_media(context))
                known.assert_called_once_with('same-conversation');observe.assert_called_once_with(matched)
                self.assertIs(b.page,matched);self.assertTrue(context.media_tab_id)
                unrelated.evaluate.assert_not_called();unrelated.close.assert_not_called()
                twin=Mock();twin.url=matched.url;twin.is_closed.return_value=False
                b.context.pages=[matched,twin];observe.reset_mock()
                self.assertFalse(b._recover_media(context));self.assertEqual(observe.call_count,2)
        finally:b.context=None;b.browser=None;b.executor.shutdown(wait=True)

    def test_cold_start_after_autoplay_uses_only_a_unique_active_youtube_player(self):
        from core.operational_context import OperationalContext
        b=BrowserControl(mode='chrome');ctx=OperationalContext('new-session',media_query='stale artist')
        active=Mock();active.url='https://www.youtube.com/watch?v=current0001';active.is_closed.return_value=False
        other=Mock();other.url='https://example.com/';other.is_closed.return_value=False
        b.context=Mock();b.context.pages=[other,active]
        state={'exists':True,'count':1,'paused':False,'ad':False,'error':'','video_id':'current0001','identity':'current0001'}
        try:
            with patch('core.task_store.TaskStore.last_playback',return_value=None),patch('core.media_control.player_state',return_value=state) as observe:
                self.assertTrue(b._recover_media(ctx));observe.assert_called_once_with(active)
                self.assertEqual(ctx.media_query,'');other.evaluate.assert_not_called()
                twin=Mock();twin.url='https://www.youtube.com/watch?v=another0001';twin.is_closed.return_value=False
                b.context.pages=[active,twin];self.assertFalse(b._recover_media(OperationalContext('ambiguous')))
        finally:b.context=None;b.browser=None;b.executor.shutdown(wait=True)

    def test_reading_suggestions_can_refresh_identity_after_autoplay_without_controlling_it(self):
        from core.operational_context import OperationalContext
        b=BrowserControl(mode='chrome');page=Mock();ctx=OperationalContext('autoplay',media_tab_id='tab',media_identity='old')
        state={'exists':True,'count':1,'identity':'new'}
        try:
            with patch.object(b,'_live_tabs',return_value={'tab':page}),patch('core.media_control.player_state',return_value=state):
                with self.assertRaisesRegex(ValueError,'mudou'):b._media_target(ctx,'next')
                observed,before=b._media_target(ctx,'suggestions')
                self.assertIs(observed,page);self.assertEqual(ctx.media_identity,'new');page.evaluate.assert_not_called()
        finally:b.executor.shutdown(wait=True)

    def test_closing_a_tab_keeps_the_authorized_browser_connection(self):
        b=BrowserControl(mode='chrome');page=Mock();page.is_closed.side_effect=[False,True]
        b.context=Mock();b.context.pages=[page];b.page=page;b.managed_pages={page}
        b.browser=Mock();b.browser.is_connected.return_value=True
        page.wait_for_timeout.side_effect=RuntimeError('Page closed while pumping')
        try:
            with patch.object(b,'_close') as detach,patch.object(b,'_queue_pump'):
                b._pump();detach.assert_not_called()
                self.assertIsNotNone(b.context)
        finally:b.context=None;b.browser=None;b.executor.shutdown(wait=True)

    def test_explicit_video_url_adopts_only_one_existing_tab_without_navigation(self):
        from core.operational_context import OperationalContext
        b=BrowserControl(mode='chrome');ctx=OperationalContext('explicit-video')
        page=Mock();page.url='https://www.youtube.com/watch?v=XdglM81b4g8&list=PL';page.is_closed.return_value=False
        other=Mock();other.url='https://example.com/';other.is_closed.return_value=False
        b.context=Mock();b.context.pages=[other,page]
        args={'action':'browser_select','query':'https://www.youtube.com/watch?v=XdglM81b4g8'}
        try:
            with patch.object(b,'_start'),patch.object(b,'_snapshot',return_value={'verified':True}),patch('core.media_control.player_state',return_value={'exists':True,'count':1,'identity':'XdglM81b4g8'}):
                self.assertTrue(b._tool(args,ctx,lambda:False)['verified'])
                self.assertIs(b.page,page);self.assertEqual(ctx.media_tab_id,ctx.tab_id)
                page.goto.assert_not_called();b.context.new_page.assert_not_called();other.evaluate.assert_not_called()
                twin=Mock();twin.url=page.url;twin.is_closed.return_value=False
                b.context.pages=[page,twin]
                with self.assertRaisesRegex(ValueError,'única aba'):b._tool(args,ctx,lambda:False)
                b.context.pages=[other]
                with self.assertRaisesRegex(ValueError,'única aba'):b._tool(args,ctx,lambda:False)
        finally:b.context=None;b.browser=None;b.executor.shutdown(wait=True)

    def test_saving_unchanged_settings_does_not_detach(self):
        import asyncio,server
        value={'mode':'chrome','profile':'Default','endpoint':'chrome'}
        with patch('core.chrome_session.browser_settings',return_value=value),patch('core.chrome_session.save_browser_settings',return_value=value),patch('core.browser_control.browser_control.close') as close,patch.object(server,'browser_status',return_value={'connected':True}):
            self.assertEqual(asyncio.run(server.browser_settings_update(value)),{'connected':True})
            close.assert_not_called()


class GroundingTests(unittest.TestCase):
    def test_explicit_selection_preserves_the_provided_video_url(self):
        url='https://www.youtube.com/watch?v=XdglM81b4g8'
        self.assertEqual(direct_plan('Selecione a aba '+url)['steps'][0],{'action':'browser_select','target':url,'content':'','when':''})

    def test_observed_failure_cannot_become_a_fabricated_music_click(self):
        command='Boa noite, Javis. Abra o Google, entra no YouTube, toque uma música do Queen.'
        result=direct_plan(command)
        self.assertEqual([x['action'] for x in result['steps']],['browser_open','browser_open','play_music'])
        model=Plan.model_validate({'steps':[{'action':'browser_open','target':'google'},{'action':'browser_click','target':'Invented Music Video'}]})
        grounded=ground_plan(model,command)
        self.assertEqual([(x.action,x.target) for x in grounded.steps],[('browser_open','google'),('browser_open','youtube'),('play_music','Queen')])

    def test_followups_are_parameterized_without_a_model(self):
        self.assertEqual(direct_plan('Toque outra do mesmo artista')['steps'][0]['target'],'recommendation')
        self.assertEqual(direct_plan('Agora coloque uma música do Daft Punk')['steps'][0]['target'],'Daft Punk')
        command='Toque outra do mesmo artista'
        grounded=ground_plan(Plan.model_validate(direct_plan(command)),command)
        self.assertEqual([(item.action,item.target) for item in grounded.steps],[('media','recommendation')])
