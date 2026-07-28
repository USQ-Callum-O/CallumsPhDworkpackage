from __future__ import annotations

import unittest

from callums_simulation_package.operations import OperationError, apply_operations, deep_merge


class Setting:
    def __init__(self, state=None):
        self.state = state

    def set_state(self, value):
        self.state = value

    def get_state(self):
        return self.state


class Collection(dict):
    @property
    def child_names(self):
        return list(self)

    def create(self, name):
        self[name] = Setting({})

    def delete(self, name):
        del self[name]


class Root:
    def __init__(self):
        self.value = Setting(1)
        self.children = Collection(existing=Setting({"a": {"b": 1}}))

    def record(self, *args, **kwargs):
        self.recorded = (args, kwargs)


class OperationTests(unittest.TestCase):
    def test_declarative_operations_and_interpolation(self) -> None:
        root = Root()
        apply_operations(
            root,
            [
                {"action": "set", "path": "value", "value": "{{mesh}}"},
                {"action": "patch", "path": "children/@existing", "value": {"a": {"c": 2}}},
                {"action": "create", "path": "children", "name": "new"},
                {
                    "action": "call",
                    "path": "record",
                    "args": [1],
                    "kwargs": {"path": "{{mesh}}"},
                },
            ],
            {"mesh": "/results/run.msh.h5"},
        )

        self.assertEqual(root.value.state, "/results/run.msh.h5")
        self.assertEqual(root.children["existing"].state, {"a": {"b": 1, "c": 2}})
        self.assertIn("new", root.children)
        self.assertEqual(root.recorded, ((1,), {"path": "/results/run.msh.h5"}))

    def test_operation_errors_include_position_and_path(self) -> None:
        with self.assertRaisesRegex(OperationError, r"operation 1 failed .*missing"):
            apply_operations(Root(), [{"action": "set", "path": "missing", "value": 1}], {})

    def test_deep_merge_does_not_mutate_input(self) -> None:
        original = {"a": {"b": 1}}
        self.assertEqual(deep_merge(original, {"a": {"c": 2}}), {"a": {"b": 1, "c": 2}})
        self.assertEqual(original, {"a": {"b": 1}})


if __name__ == "__main__":
    unittest.main()
