from __future__ import annotations

import json
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from kiss_cli import catalog, ki_updates, settings


class KiUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.home = self.root / "updates"
        self.base.mkdir()
        self.env = mock.patch.dict(
            ki_updates.os.environ,
            {"GEOFORGE_KI_UPDATE_HOME": str(self.home)}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    @staticmethod
    def _dag(name: str) -> str:
        return (
            "template_version: '3.5'\n"
            "identity:\n"
            f"  model_id: {name}\n"
            "  repo_url: https://example.org/model\n"
            "boundary: {}\ninputs: {}\noutputs: {}\nstates: {}\n"
            "processes:\n"
            f"  nodes: [{{id: {name.lower()}_run}}]\n"
            "  internal_edges: []\n"
            "influence: {}\nsafety: {}\n"
        )

    def _write_ki(self, library: Path, name: str, skill: str) -> None:
        model = library / "models" / name
        model.mkdir(parents=True, exist_ok=True)
        (model / "SKILL.md").write_text(skill, encoding="utf-8")
        (model / "preflight_check.py").write_text(
            "print('PREFLIGHT_REPORT={\\\"ok\\\": true}')\n", encoding="utf-8")
        (model / "dag.yaml").write_text(self._dag(name), encoding="utf-8")
        manifests = library / "kiss" / "manifests"
        manifests.mkdir(parents=True, exist_ok=True)
        (manifests / f"{name}.yaml").write_text(
            "verified: unverified\n", encoding="utf-8")

    def _archive(self, packages: dict[str, str], *, unsafe_link: bool = False,
                 extra: dict[str, str] | None = None) -> Path:
        path = self.root / "update.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for rel, text in (extra or {}).items():
                archive.writestr(f"repo-mac-version/{rel}", text)
            for name, skill in packages.items():
                prefix = f"repo-mac-version/models/{name}"
                archive.writestr(f"{prefix}/SKILL.md", skill)
                archive.writestr(
                    f"{prefix}/preflight_check.py",
                    "print('PREFLIGHT_REPORT={\\\"ok\\\": true}')\n")
                archive.writestr(f"{prefix}/dag.yaml", self._dag(name))
                archive.writestr(
                    f"repo-mac-version/kiss/manifests/{name}.yaml",
                    "verified: unverified\n")
            if unsafe_link:
                info = zipfile.ZipInfo(
                    "repo-mac-version/models/Demo/tools/private-tool")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "/Users/author/private-tool")
        return path

    def test_valid_snapshot_activates_and_reports_package_changes(self):
        self._write_ki(self.base, "Demo", "old instructions")
        archive = self._archive({"Demo": "new instructions", "NewModel": "new KI"})
        activated: list[Path] = []
        manager = ki_updates.UpdateManager(
            self.base, activated.append, branch="mac-version")

        def download(destination: Path) -> None:
            shutil.copyfile(archive, destination)

        with mock.patch.object(
                manager, "_remote_revision",
                return_value=("a" * 16 + "-" + "b" * 16, "a" * 40, "b" * 40)), \
             mock.patch.object(manager, "_download", side_effect=download):
            self.assertTrue(manager.start())
            report = manager.wait(10)

        self.assertEqual(report["state"], "updated")
        self.assertEqual(report["added"], ["NewModel"])
        self.assertEqual(report["updated"], ["Demo"])
        self.assertEqual(len(activated), 1)
        self.assertEqual(
            (activated[0] / "models" / "Demo" / "SKILL.md").read_text(),
            "new instructions")
        self.assertEqual(ki_updates.active_library_root(), activated[0])
        self.assertTrue(any(
            "SKILL.md" in row["updated_files"] for row in report["changes"]
            if row["name"] == "Demo"))

    def test_unsafe_snapshot_is_rejected_and_current_library_is_kept(self):
        self._write_ki(self.base, "Demo", "safe current instructions")
        archive = self._archive({"Demo": "remote"}, unsafe_link=True)
        activated: list[Path] = []
        manager = ki_updates.UpdateManager(
            self.base, activated.append, branch="mac-version")

        with mock.patch.object(
                manager, "_remote_revision",
                return_value=("c" * 16 + "-" + "d" * 16, "c" * 40, "d" * 40)), \
             mock.patch.object(
                manager, "_download",
                side_effect=lambda destination: shutil.copyfile(archive, destination)):
            manager.start()
            report = manager.wait(10)

        self.assertEqual(report["state"], "error")
        self.assertIn("absolute symbolic link", report["error"])
        self.assertEqual(activated, [])
        self.assertIsNone(ki_updates.active_library_root())
        self.assertEqual(
            (self.base / "models" / "Demo" / "SKILL.md").read_text(),
            "safe current instructions")

    def _on_platform(self, platform: str) -> None:
        # The guard and catalog.KI both ask this helper, so patching both runs
        # each platform's behaviour on any host.
        for module in (ki_updates, catalog):
            patcher = mock.patch.object(
                module, "installation_platform", return_value=platform)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _platform_files(self) -> dict[str, str]:
        platform = ki_updates.installation_platform()
        if not platform:
            self.skipTest("no installation platform for this OS")
        return {
            f"models/Demo/docs/install.{platform}.md": "Install Demo on this OS.\n",
            f"models/Demo/kiss.{platform}.yaml": "verified: unverified\n",
        }

    def _bundle_platform_files(self) -> dict[str, str]:
        files = self._platform_files()
        for rel, text in files.items():
            (self.base / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.base / rel).write_text(text, encoding="utf-8")
        return files

    def _run_update(self, archive: Path, activated: list[Path], revision: str):
        manager = ki_updates.UpdateManager(
            self.base, activated.append, branch="main")
        with mock.patch.object(
                manager, "_remote_revision",
                return_value=(revision, "a" * 40, "b" * 40)), \
             mock.patch.object(
                manager, "_download",
                side_effect=lambda destination: shutil.copyfile(archive, destination)
             ) as download:
            manager.start()
            return manager.wait(10), download

    def test_snapshot_dropping_platform_install_guidance_is_not_activated(self):
        # The canonical branch carries no Windows install notes or recipes; the
        # bundled Windows library does. Activating it would silently delete
        # them, so the updater must keep the current library and say why.
        self._on_platform("windows")
        self._write_ki(self.base, "Demo", "current")
        self._bundle_platform_files()
        archive = self._archive({"Demo": "remote"})
        activated: list[Path] = []
        revision = "7" * 16 + "-" + "8" * 16

        report, _download = self._run_update(archive, activated, revision)

        # A deliberate refusal, not a failure: the window must not report it
        # as a network or validation error.
        self.assertEqual(report["state"], "kept")
        self.assertEqual(activated, [])
        self.assertIsNone(ki_updates.active_library_root())
        self.assertFalse((self.home / "snapshots" / revision).exists())
        self.assertIn("Demo: docs/install.windows.md", report["refused"]["lost"])
        self.assertIn("Demo: windows install recipe", report["refused"]["lost"])
        self.assertEqual(report["refused"]["revision"], revision)
        self.assertIn("install", report["summary"])
        self.assertIn("kept the current KI library because", report["summary"])
        self.assertIn("Windows installation guidance", report["summary"])
        self.assertIn("docs/install.windows.md", report["error"])
        self.assertEqual(
            (self.base / "models" / "Demo" / "SKILL.md").read_text(), "current")
        saved = json.loads(
            (self.home / "last-report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "kept")

        # The same refused revision is not downloaded again on every launch.
        again, download = self._run_update(archive, activated, revision)
        download.assert_not_called()
        self.assertEqual(again["state"], "kept")
        self.assertEqual(again["refused"]["revision"], revision)
        self.assertEqual(again["summary"], report["summary"])
        self.assertEqual(activated, [])

    def _assert_activates_without_guidance(self, platform: str) -> None:
        self._on_platform(platform)
        self._write_ki(self.base, "Demo", "current")
        self._bundle_platform_files()
        archive = self._archive({"Demo": "remote"})
        activated: list[Path] = []

        report, download = self._run_update(
            archive, activated, "5" * 16 + "-" + "6" * 16)

        download.assert_called_once()
        self.assertEqual(report["state"], "updated")
        self.assertEqual(report["updated"], ["Demo"])
        self.assertIsNone(report.get("refused"))
        self.assertEqual(len(activated), 1)
        self.assertEqual(ki_updates.active_library_root(), activated[0])
        # The bundled library would lose its notes here; only Windows refuses
        # that, so a mac/Linux reference still selects the snapshot.
        self.assertEqual(
            ki_updates.active_library_root(self.base), activated[0])

    def test_macos_still_activates_snapshot_without_its_install_guidance(self):
        self._assert_activates_without_guidance("macos")

    def test_linux_still_activates_snapshot_without_its_install_guidance(self):
        self._assert_activates_without_guidance("linux")

    def test_snapshot_keeping_platform_install_guidance_is_activated(self):
        self._on_platform("windows")
        self._write_ki(self.base, "Demo", "current")
        platform_files = self._bundle_platform_files()
        archive = self._archive({"Demo": "remote"}, extra=platform_files)
        activated: list[Path] = []

        report, _download = self._run_update(
            archive, activated, "9" * 16 + "-" + "a" * 16)

        self.assertEqual(report["state"], "updated")
        self.assertEqual(report["updated"], ["Demo"])
        self.assertIsNone(report.get("refused"))
        self.assertEqual(len(activated), 1)
        self.assertEqual(ki_updates.active_library_root(), activated[0])

    def _snapshot_without_bundled_guidance(self) -> Path:
        revision = "b" * 16 + "-" + "c" * 16
        snapshot = self.home / "snapshots" / revision
        self._write_ki(snapshot, "Demo", "remote")
        self._write_ki(self.base, "Demo", "bundled")
        self._bundle_platform_files()
        (self.home / "state.json").write_text(json.dumps({
            "active_snapshot": revision, "revision": revision,
        }), encoding="utf-8")
        return snapshot.resolve()

    def test_active_snapshot_missing_bundled_guidance_is_not_used(self):
        # A snapshot activated by an older updater may already lack this
        # platform's notes; given the bundled library it must be ignored.
        self._on_platform("windows")
        snapshot = self._snapshot_without_bundled_guidance()
        self.assertEqual(ki_updates.active_library_root(), snapshot)
        self.assertIsNone(ki_updates.active_library_root(self.base))

    def test_active_snapshot_missing_guidance_is_still_used_on_macos_and_linux(self):
        for platform in ("macos", "linux"):
            with self.subTest(platform=platform), \
                 mock.patch.object(ki_updates, "installation_platform",
                                   return_value=platform), \
                 mock.patch.object(catalog, "installation_platform",
                                   return_value=platform):
                snapshot = self._snapshot_without_bundled_guidance()
                self.assertEqual(ki_updates.active_library_root(), snapshot)
                self.assertEqual(
                    ki_updates.active_library_root(self.base), snapshot)

    def test_existing_revision_skips_archive_download(self):
        revision = "e" * 16 + "-" + "f" * 16
        snapshot = self.home / "snapshots" / revision
        self._write_ki(snapshot, "Demo", "validated")
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "state.json").write_text(json.dumps({
            "active_snapshot": revision,
            "revision": revision,
            "package_count": 1,
        }), encoding="utf-8")
        manager = ki_updates.UpdateManager(
            snapshot, lambda _path: None, branch="mac-version")
        with mock.patch.object(
                manager, "_remote_revision",
                return_value=(revision, "e" * 40, "f" * 40)), \
             mock.patch.object(manager, "_download") as download:
            manager.start()
            report = manager.wait(10)
        self.assertEqual(report["state"], "up_to_date")
        download.assert_not_called()

    def test_remote_revision_pins_archive_to_exact_commit(self):
        manager = ki_updates.UpdateManager(
            self.base, lambda _path: None, branch="mac-version")
        commit_sha = "1" * 40
        tree_sha = "2" * 40
        models_sha = "3" * 40
        kiss_sha = "4" * 40
        manifests_sha = "5" * 40
        replies = [
            {"sha": commit_sha, "commit": {"tree": {"sha": tree_sha}}},
            {"tree": [{"path": "models", "sha": models_sha},
                      {"path": "kiss", "sha": kiss_sha}]},
            {"tree": [{"path": "manifests", "sha": manifests_sha}]},
        ]
        with mock.patch.object(manager, "_request_json", side_effect=replies) as request:
            revision, got_models, got_manifests = manager._remote_revision()
        self.assertEqual(revision, f"{'3' * 16}-{'5' * 16}")
        self.assertEqual((got_models, got_manifests), (models_sha, manifests_sha))
        self.assertEqual(manager._archive_ref, commit_sha)
        self.assertEqual(manager._source_commit, commit_sha)
        self.assertIn(f"/commits/{manager.branch}", request.call_args_list[0].args[0])

    def test_updater_uses_dedicated_github_proxy_route(self):
        manager = ki_updates.UpdateManager(
            self.base, lambda _path: None, branch="mac-version")
        opener = mock.Mock()
        response = object()
        opener.open.return_value = response
        request = ki_updates.urllib.request.Request("https://api.github.com/test")
        with mock.patch.object(
                settings, "proxy_url_for",
                return_value="http://127.0.0.1:7897") as route, \
             mock.patch.object(
                 ki_updates.urllib.request, "build_opener",
                 return_value=opener) as build:
            self.assertIs(manager._open(request, timeout=12), response)
        route.assert_called_with(settings.GITHUB_PROXY_TARGET)
        proxy_handler = build.call_args.args[0]
        self.assertEqual(proxy_handler.proxies["https"], "http://127.0.0.1:7897")
        opener.open.assert_called_once_with(request, timeout=12)

    def test_ki_updates_use_canonical_main_unless_explicitly_overridden(self):
        with mock.patch.dict(
                ki_updates.os.environ,
                {"GEOFORGE_KI_UPDATE_BRANCH": ""}, clear=False):
            self.assertEqual(ki_updates.branch_for_platform(), "main")
        with mock.patch.dict(
                ki_updates.os.environ,
                {"GEOFORGE_KI_UPDATE_BRANCH": "staging-kis"}, clear=False):
            self.assertEqual(ki_updates.branch_for_platform(), "staging-kis")

    def test_saved_platform_report_is_normalized_to_canonical_main(self):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "last-report.json").write_text(json.dumps({
            "state": "checking", "branch": "windows-version",
        }), encoding="utf-8")
        manager = ki_updates.UpdateManager(self.base, lambda _path: None)
        self.assertEqual(manager.status()["branch"], "main")
        self.assertEqual(manager.status()["state"], "idle")

    def test_frontend_explains_scope_and_desktop_starts_updates(self):
        package = Path(__file__).parents[1] / "kiss_cli"
        app = (package / "app.py").read_text(encoding="utf-8")
        gui = (package / "gui.py").read_text(encoding="utf-8")
        chat = (package / "web" / "app.html").read_text(encoding="utf-8")
        library = (package / "web" / "library.html").read_text(encoding="utf-8")
        self.assertIn("auto_update=True", app)
        self.assertIn('route == "/api/ki-updates"', gui)
        self.assertIn('route == "/api/ki-updates/check"', gui)
        self.assertIn("does not change chat projects", library)
        self.assertIn("ki-update-toast", chat)
        self.assertIn("network:github", chat)
        self.assertIn("network:github", library)
        self.assertIn("Network settings", library)


