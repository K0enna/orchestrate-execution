"""Independent contract checks for the deliberately broken operations fixture."""
import importlib.util
from pathlib import Path
import sys
import unittest


def suite(module):
    class Contract(unittest.TestCase):
        def test_clamp_values_and_equal_bounds(self):
            for value, lower, upper, expected in [
                (-10, 0, 10, 0), (0, 0, 10, 0), (3, 0, 10, 3),
                (10, 0, 10, 10), (15, 0, 10, 10),
                (-7, -5, -2, -5), (-3, -5, -2, -3),
                (1.5, 1.0, 2.0, 1.5), (8, 4, 4, 4),
            ]:
                with self.subTest(value=value, lower=lower, upper=upper):
                    self.assertEqual(module.clamp(value, lower, upper), expected)

        def test_reversed_bounds(self):
            with self.assertRaises(ValueError):
                module.clamp(3, 10, 0)

        def test_rotation_values(self):
            for offset, expected in [
                (0, [1, 2, 3]), (1, [3, 1, 2]), (-1, [2, 3, 1]),
                (3, [1, 2, 3]), (7, [3, 1, 2]), (-7, [2, 3, 1]),
            ]:
                with self.subTest(offset=offset):
                    self.assertEqual(module.rotate([1, 2, 3], offset), expected)

        def test_rotation_preserves_input_and_returns_new_list(self):
            for offset in (0, 1, -1, 3):
                original = [1, 2, 3]
                result = module.rotate(original, offset)
                self.assertEqual(original, [1, 2, 3])
                self.assertIsInstance(result, list)
                self.assertIsNot(result, original)

        def test_empty_rotation(self):
            original = []
            for offset in (0, 2, -2):
                result = module.rotate(original, offset)
                self.assertEqual(result, [])
                self.assertIsNot(result, original)

        def test_single_item(self):
            original = ["a"]
            result = module.rotate(original, 99)
            self.assertEqual(result, ["a"])
            self.assertIsNot(result, original)
            self.assertEqual(original, ["a"])
    return unittest.defaultTestLoader.loadTestsFromTestCase(Contract)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -B benchmarks/check_operations.py /path/to/operations.py")
    path = Path(sys.argv[1]).resolve(strict=True)
    spec = importlib.util.spec_from_file_location("fixture_operations", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = unittest.TextTestRunner(verbosity=2).run(suite(module))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

