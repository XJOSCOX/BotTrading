import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import live_store
import practice_executor
import practice_safety
import bot_controls
import bot_audit
from execution_target import TARGETS


class LeaderIsolationTests(unittest.TestCase):
    def test_fixed_target_and_separate_state_in_child_process(self):
        with tempfile.TemporaryDirectory() as folder:
            script = '''
import sys
from pathlib import Path
from unittest.mock import patch
import live_store
live_store.DB_PATH = Path(sys.argv[1])
import practice_executor as e
import practice_safety as safety
import bot_audit
import bot_health
import bot_controls
from execution_target import TARGETS
assert e.ACCOUNT_ID == TARGETS['leader']['id']
assert e.ACCOUNT_NAME == TARGETS['leader']['name']
e.configure(dict(MNQ=3,MES=3,MYM=3),False)
assert not e.snapshot()[0].get('enabled')
signal=dict(id=12,symbol='NQ=F',signal='LONG',entry=100,stop=95)
contract=dict(id='CON.F.US.MNQ.Z26',symbolId='F.US.MNQ',activeContract=True)
order=e.build_order(signal,contract,3)
assert order['accountId']==TARGETS['leader']['id'] and order['size']==3
assert order['customTag']=='gx-leader-12'
assert order['stopLossBracket']['ticks']==-20
account=dict(id=TARGETS['leader']['id'],name=e.ACCOUNT_NAME,canTrade=True,simulated=True)
with patch.object(e,'call',return_value=dict(accounts=[account])), patch.object(e,'copy_role',return_value='Leader'):
    assert e.verify_account('fake')==account
with patch.object(e,'call',return_value=dict(accounts=[account])), patch.object(e,'copy_role',return_value='Follower'):
    try: e.verify_account('fake'); raise AssertionError('Follower was accepted')
    except RuntimeError: pass
bot_controls.save(['MNQ','MES'],['CRT'],5)
bot_health.record([],[])
bot_audit.emit('test','Test','leader event',notify=True)
safety.check(50000,account_id=e.TARGET['gate_id'])
assert safety.check(49500,account_id=e.TARGET['gate_id'])['locked']
assert e.claim(dict(alert_id=12,state='Intent',symbol='MNQ',contract_id=contract['id'],quantity=3))
print('isolated')
'''
            result = subprocess.run([sys.executable,"-c",script,str(Path(folder)/"test.db")],env={**os.environ,"GOX_EXECUTION_PROFILE":"leader"},capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            with patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
                self.assertEqual(practice_executor.snapshot()[2],[])
                self.assertFalse(practice_safety.snapshot().get("locked"))
                self.assertEqual(bot_controls.read()["strategies"],["CRT","Reversal"])
                self.assertEqual(bot_controls.read("leader")["strategies"],["CRT"])
                self.assertEqual(bot_audit.events(),[])
                self.assertGreater(len(bot_audit.events(account="leader")),0)
                with self.assertRaises(ValueError):
                    practice_executor.control(dict(enabled=True))
                with self.assertRaises(ValueError):
                    practice_executor.claim(dict(alert_id=12,state="Intent"))

    def test_loss_locks_and_notifications_are_independent(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            practice_safety.check(1000)
            practice_safety.check(50000,account_id=TARGETS['leader']['id'])
            practice_safety.check(49499,account_id=TARGETS['leader']['id'])
            self.assertTrue(practice_safety.snapshot(TARGETS['leader']['id'])["locked"])
            self.assertFalse(practice_safety.snapshot()["locked"])
            practice_safety.check(1000,acknowledge=True)
            self.assertTrue(practice_safety.snapshot(TARGETS['leader']['id'])["locked"])

    def test_commands_cannot_run_in_practice_process(self):
        import leader_worker
        with self.assertRaises(ValueError):
            leader_worker.handle_command(dict(action="arm",confirmed_account=TARGETS['leader']['name']))

    def test_unknown_profile_fails_closed(self):
        result = subprocess.run([sys.executable,"-c","import execution_target"],env={**os.environ,"GOX_EXECUTION_PROFILE":"follower"},capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)


if __name__ == "__main__":
    unittest.main()
