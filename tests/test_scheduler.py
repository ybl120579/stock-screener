# -*- coding: utf-8 -*-
"""调度器退避重试的单测（不联网、不起服务）。

背景：15:40 自动更新失败后，如果每 30 秒就重试一次，只会让东财的限流更久。
这里锁住“10/20/40/60 分钟退避、一天最多 5 次”的行为。
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "mobile"))

import app as mobile_app  # noqa: E402


class TestRetryBackoff(unittest.TestCase):
    def test_first_attempt_has_no_wait(self):
        self.assertEqual(mobile_app.retry_delay_min(0), 0)
        self.assertEqual(mobile_app.retry_delay_min(1), 10)

    def test_waits_grow(self):
        waits = [mobile_app.retry_delay_min(n) for n in (1, 2, 3, 4)]
        self.assertEqual(waits, [10, 20, 40, 60])
        # 超过序列长度后一直用最后一个
        self.assertEqual(mobile_app.retry_delay_min(9), 60)

    def test_not_ready_before_wait(self):
        now = datetime(2026, 11, 5, 15, 40)
        self.assertFalse(mobile_app.retry_ready(1, now - timedelta(minutes=9), now))
        self.assertTrue(mobile_app.retry_ready(1, now - timedelta(minutes=10), now))

    def test_second_failure_waits_longer(self):
        now = datetime(2026, 11, 5, 16, 0)
        # 第 2 次失败后要等 20 分钟
        self.assertFalse(mobile_app.retry_ready(2, now - timedelta(minutes=15), now))
        self.assertTrue(mobile_app.retry_ready(2, now - timedelta(minutes=20), now))

    def test_gives_up_after_max_attempts(self):
        now = datetime(2026, 11, 5, 23, 0)
        old = now - timedelta(hours=6)
        self.assertFalse(mobile_app.retry_ready(mobile_app.MAX_ATTEMPTS_PER_DAY, old, now))

    def test_no_previous_attempt_is_ready(self):
        self.assertTrue(mobile_app.retry_ready(0, None, datetime.now()))


if __name__ == "__main__":
    unittest.main()
