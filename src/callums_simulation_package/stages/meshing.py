"""Configuration-driven Fluent Watertight Geometry meshing."""

from __future__ import annotations

from typing import Any, Mapping

from ..artifacts import RunArtifacts
from ..config import ConfigError, SimulationConfig
from ..fluent import managed_session
from ..operations import interpolate


def _structured_tasks(meshing: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Translate the concise meshing schema into workflow task operations."""

    required = ("describe_geometry", "surface_mesh", "volume_mesh")
    missing = [key for key in required if not isinstance(meshing.get(key), Mapping)]
    if missing:
        raise ConfigError(f"structured meshing configuration is missing: {missing}")
    tasks: list[dict[str, Any]] = [
        {
            "name": "Import Geometry",
            "operations": [
                {
                    "action": "set_state",
                    "value": {"FileName": "{{geometry}}"},
                },
                {
                    "action": "execute",
                },
            ],
        },
    ]
    
    for sizing in meshing.get("local_sizing", []):
        tasks.append(
            {
                "name": "Add Local Sizing",
                "operations": [
                    {
                        "action": "set_state",
                        "value": dict(sizing),
                    },
                    {
                        "action": "add_child_and_update",
                    },
                ],
            }
        )
    
    tasks.append(
        {
            "name": "Generate the Surface Mesh",
            "operations": [
                {
                    "action": "set_state",
                    "value": dict(meshing["surface_mesh"]),
                },
                {
                    "action": "execute",
                },
            ],
        }
    )
    
    tasks.append(
        {
            "name": "Describe Geometry",
            "operations": [
                {
                    "action": "update_child_tasks",
                    "kwargs": {"SetupTypeChanged": False},
                },
                {
                    "action": "set_state",
                    "value": dict(meshing["describe_geometry"]),
                },
                {
                    "action": "update_child_tasks",
                    "kwargs": {"SetupTypeChanged": True},
                },
                {
                    "action": "execute",
                },
            ],
        }
    )
    if isinstance(meshing.get("update_boundaries"), Mapping):
        tasks.append(
            {
                "name": "Update Boundaries",
                "operations": [
                    {
                        "action": "set_state",
                        "value": dict(meshing["update_boundaries"]),
                    },
                    {
                        "action": "execute",
                    },
                ],
            }
        )

    if isinstance(meshing.get("repair_geometry"), Mapping):
        tasks.append(
            {
                "name": "Repair Geometry",
                "optional": True,
                "operations": [
                    {
                        "action": "set_state",
                        "value": dict(meshing["repair_geometry"]),
                    },
                    {
                        "action": "execute",
                    },
                ],
            }
        )

    if isinstance(meshing.get("create_regions"), Mapping):
        tasks.append(
            {
                "name": "Create Regions",
                "operations": [
                    {
                        "action": "set_state",
                        "value": dict(meshing["create_regions"]),
                    },
                    {
                        "action": "execute",
                    },
                ],
            }
        )

    tasks.append(
        {
            "name": "Update Regions",
            "operations": [
                {
                    "action": "execute",
                },
            ],
        }
    )

    for boundary_layer in meshing.get("boundary_layers", []):
        layer_state = dict(boundary_layer)
        operation_kwargs = layer_state.pop(
            "_operation_kwargs",
            {},
        )

        tasks.append(
            {
                "name": "Add Boundary Layers",
                "operations": [
                    {
                        "action": "set_state",
                        "value": layer_state,
                    },
                    {
                        "action": "add_child_and_update",
                        "kwargs": operation_kwargs,
                    },
                ],
            }
        )

    tasks.append(
        {
            "name": "Generate the Volume Mesh",
            "operations": [
                {
                    "action": "set_state",
                    "value": dict(meshing["volume_mesh"]),
                },
                {
                    "action": "execute",
                },
            ],
        }
    )

    return tasks



def _task_operation(
    task: Any,
    operation: Mapping[str, Any],
    context: Mapping[str, str],
) -> None:
    action = operation.get("action")
    kwargs = interpolate(operation.get("kwargs", {}), context)

    if action == "set_state":
        task.Arguments.set_state(
            interpolate(operation.get("value", {}), context)
        )
    elif action == "update_child_tasks":
        task.UpdateChildTasks(**kwargs)
    elif action == "execute":
        task.Execute(**kwargs)
    elif action == "add_child_and_update":
        task.AddChildAndUpdate(**kwargs)
    elif action == "add_child_to_task":
        task.AddChildToTask(**kwargs)
    elif action == "insert_compound_child_task":
        task.InsertCompoundChildTask(**kwargs)
    else:
        raise ConfigError(
            f"unsupported meshing task action: {action}"
        )

def _workflow_task_names(session: Any) -> list[str]:
    """Return available Fluent workflow task identifiers."""

    try:
        value = session.workflow.Workflow.TaskList()
        return list(value) if value else []
    except Exception:
        pass

    try:
        value = session.workflow.TaskObject.child_names
        return list(value) if value else []
    except Exception:
        return []

def run_meshing(
    config: SimulationConfig,
    artifacts: RunArtifacts,
    launcher: Any = None,
) -> None:
    """Execute one declarative Fluent meshing workflow."""

    meshing = config.meshing
    tasks = meshing.get("tasks")
    if tasks is None:
        tasks = _structured_tasks(meshing)
    if not isinstance(tasks, list) or not tasks:
        raise ConfigError("meshing.tasks must be a non-empty array")
    context = artifacts.context() | {"geometry": str(config.geometry)}

    with managed_session("meshing", config.launch, launcher) as session:
        workflow_type = str(meshing.get("workflow_type", "Watertight Geometry"))
        session.workflow.InitializeWorkflow(WorkflowType=workflow_type)
        for task_index, task_spec in enumerate(tasks, start=1):
            if not isinstance(task_spec, Mapping) or not isinstance(task_spec.get("name"), str):
                raise ConfigError(f"meshing task {task_index} requires a name")
            name = task_spec["name"]
            try:
                task = session.workflow.TaskObject[name]
            except Exception as exc:
                if task_spec.get("optional", False):
                    print(f"Skipping unavailable optional task: {name}")
                    continue

                available_names = _workflow_task_names(session)
                raise ConfigError(
                    f"Fluent workflow does not contain or expose "
                    f"required task {name!r}. "
                    f"Available tasks: {available_names}"
                ) from exc
            operations = task_spec.get("operations", [])
            if not isinstance(operations, list):
                raise ConfigError(f"operations for meshing task {name!r} must be an array")
            for operation_index, operation in enumerate(operations, start=1):
                try:
                    _task_operation(task, operation, context)
                except Exception as exc:
                    raise RuntimeError(
                        f"meshing task {task_index} ({name}), operation {operation_index} failed: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc

        if meshing.get("check_mesh", True):
            session.tui.mesh.check_mesh()
        session.meshing.File.WriteMesh(FileName=str(artifacts.mesh))
