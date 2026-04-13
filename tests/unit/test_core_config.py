from __future__ import annotations

import unittest

from packages.core.config import (
    clamp,
    env_bool,
    env_float,
    env_float_or_none,
    env_int,
    env_str,
    env_str_or_none,
)


class TestCoreConfig(unittest.TestCase):
    def test_env_bool(self) -> None:
        environ = {"A": "true", "B": "0"}
        self.assertTrue(env_bool("A", False, environ=environ))
        self.assertFalse(env_bool("B", True, environ=environ))
        self.assertTrue(env_bool("MISS", True, environ=environ))

    def test_env_int_with_bounds(self) -> None:
        environ = {"A": "20", "B": "bad"}
        self.assertEqual(env_int("A", 1, environ=environ), 20)
        self.assertEqual(env_int("A", 1, minimum=30, environ=environ), 30)
        self.assertEqual(env_int("A", 1, maximum=10, environ=environ), 10)
        self.assertEqual(env_int("B", 7, environ=environ), 7)

    def test_env_float_or_none(self) -> None:
        environ = {"A": "0.3", "B": "none", "C": "bad"}
        self.assertAlmostEqual(env_float("A", 0.1, environ=environ), 0.3, places=6)
        self.assertAlmostEqual(
            env_float("A", 0.1, minimum=0.5, maximum=0.9, environ=environ),
            0.5,
            places=6,
        )
        self.assertIsNone(env_float_or_none("B", 0.2, environ=environ))
        self.assertAlmostEqual(env_float_or_none("C", 0.2, environ=environ) or 0.0, 0.2)

    def test_env_str(self) -> None:
        environ = {"A": " hello ", "B": ""}
        self.assertEqual(env_str("A", "d", environ=environ), "hello")
        self.assertEqual(env_str("B", "d", environ=environ), "d")
        self.assertIsNone(env_str_or_none("B", None, environ=environ))
        self.assertEqual(env_str_or_none("A", None, environ=environ), "hello")

    def test_clamp(self) -> None:
        self.assertEqual(clamp(1.5, minimum=2.0), 2.0)
        self.assertEqual(clamp(3.5, maximum=3.0), 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
