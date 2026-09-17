import unittest
from unittest.mock import patch
import leader_worker
import practice_executor
import bot_controls


class LeaderMymTests(unittest.TestCase):
    def test_explicit_opt_in_and_default_off(self):
        with patch.object(leader_worker,"PROFILE","leader"), patch.object(practice_executor,"configure") as configure, patch.object(bot_controls,"save") as save:
            request = dict(action="configure",quantities=dict(MNQ=3,MES=3,MYM=2))
            leader_worker.handle_command(request)
            self.assertFalse(configure.call_args.args[1])
            self.assertEqual(save.call_args.args[0],["MNQ","MES"])
            leader_worker.handle_command(dict(request,enable_mym=True))
            self.assertTrue(configure.call_args.args[1])
            self.assertEqual(save.call_args.args[0],["MNQ","MES","MYM"])
            with self.assertRaises(ValueError):
                leader_worker.handle_command(dict(request,enable_mym="true"))
