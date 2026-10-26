"""Tests for the documentation dependency pins."""

from __future__ import annotations

import unittest
from pathlib import Path


class RequirementsTests(unittest.TestCase):
    def test_documentation_requirements_are_pinned(self):
        requirements = Path(__file__).parents[2] / "requirements-docs.txt"
        for line in requirements.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            with self.subTest(requirement=line):
                self.assertIn("==", line)


if __name__ == "__main__":
    unittest.main()