WEB = Path(__file__).parents[1] / "kiss_cli" / "web"
NODE = shutil.which("node")

# Runs the shipped update-notice JavaScript against stub elements.
NOTICE_RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(process.argv[1],'utf8'),kind=process.argv[2];
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map(),language=input.zh?'zh-CN':'en';
function element(selector){
  if(!elements.has(selector)){
    const node={textContent:'',innerHTML:'',href:'',disabled:false,open:false};
    node.classList={add(name){if(name==='open')node.open=true;},remove(name){if(name==='open')node.open=false;}};
    elements.set(selector,node);
  }
  return elements.get(selector);
}
const context={console,$:element,CUR:null,MODELS:null,STATUS:null,KIUPDATE:input.report,
  drawModelLabel(){},setTimeout(){return 1;},clearTimeout(){},
  window:{GeoForgeI18n:{language}},GeoForgeI18n:{language},
  fetch:async url=>({json:async()=>url==='/api/ki-updates'?input.report:{}})};
vm.createContext(context);
function shipped(start,end){
  const a=page.indexOf(start),b=page.indexOf(end,a);
  if(a<0||b<0)throw new Error('Missing shipped JavaScript segment: '+start);
  vm.runInContext(page.slice(a,b),context);
}
(async()=>{
  if(kind==='app'){
    shipped('const chineseUI=','\n');
    shipped('let KI_UPDATE_REVISION=','\n');
    shipped('async function watchKiUpdates(){','\n');
    await context.watchKiUpdates();
  }else{
    shipped('function esc(s){','\n');
    shipped('function safeUrl(s){','async function loadKiUpdate(');
    context.drawKiUpdate();
  }
  process.stdout.write(JSON.stringify(Object.fromEntries([...elements.entries()].map(
    ([key,node])=>[key,{text:node.textContent,html:node.innerHTML,open:node.open}]))));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@unittest.skipIf(NODE is None, "Node is required")
class KiUpdateNoticeTests(unittest.TestCase):
    KEPT = {
        "state": "kept", "branch": "main",
        "summary": ("GeoForge kept the current KI library because the repository "
                    "version would remove Windows installation guidance."),
        "error": ("The main snapshot lacks 2 Windows installation notes or recipes "
                  "that the current library ships (Demo: docs/install.windows.md, "
                  "Demo: windows install recipe), so it was not activated."),
        "refused": {"revision": "7" * 16 + "-" + "8" * 16, "reference": "x",
                    "lost": ["Demo: docs/install.windows.md",
                             "Demo: windows install recipe"]},
        "added": [], "updated": [], "removed": [], "changes": [], "warning_count": 0,
    }
    FAILED = {"state": "error", "branch": "main", "error": "timed out",
              "summary": "Could not update the KI library. GeoForge kept the last "
                         "validated version."}

    def _render(self, page: str, report: dict, *, zh: bool = False) -> dict:
        # Node always writes UTF-8; the locale default (GBK on Chinese Windows)
        # cannot decode it.
        result = subprocess.run(
            [NODE, "-e", NOTICE_RUNNER, str(WEB / f"{page}.html"), page],
            input=json.dumps({"report": report, "zh": zh}), capture_output=True,
            text=True, encoding="utf-8", check=True, timeout=10)
        return json.loads(result.stdout)

    def test_chat_toast_shows_a_kept_library_as_a_notice_not_a_failure(self):
        en = self._render("app", self.KEPT)
        zh = self._render("app", self.KEPT, zh=True)
        self.assertTrue(en["#ki-update-toast"]["open"])
        self.assertEqual(en["#ki-update-title"]["text"], "Current KI library kept")
        self.assertEqual(en["#ki-update-message"]["text"], self.KEPT["summary"])
        self.assertTrue(zh["#ki-update-toast"]["open"])
        self.assertEqual(zh["#ki-update-title"]["text"], "已保留当前 KI 库")
        self.assertIn("保留了当前 KI 库", zh["#ki-update-message"]["text"])
        self.assertIn("安装说明", zh["#ki-update-message"]["text"])
        for view in (en, zh):
            self.assertNotIn("network", view["#ki-update-message"]["text"])
            self.assertNotIn("网络", view["#ki-update-message"]["text"])

        # A real failure keeps its existing wording.
        failed = self._render("app", self.FAILED)
        self.assertEqual(failed["#ki-update-title"]["text"], "KI update not completed")
        self.assertIn("network or validation issue", failed["#ki-update-message"]["text"])

    def test_library_report_shows_why_the_library_was_kept(self):
        en = self._render("library", self.KEPT)
        zh = self._render("library", self.KEPT, zh=True)
        self.assertEqual(en["#kiupdatelabel"]["text"], "Library kept")
        self.assertIn(self.KEPT["summary"], en["#updatesummary"]["html"])
        self.assertIn("Current library kept safely", en["#updatedetails"]["html"])
        self.assertIn("docs/install.windows.md", en["#updatedetails"]["html"])
        self.assertEqual(zh["#kiupdatelabel"]["text"], "已保留当前库")
        self.assertIn("保留了当前 KI 库", zh["#updatesummary"]["html"])
        self.assertNotIn("未完成", zh["#updatesummary"]["html"])

        failed = self._render("library", self.FAILED)
        self.assertEqual(failed["#kiupdatelabel"]["text"], "Update issue")
