import unittest
from operations import clamp, rotate


class OperationTests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(-1, 0, 10), 0)
        self.assertEqual(clamp(4, 0, 10), 4)
        self.assertEqual(clamp(11, 0, 10), 10)

    def test_rotation(self):
        self.assertEqual(rotate([1, 2, 3], 1), [3, 1, 2])
        self.assertEqual(rotate([1, 2, 3], -1), [2, 3, 1])


if __name__ == "__main__":
    unittest.main()

