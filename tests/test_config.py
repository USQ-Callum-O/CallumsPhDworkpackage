from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from callums_simulation_package.artifacts import RunArtifacts
from callums_simulation_package.config import ConfigError, load_config, validate_inputs


def write_config(tmp_path: Path, *, geometry: str = "model.pmdb", stages=None) -> Path:
    geometry_root = tmp_path / "Geometry"
    results_root = tmp_path / "Results"
    geometry_root.mkdir()
    config = {
        "schema_version": 1,
        "simulation": {
            "id": "Nozzle_simulation1.1",
            "category": "nozzle",
            "versions": {"mesh": "0.1", "solver": "0.2", "post": "0.3"},
        },
        "paths": {
            "geometry_root": str(geometry_root),
            "results_root": str(results_root),
        },
        "geometry": geometry,
        "stages": stages or ["mesh", "solve"],
        "meshing": {},
        "solver": {},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_paths_and_versioned_result_tree(self) -> None:
        path = write_config(self.tmp_path)
        (self.tmp_path / "Geometry" / "model.pmdb").touch()
        config = load_config(path)
        artifacts = RunArtifacts.from_config(config)

        self.assertEqual(config.run_name, "Nozzle_simulation1.1-0.1-0.2-0.3")
        self.assertEqual(
            artifacts.run_root,
            self.tmp_path
            / "Results"
            / "Nozzle_simulations"
            / "Nozzle_simulation1.1-0.1-0.2-0.3",
        )
        self.assertTrue(artifacts.mesh.name.endswith(".msh.h5"))
        validate_inputs(config, system="Linux")

    def test_dsco_is_rejected_for_linux_meshing(self) -> None:
        path = write_config(self.tmp_path, geometry="model.dsco")
        (self.tmp_path / "Geometry" / "model.dsco").touch()
        config = load_config(path)

        with self.assertRaisesRegex(ConfigError, "not supported"):
            validate_inputs(config, system="Linux")

    def test_geometry_is_not_required_when_mesh_stage_is_not_selected(self) -> None:
        config = load_config(write_config(self.tmp_path, stages=["solve"]))
        validate_inputs(config, system="Linux", stages=["solve"])

    def test_stage_order_is_enforced(self) -> None:
        path = write_config(self.tmp_path, stages=["solve", "mesh"])
        with self.assertRaisesRegex(ConfigError, "order"):
            load_config(path)


if __name__ == "__main__":
    unittest.main()
