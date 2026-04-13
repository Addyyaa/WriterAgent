from __future__ import annotations

import io
import json
import logging
import unittest

from packages.core.logging import StructuredObservability
from packages.core.tracing import (
    clear_request_id,
    clear_trace_id,
    get_request_id,
    get_trace_id,
    request_context,
)


class TestCoreTracing(unittest.TestCase):
    def test_request_context_lifecycle(self) -> None:
        clear_request_id()
        clear_trace_id()
        self.assertIsNone(get_request_id())
        self.assertIsNone(get_trace_id())

        with request_context(request_id="rid", trace_id="tid"):
            self.assertEqual(get_request_id(), "rid")
            self.assertEqual(get_trace_id(), "tid")

        self.assertIsNone(get_request_id())
        self.assertIsNone(get_trace_id())


class TestCoreLogging(unittest.TestCase):
    def test_emit_with_trace_context(self) -> None:
        stream = io.StringIO()
        logger_name = "writeragent.test.core.logging"
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False

        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)

        obs = StructuredObservability(logger_name=logger_name, enable_logging=True)

        with request_context(request_id="rid-1", trace_id="tid-1"):
            obs.emit("unit.event", value=1)

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual(payload["event"], "unit.event")
        self.assertEqual(payload["request_id"], "rid-1")
        self.assertEqual(payload["trace_id"], "tid-1")
        self.assertEqual(payload["value"], 1)

    def test_emit_non_serializable_field(self) -> None:
        stream = io.StringIO()
        logger_name = "writeragent.test.core.logging.nonserial"
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False

        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)

        obs = StructuredObservability(logger_name=logger_name, enable_logging=True)
        obs.emit("unit.obj", obj=object())

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual(payload["event"], "unit.obj")
        self.assertIn("obj", payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
