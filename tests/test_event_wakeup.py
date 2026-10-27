from types import SimpleNamespace
from threading import Event, Thread
from unittest.mock import Mock, patch
import unittest
import requests

from goxtrade.runtime import event_wakeup
from goxtrade.bot import bot_monitor
from goxtrade.execution import practice_executor as executor


class WakeSignalTests(unittest.TestCase):
    def test_burst_during_work_is_coalesced_but_not_lost(self):
        signal=event_wakeup.WakeSignal()
        observed=signal.version()
        for _ in range(10000):signal.notify()
        self.assertEqual(signal.wait(observed,30),10000)

    def test_waiting_consumer_wakes_before_watchdog(self):
        signal=event_wakeup.WakeSignal()
        observed=signal.version()
        ready,done=Event(),Event()
        def consumer():
            ready.set()
            signal.wait(observed,3)
            done.set()
        worker=Thread(target=consumer,daemon=True)
        worker.start();self.assertTrue(ready.wait(1))
        signal.notify()
        self.assertTrue(done.wait(1))
        worker.join(1)
        self.assertFalse(worker.is_alive())

    def test_storm_cannot_bypass_minimum_cycle_spacing(self):
        signal=event_wakeup.WakeSignal()
        for _ in range(10000):signal.notify()
        with patch.object(event_wakeup,'time',SimpleNamespace(monotonic=Mock(side_effect=[0,0,2]))),patch.object(signal.condition,'wait') as wait:
            self.assertEqual(signal.wait(0,3,not_before=2),10000)
        wait.assert_called_once_with(2)

    def test_watchdog_waits_until_rate_boundary_even_if_timeout_elapsed(self):
        signal=event_wakeup.WakeSignal()
        with patch.object(event_wakeup,'time',SimpleNamespace(monotonic=Mock(side_effect=[0,3,5]))),patch.object(signal.condition,'wait') as wait:
            self.assertEqual(signal.wait(0,1,not_before=5),0)
        wait.assert_called_once_with(2)

    def test_idle_watchdog_returns_without_manufacturing_event(self):
        signal=event_wakeup.WakeSignal()
        self.assertEqual(signal.wait(0,0),0)
        self.assertEqual(signal.version(),0)

    def test_timer_fallback_runs_without_market_notifications(self):
        signal=event_wakeup.WakeSignal()
        self.assertEqual(signal.wait(0,.01),0)


class WorkerWakeTests(unittest.TestCase):
    def test_monitor_publishes_after_evaluation_and_retains_watchdog(self):
        wake=Mock();wake.version.return_value=7;wake.wait.side_effect=KeyboardInterrupt
        execution=Mock()
        with patch.object(bot_monitor,'monitor_once') as monitor,patch.object(bot_monitor,'time',SimpleNamespace(monotonic=lambda:100)):
            with self.assertRaises(KeyboardInterrupt):bot_monitor.run_monitor(wake,execution)
        monitor.assert_called_once_with()
        execution.notify.assert_called_once_with()
        wake.wait.assert_called_once_with(7,2,not_before=100.5)

    def test_execution_wakeup_runs_the_original_cycle_with_rate_headroom(self):
        wake=Mock();wake.version.return_value=4;wake.wait.side_effect=KeyboardInterrupt
        clock=SimpleNamespace(monotonic=lambda:100,time=lambda:100)
        with patch.object(executor,'snapshot',return_value=(dict(enabled=True),{},[])),patch.object(executor,'login',return_value='fixture'),patch.object(executor,'cycle') as cycle,patch.object(executor,'time',clock),patch.object(executor,'SCHEDULING_MODE','watchdog'):
            with self.assertRaises(KeyboardInterrupt):executor.run_practice(wake)
            self.assertEqual(executor.SCHEDULING_MODE,'event-driven-coalesced-v1')
        cycle.assert_called_once_with('fixture')
        wake.wait.assert_called_once_with(4,3,not_before=102)

    def test_paused_idle_worker_does_not_poll_broker_on_every_tick(self):
        wake=Mock();wake.version.return_value=0;wake.wait.side_effect=KeyboardInterrupt
        with patch.object(executor,'snapshot',return_value=(dict(enabled=False),{},[])),patch.object(executor,'login',return_value='fixture'),patch.object(executor,'cycle'),patch.object(executor,'time',SimpleNamespace(monotonic=lambda:100,time=lambda:100)),patch.object(executor,'SCHEDULING_MODE','watchdog'):
            with self.assertRaises(KeyboardInterrupt):executor.run_practice(wake)
        wake.wait.assert_called_once_with(0,15,not_before=115)

    def test_tick_notifications_never_shorten_retry_backoff(self):
        wake=Mock();wake.version.return_value=0
        with patch.object(executor,'snapshot',return_value=(dict(enabled=True),{},[])),patch.object(executor,'login',return_value='fixture'),patch.object(executor,'cycle',side_effect=requests.Timeout()),patch.object(executor,'recover_connection'),patch.object(executor,'Event') as event,patch.object(executor,'SCHEDULING_MODE','watchdog'):
            event.return_value.wait.side_effect=KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):executor.run_practice(wake)
        event.return_value.wait.assert_called_once_with(3)
        wake.wait.assert_not_called()


if __name__=='__main__':unittest.main()
