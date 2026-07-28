from __future__ import annotations

import unittest

from callums_simulation_package.config import FluentLaunchConfig
from callums_simulation_package.fluent import managed_session


class Session:
    def __init__(self):
        self.closed = False

    def exit(self):
        self.closed = True


class FluentTests(unittest.TestCase):
    def test_session_is_closed_after_stage_error(self) -> None:
        session = Session()

        def launcher(mode, config):
            self.assertEqual(mode, "solver")
            self.assertIsInstance(config, FluentLaunchConfig)
            return session

        with self.assertRaisesRegex(RuntimeError, "stage failed"):
            with managed_session("solver", FluentLaunchConfig(), launcher):
                raise RuntimeError("stage failed")

        self.assertTrue(session.closed)

    def test_null_processor_count_is_omitted_for_scheduler_detection(self) -> None:
        self.assertNotIn("processor_count", FluentLaunchConfig(processor_count=None).kwargs())
        self.assertEqual(FluentLaunchConfig(processor_count=16).kwargs()["processor_count"], 16)


if __name__ == "__main__":
    unittest.main()
