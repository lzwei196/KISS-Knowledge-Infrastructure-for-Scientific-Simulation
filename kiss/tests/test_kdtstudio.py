from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from kiss_cli import doctor, kdtstudio
from kiss_cli.catalog import KI


class KdtStudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.data = self.base / "data"
        self.engine = self.base / "engine"
        self.source = self.base / "source"
        self.parent = self.base / "workspaces"
        self.source.mkdir()
        self.parent.mkdir()
        (self.source / "README.md").write_text("A real model source", encoding="utf-8")
        for rel in kdtstudio.REQUIRED_ENGINE_FILES:
            path = self.engine / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {
            "GEOFORGE_KDT_HOME": str(self.data),
            "GEOFORGE_KDT_ENGINE": str(self.engine),
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _create(self, ki_kind="process_model"):
        return kdtstudio.create_job(
            model_name="My Model", domain="hydrology", source_type="local",
            source=str(self.source), parent=str(self.parent),
            provider="cli:codex", llm_model="", ki_kind=ki_kind,
        )

    def test_create_job_is_indexed_and_uses_opaque_id(self):
        created = self._create()
        self.assertRegex(created["id"], r"^[a-f0-9]{12}$")
        root = Path(created["root"])
        self.assertTrue(root.resolve().is_relative_to(self.parent.resolve()))
        self.assertEqual(kdtstudio.job(created["id"])["model_name"], "My Model")
        self.assertEqual(kdtstudio.job(created["id"])["ki_kind"], "process_model")
        path_contract = json.loads((root / "runs" / "desktop-paths.json").read_text())
        self.assertEqual(path_contract["workspace"], str(root))
        self.assertEqual(path_contract["kdt_engine"], str(self.engine.resolve()))
        with self.assertRaises(ValueError):
            kdtstudio.job("../../outside")

    def test_rejects_non_https_git_source(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            kdtstudio.create_job(
                model_name="Unsafe", domain="crop", source_type="git",
                source="file:///etc", parent=str(self.parent),
            )

    def test_rejects_github_file_pages_with_repository_root_hint(self):
        with self.assertRaisesRegex(ValueError, "https://github.com/K-Dense-AI/scientific-agent-skills"):
            kdtstudio.create_job(
                model_name="GIS", domain="GIS", source_type="git",
                source=("https://github.com/K-Dense-AI/scientific-agent-skills/"
                        "blob/main/skills/geomaster/SKILL.md"),
                parent=str(self.parent),
            )

    def test_custom_domain_has_no_hidden_hydrology_prior(self):
        created = kdtstudio.create_job(
            model_name="GIS", domain="GIS / remote sensing", source_type="local",
            source=str(self.source), parent=str(self.parent),
            provider="cli:codex", ki_kind="task_workflow",
        )
        self.assertEqual(created["domain"], "gis_remote_sensing")
        self.assertFalse(created["domain_guided"])
        root = Path(created["root"])
        (root / "probe" / "probe_report.json").write_text(json.dumps({
            "source_root": str(self.source), "primary_language": "Python",
            "build_system": "none", "has_examples": True,
        }), encoding="utf-8")
        (root / "probe" / "io_graph.json").write_text(
            json.dumps({"summary": {}}), encoding="utf-8")
        prompt = kdtstudio.build_prompt(created["id"])
        self.assertIn("NO previous domain protocol", prompt)
        self.assertIn("do not borrow hydrology", prompt)

    def test_provider_can_change_between_build_passes(self):
        created = self._create()
        _root, state = kdtstudio.mark_building(
            created["id"], provider="api:deepseek", llm_model="deepseek-chat")
        self.assertEqual(state["provider"], "api:deepseek")
        self.assertEqual(state["llm_model"], "deepseek-chat")
        reopened = kdtstudio.job(created["id"])
        self.assertEqual(reopened["provider"], "api:deepseek")

    def test_probe_evidence_inventory_and_user_evidence_are_workspace_scoped(self):
        (self.source / "docs").mkdir()
        (self.source / "docs" / "manual.md").write_text(
            "Model paper DOI 10.1234/example.2026", encoding="utf-8")
        (self.source / "examples").mkdir()
        (self.source / "examples" / "case.in").write_text("real case", encoding="utf-8")
        (self.source / "validation").mkdir()
        (self.source / "validation" / "observed.csv").write_text(
            "date,value\n2020-01-01,1\n", encoding="utf-8")
        created = self._create()
        root = Path(created["root"])
        (root / "probe" / "probe_report.json").write_text(json.dumps({
            "source_root": str(self.source), "primary_language": "Fortran",
            "build_system": "make", "has_examples": True,
        }), encoding="utf-8")
        (root / "probe" / "io_graph.json").write_text(
            json.dumps({"summary": {}}), encoding="utf-8")

        evidence = kdtstudio.evidence_inventory(created["id"])
        by_kind = {item["kind"]: item for item in evidence["items"]}
        self.assertEqual(by_kind["official_docs"]["state"], "found")
        self.assertEqual(by_kind["working_example"]["state"], "found")
        self.assertEqual(by_kind["literature"]["state"], "found")
        self.assertEqual(by_kind["validation_data"]["state"], "found")
        self.assertEqual(by_kind["restricted_assets"]["state"], "not_requested")

        paper = self.base / "paper-notes.txt"
        paper.write_text("legally supplied notes", encoding="utf-8")
        updated = kdtstudio.add_evidence(
            created["id"], kind="literature", source_type="local",
            value=str(paper), label="author notes")
        literature = next(item for item in updated["items"] if item["kind"] == "literature")
        copied = root / literature["supplied"][0]["value"]
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_text(), "legally supplied notes")

        updated = kdtstudio.add_evidence(
            created["id"], kind="literature", source_type="link",
            value="10.1234/public-paper")
        literature = next(item for item in updated["items"] if item["kind"] == "literature")
        self.assertTrue(any(row["value"].startswith("https://doi.org/")
                            for row in literature["supplied"]))
        prompt = kdtstudio.build_prompt(created["id"])
        self.assertIn("10 KI deliverable groups", prompt)
        self.assertIn("https://doi.org/10.1234/public-paper", prompt)
        self.assertIn("user-supplied evidence", prompt)

    def test_deliverable_inventory_is_ten_plus_one_for_process_models(self):
        created = self._create()
        root = Path(created["root"])
        candidate = root / "candidate"
        (candidate / "SKILL.md").write_text("skill", encoding="utf-8")
        (candidate / "tools").mkdir()
        (candidate / "tools" / "run.py").write_text("", encoding="utf-8")
        contract = kdtstudio.deliverable_inventory(created["id"])
        self.assertEqual(contract["required"], 10)
        self.assertEqual(contract["present"], 2)
        self.assertEqual(contract["label"], "10 KI deliverable groups + 1 acceptance report")
        self.assertFalse(contract["acceptance_report"])
        (root / "runs" / "ki-acceptance.json").write_text("{}", encoding="utf-8")
        self.assertTrue(kdtstudio.deliverable_inventory(created["id"])["acceptance_report"])

    def test_agent_evidence_request_is_queued_not_claimed_as_found(self):
        created = self._create()
        root = Path(created["root"])
        (root / "probe" / "probe_report.json").write_text(
            json.dumps({"source_root": str(self.source)}), encoding="utf-8")
        inventory = kdtstudio.add_evidence(
            created["id"], kind="literature", source_type="agent",
            value="Resolve public papers on the next pass")
        literature = next(item for item in inventory["items"]
                          if item["kind"] == "literature")
        self.assertEqual(literature["state"], "agent_requested")
        self.assertEqual(literature["supplied"], [])
        self.assertEqual(len(literature["requested"]), 1)

    def test_desktop_prompt_has_no_server_path_and_uses_probe_evidence(self):
        created = self._create()
        root = Path(created["root"])
        (root / "probe" / "probe_report.json").write_text(json.dumps({
            "source_root": str(root / "probe" / "source" / "repo"),
            "primary_language": "Fortran", "build_system": "make",
            "domain": "hydrology", "has_examples": True,
        }), encoding="utf-8")
        (root / "probe" / "io_graph.json").write_text(
            json.dumps({"summary": {"files_scanned": 14}}), encoding="utf-8")
        prompt = kdtstudio.build_prompt(created["id"])
        self.assertIn("GEOFORGE KI STUDIO", prompt)
        self.assertIn(str(root / "candidate"), prompt)
        self.assertIn("Fortran", prompt)
        self.assertNotIn("/mnt/disk1", prompt)
        self.assertNotIn("/media/server", prompt)

    def test_task_workflow_gets_a_task_contract(self):
        created = self._create(ki_kind="task_workflow")
        root = Path(created["root"])
        (root / "probe" / "probe_report.json").write_text(json.dumps({
            "source_root": str(root / "probe" / "source"),
            "primary_language": "Python", "build_system": "none",
            "domain": "hydrology", "has_examples": True,
        }), encoding="utf-8")
        (root / "probe" / "io_graph.json").write_text(
            json.dumps({"summary": {"files_scanned": 2}}), encoding="utf-8")
        prompt = kdtstudio.build_prompt(created["id"])
        self.assertIn("KI type: task_workflow", prompt)
        self.assertIn("TASK WORKFLOW KI", prompt)
        self.assertIn("Do not invent a model binary", prompt)
        self.assertNotIn("Observable outputs need comparison shapes", prompt)

    def test_local_source_root_is_not_mistaken_for_its_only_subfolder(self):
        (self.source / "examples").mkdir()
        (self.source / "examples" / "input.csv").write_text("x\n1\n", encoding="utf-8")
        (self.engine / "auto_dissect.py").write_text(
            "import json, shutil\n"
            "from pathlib import Path\n"
            "class Acquire:\n"
            " @staticmethod\n"
            " def find_source_root(work):\n"
            "  ds=[p for p in Path(work).iterdir() if p.is_dir()]\n"
            "  return str(ds[0] if len(ds)==1 else Path(work))\n"
            "s0_acquire=Acquire()\n"
            "class State:\n"
            " def __init__(self, value): self.state=value\n"
            "def run_pipeline(config):\n"
            " wd=Path(config['work_dir']); source=wd/'source'\n"
            " shutil.copytree(config['source_path'], source, dirs_exist_ok=True)\n"
            " root=s0_acquire.find_source_root(source)\n"
            " (wd/'probe_report.json').write_text(json.dumps({'source_root':root}))\n"
            " (wd/'io_graph.json').write_text(json.dumps({'summary':{}}))\n"
            " stages={'s0_acquire':{'status':'completed','source_root':root},'s1_pipeline_map':{'status':'completed'}}\n"
            " (wd/'stage_log.json').write_text(json.dumps({'stages':stages}))\n"
            " return State({'stages':stages})\n",
            encoding="utf-8",
        )
        created = self._create(ki_kind="task_workflow")
        result = kdtstudio.run_probe(created["id"])
        report = json.loads((Path(result["root"]) / "probe" / "probe_report.json").read_text())
        self.assertEqual(Path(report["source_root"]), Path(result["root"]) / "probe" / "source")
        scaffold = json.loads((Path(result["candidate"]) / "knowledge_infrastructure.yaml").read_text())
        self.assertEqual(scaffold["package"]["kind"], "task_workflow")
        names = [stage["name"] for stage in scaffold["pipeline"]["stages"]]
        self.assertEqual(names, ["Inspect inputs", "Execute task", "Validate outputs"])
        self.assertNotIn("Run the model binary", json.dumps(scaffold))

    def test_gate_uses_safe_copy_and_export_is_digest_bound(self):
        created = self._create(ki_kind="task_workflow")
        root = Path(created["root"])
        candidate = root / "candidate"
        marker = root / "runs" / "untrusted-code-ran"
        (candidate / "SKILL.md").write_text("skill", encoding="utf-8")
        (candidate / "preflight_check.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('bad')\n"
            "print('PREFLIGHT_REPORT={}')\n",
            encoding="utf-8",
        )
        # This fake gate behaves like KDT's important execution seam: it runs
        # the preflight it was given. GeoForge must give it the safe copy, not
        # the untrusted candidate script above.
        (self.engine / "verify_ki_structure.py").write_text(
            "import subprocess, sys\n"
            "from pathlib import Path\n"
            "def verify(root, kind=None):\n"
            " p=Path(root)\n"
            " r=subprocess.run([sys.executable, str(p/'preflight_check.py')], cwd=p, capture_output=True, text=True)\n"
            " return {'ok': 'deferred' in r.stdout, 'failures': [], 'warnings': ['/mnt/disk1/Hydrocraft_server/data/old'], 'info': {'kind': kind}}\n",
            encoding="utf-8",
        )
        accepted = kdtstudio.verify(created["id"])
        self.assertTrue(accepted["ok"])
        self.assertEqual(accepted["info"]["kind"], "task_workflow")
        self.assertNotIn("/mnt/disk1", accepted["warnings"][0])
        self.assertIn("server-only path unavailable", accepted["warnings"][0])
        self.assertFalse(marker.exists(), "candidate preflight must not execute during structure gate")
        self.assertTrue(kdtstudio.job(created["id"])["can_import"])
        archive, blob = kdtstudio.export_zip(created["id"])
        self.assertTrue(archive.is_file())
        with zipfile.ZipFile(archive) as zf:
            self.assertIn("SKILL.md", zf.namelist())
        self.assertEqual(blob, archive.read_bytes())

        (candidate / "SKILL.md").write_text("changed after acceptance", encoding="utf-8")
        self.assertFalse(kdtstudio.job(created["id"])["can_import"])
        with self.assertRaisesRegex(ValueError, "verify the unchanged"):
            kdtstudio.export_zip(created["id"])

    def test_desktop_adapter_keeps_bare_ki_unchanged_and_adds_only_compatibility_fields(self):
        created = self._create()
        root = Path(created["root"])
        candidate = root / "candidate"
        (candidate / "SKILL.md").write_text("# My Model\n", encoding="utf-8")
        (candidate / "preflight_check.py").write_text(
            "print('PREFLIGHT_REPORT={}')\n", encoding="utf-8")
        (candidate / "docs").mkdir()
        (candidate / "docs" / "format_spec.yaml").write_text("formats: {}\n", encoding="utf-8")
        # This represents a valid bare scientific contract whose only missing
        # fields belong to GeoForge's Desktop projection.
        bare_dag = (
            "identity:\n  model_id: My Model\n  repo_url: https://example.org/model\n"
            "boundary: {}\ninputs: {}\noutputs: []\nstates: {}\n"
            "influence: {}\nsafety: {}\n"
        )
        (candidate / "dag.yaml").write_text(bare_dag, encoding="utf-8")
        acceptance = {
            "ok": True,
            "engine_commit": kdtstudio.REVIEWED_COMMIT,
            "digest": kdtstudio.tree_digest(candidate),
            "signature": kdtstudio.tree_signature(candidate),
        }
        (root / "runs" / "ki-acceptance.json").write_text(
            json.dumps(acceptance), encoding="utf-8")

        adaptation = kdtstudio.adapt_for_desktop(created["id"])
        desktop = Path(adaptation["path"])
        self.assertEqual((candidate / "dag.yaml").read_text(), bare_dag)
        projected = (desktop / "dag.yaml").read_text()
        self.assertIn("template_version: '3.5'", projected)
        self.assertIn("processes:", projected)
        self.assertIn("nodes: []", projected)
        self.assertEqual(
            [item["field"] for item in adaptation["changes"]],
            ["template_version", "processes"],
        )
        self.assertTrue((desktop / ".geoforge-adapter.json").is_file())
        blockers = [
            finding for finding in doctor.check_ki(KI(name="My Model", root=desktop))
            if finding.severity == doctor.BLOCK
        ]
        self.assertEqual(blockers, [])

        archive, blob, exported = kdtstudio.export_desktop_zip(created["id"])
        self.assertEqual(exported["source_digest"], acceptance["digest"])
        self.assertEqual(blob, archive.read_bytes())
        with zipfile.ZipFile(archive) as zf:
            self.assertIn(".geoforge-adapter.json", zf.namelist())
            self.assertIn("template_version: '3.5'", zf.read("dag.yaml").decode())

    def test_studio_frontend_and_routes_are_present(self):
        package = Path(__file__).parents[1]
        page = (package / "kiss_cli" / "web" / "studio.html").read_text(encoding="utf-8")
        gui = (package / "kiss_cli" / "gui.py").read_text(encoding="utf-8")
        app = (package / "kiss_cli" / "web" / "app.html").read_text(encoding="utf-8")
        library = (package / "kiss_cli" / "web" / "library.html").read_text(encoding="utf-8")
        self.assertIn("Create a KI for your own model", page)
        self.assertIn("Unknown generated code is not executed here", page)
        self.assertIn('id="customdomain"', page)
        self.assertIn('id="runprovider"', page)
        self.assertIn('id="runllm"', page)
        self.assertIn('id="evidencepanel"', page)
        self.assertIn('id="contractpanel"', page)
        self.assertIn("10 KI deliverable groups", gui + page)
        self.assertIn("No KDT prior protocol exists", page)
        self.assertIn("GitHub file or folder page", page)
        for route in ("/api/kdt/create", "/api/kdt/probe", "/api/kdt/build",
                      "/api/kdt/verify", "/api/kdt/import", "/api/kdt/evidence"):
            self.assertIn(route, gui)
        self.assertIn('href="/studio"', app)
        self.assertIn('location.href="/studio"', library)


if __name__ == "__main__":
    unittest.main()
