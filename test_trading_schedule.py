import unittest
from datetime import datetime
from trading_schedule import execution_schedule


class ScheduleTests(unittest.TestCase):
    def test_boundaries_and_dst(self):
        for date,offset in (("2026-09-17","-05:00"),("2026-01-15","-06:00")):
            for clock,allowed,flat in (("14:49:59",True,False),("14:50:00",False,False),("15:04:59",False,False),("15:05:00",False,True),("15:10:00",False,True),("16:59:59",False,True),("17:00:00",True,False)):
                result = execution_schedule(datetime.fromisoformat(f"{date}T{clock}{offset}"))
                self.assertEqual((result["allow_entry"],result["flatten"]),(allowed,flat))

    def test_weekend(self):
        for stamp,allowed in (("2026-09-18T17:00:00-05:00",False),("2026-09-19T12:00:00-05:00",False),("2026-09-20T16:59:59-05:00",False),("2026-09-20T17:00:00-05:00",True)):
            self.assertEqual(execution_schedule(datetime.fromisoformat(stamp))["allow_entry"],allowed)
