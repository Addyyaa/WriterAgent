from __future__ import annotations

import unittest

from packages.core.errors import CoreConfigError, CoreError
from packages.core.logging import StructuredObservability
from packages.memory.long_term.observability import MemoryObservability
from packages.retrieval.errors import RetrievalConfigError, RetrievalError


class TestCoreErrorsAndCompat(unittest.TestCase):
    def test_error_inheritance(self) -> None:
        self.assertTrue(issubclass(RetrievalError, CoreError))
        self.assertTrue(issubclass(RetrievalConfigError, CoreConfigError))

    def test_memory_observability_compat_layer(self) -> None:
        obs = MemoryObservability(logger_name="writeragent.test", enable_logging=False)
        self.assertIsInstance(obs, StructuredObservability)
        obs.incr("m", 2)
        self.assertEqual(obs.snapshot().get("m"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
