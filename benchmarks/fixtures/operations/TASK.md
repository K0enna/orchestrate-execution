Fix operations.py. clamp(value, lower, upper) must return the nearest value in the inclusive range, preserving values inside it. Reversed bounds must raise ValueError; equal bounds are valid. Numeric inputs need no coercion.

rotate(items, offset) must return a new list rotated right by the integer offset. Negative and oversized offsets wrap, the input list remains unchanged, and empty input returns a new empty list.

Change only operations.py. Use no dependencies. Read and run the existing check: python -B -m unittest -v test_operations.py. Report the source identity, actual terminal result and any scope limitation. Stop after local verification; no commits, publication or delegation. The task is small enough for direct execution.

This deliberately broken fixture supports a forward smoke test. Its two visible test methods are incomplete; the coordinator also checks the full stated contract after the return. Do not mistake this fixture for production library code.

