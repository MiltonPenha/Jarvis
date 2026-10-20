"""Restart lifecycle contracts; no real process or server is killed here."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch


class WorkerRecoveryTests(unittest.TestCase):
    def setUp(self):
        from core.local_model import LocalModel,config
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.patch=patch.object(config,'DATA_DIR',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.model=LocalModel();self.executable=str(self.root/'ollama.exe')
        self.worker=Mock();self.worker.create_time.return_value=10.;self.worker.exe.return_value=self.executable
        self.worker.environ.return_value={'OLLAMA_HOST':'127.0.0.1:11439','OLLAMA_MODELS':str(self.root/'models/ollama')}
        self.worker.children.return_value=[]
        self.record={'pid':123,'created_at':10.,'owner_pid':456,'owner_created_at':20.}
        self.model.worker_record.write_text(json.dumps(self.record),encoding='utf-8')

    def processes(self,pid):
        import psutil
        if pid==123:return self.worker
        raise psutil.NoSuchProcess(pid)

    def test_reaps_only_owned_worker_with_absent_owner(self):
        with patch('psutil.Process',side_effect=self.processes),patch('psutil.wait_procs',return_value=([],[])):
            self.assertTrue(self.model._recover_orphan(self.executable))
        self.worker.terminate.assert_called_once();self.assertFalse(self.model.worker_record.exists())

    def test_live_owner_is_never_stopped(self):
        owner=Mock();owner.create_time.return_value=20.
        with patch('psutil.Process',side_effect=lambda pid:self.worker if pid==123 else owner):
            self.assertFalse(self.model._recover_orphan(self.executable))
        self.worker.terminate.assert_not_called()

    def test_pid_reuse_and_foreign_environment_are_never_stopped(self):
        with patch('psutil.Process',side_effect=self.processes):
            self.worker.create_time.return_value=11.
            self.assertFalse(self.model._recover_orphan(self.executable))
            self.worker.create_time.return_value=10.
            self.worker.environ.return_value['OLLAMA_MODELS']=str(self.root/'other-project')
            self.assertFalse(self.model._recover_orphan(self.executable))
        self.worker.terminate.assert_not_called()

    def test_unrecorded_worker_is_not_touched(self):
        self.model.worker_record.unlink()
        with patch('psutil.Process') as process:
            self.assertFalse(self.model._recover_orphan(self.executable));process.assert_not_called()

    def test_stop_cannot_remove_another_instance_record(self):
        self.model.worker_identity={**self.record,'pid':789}
        self.model.stop()
        self.assertEqual(json.loads(self.model.worker_record.read_text()),self.record)


class GracefulStopTests(unittest.TestCase):
    def test_waits_until_endpoint_is_closed(self):
        from scripts.stop import stop_server
        client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
        health=Mock();health.json.return_value={'engine':'Hermes AIAgent'}
        client.get.side_effect=[health,Mock()]
        probe=MagicMock();probe.__enter__.return_value.connect_ex.side_effect=[0,10061]
        def socket():
            self.assertTrue(client.__exit__.called,'Close HTTP before waiting for the listener')
            return probe
        with patch('scripts.stop.httpx.Client',return_value=client),patch('scripts.stop.socket.socket',side_effect=socket),patch('scripts.stop.time.sleep'):
            self.assertTrue(stop_server(8000))
        client.post.assert_called_once_with('/api/shutdown')
        self.assertEqual(client.get.call_count,2)

    def test_other_service_on_port_is_not_stopped(self):
        from scripts.stop import stop_server
        client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
        client.get.return_value.json.return_value={'engine':'another-service'}
        with patch('scripts.stop.httpx.Client',return_value=client):
            with self.assertRaisesRegex(RuntimeError,'outro serviço'):stop_server(8000)
        client.post.assert_not_called()


if __name__=='__main__':unittest.main()
