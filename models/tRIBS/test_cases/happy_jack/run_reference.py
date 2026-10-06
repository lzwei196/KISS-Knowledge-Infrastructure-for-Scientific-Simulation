#!/usr/bin/env python3
"""Run the official tRIBS Happy Jack benchmark (Zenodo 10909507) and check it the official way.

Foundation case for the tRIBS KI. The benchmark data (237 MB: data/, src/in_files/happy_jack.in,
results/reference.zip) is NOT in git: it lives in the versioned Netdisk pack tRIBS/happy_jack_v1,
listed file by file (bytes + sha256) in manifest.json["pack"]["files"].

Pack lookup: --pack-dir -> $TRIBS_PACK_DIR -> server copy -> cache dir
($KISS_PACK_CACHE or ~/.cache/kiss_packs)/tRIBS/happy_jack_v1 -> automatic download from the
Baidu share link in manifest.json into that cache dir. Every file is checked (bytes + sha256)
before the run; any problem -> exit 3 "MISSING/BAD DATA ... NOT run."
--no-server-pack (or KISS_NO_SERVER_PACK=1) skips the server copy; --no-download turns
the download off.

Run: data/ and src/ are copied to a fresh temp dir, the empty results/test/ folder is made
(OUTFILENAME in happy_jack.in), and tRIBS runs there through the KI tool tools/run_tribs.py
with the official happy_jack.in unchanged.
Checks: (a) the 9 official black-box tests of the tRIBS repo
(testing/black_box/happy_jack_pytest/test_happy_jack.py, copied unchanged into inputs/), fed
exactly like the official conftest.py does but without its own m.run() (the KI tool already
ran the model); (b) numbers from expected.json (own runs, repeat bit-identical; precip total
also equals the official reference output).

Exit 0 PASS, 2 checks failed, 3 engine/dependency or data missing/bad.
Binary lookup: --tribs-bin -> $TRIBS_BIN -> `which tRIBS` -> server default.
"""
import argparse, contextlib, io, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAN = json.loads((HERE / "manifest.json").read_text())
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_tribs.py"
OFFICIAL_TESTS = HERE / "inputs" / "happy_jack_pytest"
_DEF_BIN = "/mnt/disk1/Hydrocraft_server/models/tRIBS/source/repo/build/tRIBS"
INFILE = "src/in_files/happy_jack.in"

# ---------------------------------------------------------------------------
# Data pack: find it, or download it from the Baidu Netdisk share link, then
# check EVERY file (bytes + sha256) against manifest.json before any run.
# Same block in every KISS case whose data lives in a Netdisk pack.
# ---------------------------------------------------------------------------
import hashlib, http.cookiejar as _cj, json as _json, os as _os, sys as _sys, time as _time
import urllib.parse as _up, urllib.request as _ur
from pathlib import Path as _P

_UA_WEB = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120 Safari/537.36")
_UA_DL = "pan.baidu.com"   # Baidu CDN refuses some client UAs (error 31326)


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def file_ok(root, rel, meta):
    p = _P(root) / rel
    return p.is_file() and p.stat().st_size == meta["bytes"] and _sha256(p) == meta["sha256"]


def verify_pack(root, files):
    """Return list of problems ([] = every file present with right bytes + sha256)."""
    bad = []
    for rel, meta in files.items():
        p = _P(root) / rel
        if not p.is_file():
            bad.append(f"missing {rel}")
        elif p.stat().st_size != meta["bytes"]:
            bad.append(f"size {rel}: {p.stat().st_size} != {meta['bytes']}")
        elif _sha256(p) != meta["sha256"]:
            bad.append(f"sha256 {rel}")
    return bad


def _baidu_cookies():
    """BDUSS + STOKEN of a logged-in Baidu account (needed to download a share).
    1) $KISS_BAIDU_COOKIES = "BDUSS=...; STOKEN=..."   2) the BaiduPCS-Py account store."""
    env = _os.environ.get("KISS_BAIDU_COOKIES", "").strip()
    if env:
        return env
    try:
        import warnings
        warnings.filterwarnings("ignore")
        from baidupcs_py.app.account import AccountManager
        from baidupcs_py.commands.env import ACCOUNT_DATA_PATH
        ck = AccountManager.load_data(ACCOUNT_DATA_PATH).who().pcsapi()._baidupcs.cookies
        if ck.get("BDUSS") and ck.get("STOKEN"):
            return f"BDUSS={ck['BDUSS']}; STOKEN={ck['STOKEN']}"
    except Exception:
        pass
    return ""


class _Share:
    """Minimal Baidu share-link reader: verify code -> list tree -> per-file dlink."""

    def __init__(self, url, pwd, cookies):
        # Baidu is a domestic service: go DIRECT, never through an http(s)_proxy.
        # A cookie jar keeps the cookies Baidu sets during verify (needed by sharedownload).
        self.jar = _cj.CookieJar()
        for part in cookies.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                self.jar.set_cookie(_cj.Cookie(0, k, v, None, False, ".baidu.com", True, True, "/",
                                               True, True, None, False, None, None, {}))
        self.op = _ur.build_opener(_ur.ProxyHandler({}), _ur.HTTPCookieProcessor(self.jar))
        self.surl = _up.urlparse(url).path.rstrip("/").split("/")[-1]   # "1xxxx"
        self.pwd = pwd
        self._refresh()
        root = self._list(None)
        self.share_id, self.uk = root["share_id"], root["uk"]
        self.root_items = root["list"]

    def _refresh(self):
        """(Re)check the share code and get a fresh sign/timestamp (Baidu's expire after ~10 min)."""
        v = self._json("POST", "https://pan.baidu.com/share/verify",
                       {"surl": self.surl[1:], "t": str(int(_time.time() * 1000)),
                        "channel": "chunlei", "web": "1", "clienttype": "0"},
                       {"pwd": self.pwd, "vcode": "", "vcode_str": ""})
        if v.get("errno") != 0:
            raise RuntimeError(f"share verify failed: {v}")
        self.randsk = v["randsk"]
        self.jar.set_cookie(_cj.Cookie(0, "BDCLND", self.randsk, None, False, ".baidu.com", True, True,
                                       "/", True, True, None, False, None, None, {}))
        t = self._json("GET", "https://pan.baidu.com/share/tplconfig",
                       {"surl": self.surl, "fields": "sign,timestamp", "view_mode": "1",
                        "channel": "chunlei", "web": "1", "app_id": "250528", "clienttype": "0"})
        if t.get("errno") != 0:
            raise RuntimeError(f"share tplconfig failed (login cookies ok?): {t}")
        self.sign, self.ts = t["data"]["sign"], t["data"]["timestamp"]
        self.t_sign = _time.time()

    def _json(self, method, url, params, data=None, referer=None):
        q = url + "?" + _up.urlencode(params)
        body = _up.urlencode(data).encode() if data is not None else None
        req = _ur.Request(q, data=body, method=method, headers={
            "User-Agent": _UA_WEB,
            "Referer": referer or "https://pan.baidu.com/s/" + self.surl})
        with self.op.open(req, timeout=60) as r:
            return _json.loads(r.read().decode())

    def _list(self, d, page=1):
        p = {"shorturl": self.surl[1:], "page": str(page), "num": "100", "web": "1",
             "channel": "chunlei", "clienttype": "0", "order": "name"}
        if d is None:
            p["root"] = "1"
        else:
            p["dir"] = d
        r = self._json("GET", "https://pan.baidu.com/share/list", p)
        if r.get("errno") != 0:
            raise RuntimeError(f"share list failed for {d}: {r}")
        return r

    def walk(self, remote_root):
        """{relative path: (fs_id, size)} for every file under the shared folder."""
        out, todo = {}, [i["path"] for i in self.root_items if str(i["isdir"]) == "1"]
        for i in self.root_items:
            if str(i["isdir"]) != "1":
                out[_os.path.relpath(i["path"], remote_root)] = (int(i["fs_id"]), int(i["size"]))
        while todo:
            d, page = todo.pop(), 1
            while True:
                items = self._list(d, page).get("list", [])
                for i in items:
                    if str(i["isdir"]) == "1":
                        todo.append(i["path"])
                    else:
                        out[_os.path.relpath(i["path"], remote_root)] = (int(i["fs_id"]), int(i["size"]))
                if len(items) < 100:
                    break
                page += 1
        return out

    def dlinks(self, fs_ids):
        if _time.time() - self.t_sign > 300:
            self._refresh()
        for attempt in range(5):
            r = self._json("POST", "https://pan.baidu.com/api/sharedownload",
                           {"sign": self.sign, "timestamp": self.ts, "channel": "chunlei",
                            "web": "1", "app_id": "250528", "clienttype": "0"},
                           {"encrypt": "0", "extra": _json.dumps({"sekey": _up.unquote(self.randsk)}),
                            "fid_list": _json.dumps(fs_ids), "primaryid": str(self.share_id),
                            "uk": str(self.uk), "product": "share", "type": "nolimit"})
            # 112 = sign expired; -20 = Baidu wants a captcha after many quick requests.
            # Both clear after a pause + fresh verify/sign: back off and ask again.
            if r.get("errno") in (112, -20) and attempt < 4:
                _time.sleep(0 if r.get("errno") == 112 else 30 * (attempt + 1))
                self._refresh()
                continue
            break
        if r.get("errno") != 0:
            raise RuntimeError(f"sharedownload failed: {r}")
        if not isinstance(r.get("list"), list):
            return {}   # Baidu gives no plain link (seen for files > ~50 MB): caller uses fallback
        return {int(i["fs_id"]): i["dlink"] for i in r["list"]}

    def transfer(self, fs_id, remote_dir):
        """Save one shared file into the logged-in account's own netdisk (remote_dir)."""
        t = self._json("GET", "https://pan.baidu.com/api/gettemplatevariable",
                       {"fields": '["bdstoken"]', "channel": "chunlei", "web": "1", "clienttype": "0"})
        tok = t["result"]["bdstoken"]
        self._json("POST", "https://pan.baidu.com/api/create",
                   {"a": "commit", "bdstoken": tok, "channel": "chunlei", "web": "1", "clienttype": "0"},
                   {"path": remote_dir, "isdir": "1", "block_list": "[]"})
        r = self._json("POST", "https://pan.baidu.com/share/transfer",
                       {"shareid": str(self.share_id), "from": str(self.uk), "bdstoken": tok,
                        "channel": "chunlei", "web": "1", "clienttype": "0"},
                       {"fsidlist": _json.dumps([fs_id]), "path": remote_dir})
        return r

    def fetch(self, dlink, dest):
        req = _ur.Request(dlink, headers={"User-Agent": _UA_DL})
        tmp = _P(str(dest) + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with self.op.open(req, timeout=120) as r, open(tmp, "wb") as fo:
            for b in iter(lambda: r.read(1 << 20), b""):
                fo.write(b)
        tmp.replace(dest)


def _pcs_bin():
    import shutil as _sh
    for c in (_os.environ.get("BAIDUPCS_BIN"), _sh.which("BaiduPCS-Py"),
              "/mnt/disk1/Hydrocraft_server/python_env/bin/BaiduPCS-Py"):
        if c and _os.path.isfile(c) and _os.access(c, _os.X_OK):
            return c
    return None


def _pcs(args, timeout=3600):
    import subprocess as _sp
    env = {k: v for k, v in _os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}   # Baidu = direct
    return _sp.run([_pcs_bin()] + args, env=env, capture_output=True, text=True, timeout=timeout)


def _pcs_get(remote_file, dest):
    """Download one file of the logged-in account's own netdisk with BaiduPCS-Py."""
    import shutil as _sh, tempfile as _tf
    tmpd = _P(_tf.mkdtemp(prefix="kiss_pcs_", dir=str(_P(dest).parent)))
    try:
        p = _pcs(["download", remote_file, "-o", str(tmpd)])
        got = [q for q in tmpd.rglob(_P(remote_file).name) if q.is_file()]
        if not got:
            raise RuntimeError(f"BaiduPCS-Py download gave no file: {(p.stdout + p.stderr)[-300:]}")
        _sh.move(str(got[0]), str(dest))
    finally:
        _sh.rmtree(tmpd, ignore_errors=True)


def _fetch_big(sh, pack, rel, fs_id, size, dest):
    """Fallback for a file the share gives no plain link for (large files).
    (a) the account already holds the pack at remote_path (e.g. the owner) -> download that copy;
    (b) otherwise save the file from the share into /_kiss_pack_tmp/ of the account, download it,
        then delete the temp copy. Both need BaiduPCS-Py logged in to the same account."""
    if not _pcs_bin():
        raise RuntimeError(f"{rel}: Baidu gives no direct share link for this file and BaiduPCS-Py "
                           f"is not installed (needed for large files)")
    own = pack["remote_path"].rstrip("/") + "/" + rel
    try:
        lst = sh._json("GET", "https://pan.baidu.com/api/list",
                       {"dir": str(_P(own).parent), "web": "1", "app_id": "250528", "clienttype": "0",
                        "limit": "10000"}, referer="https://pan.baidu.com/disk/home").get("list", [])
    except Exception:
        lst = []
    if any(i.get("server_filename") == _P(own).name and int(i.get("size", -1)) == size for i in lst):
        print(f"[pack]   {rel}: large file, using the account's own copy at {own}", flush=True)
        _pcs_get(own, dest)
        return
    tmp_remote = f"/_kiss_pack_tmp/{pack['name']}_{int(_time.time())}"
    r = sh.transfer(fs_id, tmp_remote)
    if r.get("errno") != 0:
        raise RuntimeError(f"{rel}: could not save it from the share into your netdisk: {r}")
    try:
        print(f"[pack]   {rel}: large file, saved from the share to {tmp_remote}, downloading", flush=True)
        _pcs_get(tmp_remote + "/" + _P(rel).name, dest)
    finally:
        _pcs(["remove", tmp_remote], timeout=300)


def download_pack(pack, dest):
    """Download every manifest file of the pack from its share link into dest."""
    ck = _baidu_cookies()
    if not ck:
        raise RuntimeError("no Baidu login cookies: set KISS_BAIDU_COOKIES='BDUSS=...; STOKEN=...' "
                           "(from a browser logged in to pan.baidu.com) or log in BaiduPCS-Py")
    t0 = _time.time()
    sh = _Share(pack["share_url"], pack["share_pwd"], ck)
    remote = sh.walk(pack["remote_path"])
    files = pack["files"]
    todo = [rel for rel, m in files.items() if not file_ok(dest, rel, m)]
    lost = [rel for rel in todo if rel not in remote]
    if lost:
        raise RuntimeError(f"{len(lost)} manifest files not in the share, e.g. {lost[:3]}")
    print(f"[pack] downloading {len(todo)} of {len(files)} files from {pack['share_url']} "
          f"-> {dest}", flush=True)
    done_b = 0
    # One file per sharedownload call: Baidu asks for a captcha (errno -20) on multi-file
    # requests once an account has downloaded a lot, while single-file requests still work.
    for k, rel in enumerate(todo, 1):
        fid = remote[rel][0]
        link = sh.dlinks([fid]).get(fid)
        if link is None:   # no plain share link (big file): BaiduPCS-Py fallback
            _fetch_big(sh, pack, rel, fid, files[rel]["bytes"], _P(dest) / rel)
        else:
            for attempt in range(6):
                try:
                    sh.fetch(link, _P(dest) / rel)
                    break
                except Exception as e:
                    if attempt == 5:
                        raise RuntimeError(f"download failed for {rel}: {e}")
                    _time.sleep(5 * (attempt + 1))
                    try:  # a used/expired dlink can give 403: ask for a fresh one
                        link = sh.dlinks([fid]).get(fid, link)
                    except Exception:
                        pass
        done_b += files[rel]["bytes"]
        if k % 20 == 0 or k == len(todo):
            print(f"[pack]   {k}/{len(todo)} files, {done_b / 1e6:.0f} MB, "
                  f"{_time.time() - t0:.0f} s", flush=True)
    print(f"[pack] download finished in {_time.time() - t0:.0f} s", flush=True)


def resolve_pack(pack, ki, pack_dir_arg, cache_arg, no_server, no_download):
    """Lookup: --pack-dir -> $<KI>_PACK_DIR -> server default copy -> cache dir ->
    auto-download into cache dir. Returns a verified pack dir, or exits 3."""
    name = f"{ki}/{pack['name']}"
    explicit = pack_dir_arg or _os.environ.get(f"{ki.upper()}_PACK_DIR")
    no_server = no_server or _os.environ.get("KISS_NO_SERVER_PACK") == "1"
    cache_root = cache_arg or _os.environ.get("KISS_PACK_CACHE") or str(_P.home() / ".cache" / "kiss_packs")
    cache = _P(cache_root) / ki / pack["name"]

    def bad_exit(where, problems):
        print(f"MISSING/BAD DATA: pack {name} at {where}: {len(problems)} problem(s), e.g. "
              f"{problems[:3]}. NOT run.", file=_sys.stderr)
        _sys.exit(3)

    def how_to():
        return (f"Get it from Baidu Netdisk: {pack['share_url']} (code {pack['share_pwd']}), "
                f"folder {pack['remote_path']} ; then pass --pack-dir <folder> "
                f"or set {ki.upper()}_PACK_DIR.")

    if explicit:
        if not _P(explicit).is_dir():
            print(f"MISSING/BAD DATA: pack dir {explicit} does not exist. {how_to()} NOT run.",
                  file=_sys.stderr)
            _sys.exit(3)
        b = verify_pack(explicit, pack["files"])
        if b:
            bad_exit(explicit, b)
        print(f"[pack] using {explicit} (all {len(pack['files'])} files verified)")
        return explicit
    if not no_server and _P(pack["server_default"]).is_dir():
        b = verify_pack(pack["server_default"], pack["files"])
        if b:
            bad_exit(pack["server_default"], b)
        print(f"[pack] using server copy {pack['server_default']} "
              f"(all {len(pack['files'])} files verified)")
        return pack["server_default"]
    if cache.is_dir() and not verify_pack(cache, pack["files"]):
        print(f"[pack] using cache {cache} (all {len(pack['files'])} files verified)")
        return str(cache)
    if no_download:
        print(f"MISSING/BAD DATA: pack {name} not found locally and download is off. "
              f"{how_to()} NOT run.", file=_sys.stderr)
        _sys.exit(3)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        download_pack(pack, cache)
    except Exception as e:
        print(f"MISSING/BAD DATA: could not download pack {name}: {e}. Files already fetched stay "
              f"in {cache} and a re-run resumes. {how_to()} NOT run.", file=_sys.stderr)
        _sys.exit(3)
    b = verify_pack(cache, pack["files"])
    if b:
        bad_exit(cache, b)
    print(f"[pack] downloaded pack verified: all {len(pack['files'])} files match manifest.json")
    return str(cache)
# ---------------------------------------------------------------------------


def find_bin(arg):
    for c in (arg, os.environ.get("TRIBS_BIN"), shutil.which("tRIBS"), _DEF_BIN):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)   # the run starts in a temp dir
    return None


def official_tests(run_dir):
    """Run the official test_happy_jack.py functions on the finished run (cwd = run_dir).
    Setup tuple built exactly like the official conftest.py, minus its m.run()."""
    import re
    sys.dont_write_bytecode = True   # keep the case folder clean (no __pycache__ in inputs/)
    sys.path.insert(0, str(OFFICIAL_TESTS))
    import test_happy_jack as T
    from pytRIBS.classes import Model as model
    from pytRIBS.classes import Results as results
    hj = "."
    input_file = f"{hj}/src/in_files/happy_jack.in"
    m = model()
    m.read_input_file(input_file)
    r = results(input_file)
    r.get_element_results()
    pixel = r.element[0]["pixel"]
    setup = (pixel, f"{hj}/data/HJ_WEATHER_2002-2018_XC_mod.mdf", f"{hj}/data/HJ_PRECIP_2002-2018.mdf",
             m, r, f"{hj}/data/Snotel/bcqc_34.75000_-111.41000.txt")
    order = ["test_match_precip_input_to_output", "test_match_PA_input_to_output",
             "test_match_RH_input_to_output", "test_match_XC_input_to_output",
             "test_match_US_input_to_output", "test_match_TA_input_to_output",
             "test_match_IS_input_to_output", "test_elem_water_balance", "test_model_efficiency"]
    res, vals = {}, {}
    for n in order:  # same order as in the official file (test_model_efficiency re-indexes pixel)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                getattr(T, n)(setup)
            res[n] = "PASS"
        except AssertionError as e:
            res[n] = f"FAIL {e}"
        txt = buf.getvalue()
        m1 = re.search(r"Test metric \(P - Loss - delS\) = ([-0-9.eE+]+)", txt)
        m2 = re.search(r"Kling-Gupta efficiency = ([-0-9.eE+]+)", txt)
        if m1:
            vals["official_water_balance_metric_mm_per_yr"] = float(m1.group(1))
        if m2:
            vals["official_kge_swe_vs_snotel"] = float(m2.group(1))
    return res, vals


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tribs-bin")
    ap.add_argument("--pack-dir", help="local copy of the tRIBS/happy_jack_v1 pack")
    ap.add_argument("--cache-dir", help="where a downloaded pack is kept (default ~/.cache/kiss_packs)")
    ap.add_argument("--no-server-pack", action="store_true", help="skip the server's own copy")
    ap.add_argument("--no-download", action="store_true", help="never download; exit 3 if no pack")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()

    binp = find_bin(a.tribs_bin)
    if not binp:
        print("MISSING DEPENDENCY: tRIBS binary not found (use --tribs-bin or $TRIBS_BIN). NOT run.",
              file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {RUN_TOOL} not found. NOT run.", file=sys.stderr)
        return 3
    try:
        import numpy, pandas  # noqa: F401
        from pytRIBS.classes import Results  # noqa: F401
    except Exception as e:
        print(f"MISSING DEPENDENCY: python packages for the official tests (pytRIBS, numpy, pandas): "
              f"{e}. NOT run.", file=sys.stderr)
        return 3
    import pandas as pd
    import zipfile
    pack = resolve_pack(MAN["pack"], "tRIBS", a.pack_dir, a.cache_dir, a.no_server_pack, a.no_download)

    tmp = Path(tempfile.mkdtemp(prefix="tribs_happy_jack_"))
    cwd0 = os.getcwd()
    try:
        shutil.copytree(Path(pack) / "data", tmp / "data")
        shutil.copytree(Path(pack) / "src", tmp / "src")
        (tmp / "results" / "test").mkdir(parents=True)
        rep = tmp / "run_report.json"
        t0 = time.time()
        p = subprocess.run([sys.executable, str(RUN_TOOL), "--binary", binp, "--input", INFILE,
                            "--work-dir", str(tmp), "--timeout", "1800", "--json-output", str(rep)],
                           cwd=tmp, capture_output=True, text=True)
        el = time.time() - t0
        if not rep.is_file():
            print(p.stdout[-2000:], p.stderr[-2000:], sep="\n")
            print("FAIL: KI run tool wrote no report", file=sys.stderr)
            return 2
        report = json.loads(rep.read_text())
        print(f"[run] KI tool status={report.get('status')} returncode={report.get('returncode')} "
              f"elapsed={el:.0f} s findings={report.get('findings')}")

        got = {"returncode": report.get("returncode"),
               "part9_reached": int("Simulation completed successfully (Part 9 reached)."
                                    in report.get("findings", []))}
        os.chdir(tmp)
        try:
            res, vals = official_tests(tmp)
        except Exception as e:
            print(f"FAIL: official tests could not read the run output: {e}", file=sys.stderr)
            return 2
        finally:
            os.chdir(cwd0)
        for n, s in res.items():
            print(f"  official {n}: {s}")
        got["official_tests_passed"] = sum(1 for s in res.values() if s == "PASS")
        got.update(vals)

        px = pd.read_csv(tmp / "results" / "test" / "hj_test0.pixel", sep=r"\s+")
        got.update({
            "n_pixel_records": len(px),
            "precip_total_mm": float(px["Rain_mm_h"].sum()),
            "et_total_mm": float(px["EvpTtrs_mm_h"].sum()),
            "surface_runoff_total_mm": float(px["Srf_Hour_mm"].sum()),   # hourly total, as the official WB test sums it
            "swe_max_cm": float(px["SnWE_cm"].max()),
            "swe_mean_cm": float(px["SnWE_cm"].mean()),
            "nwt_end_mm": float(px["Nwt_mm"].iloc[-1]),
            "mu_end_mm": float(px["Mu_mm"].iloc[-1]),
        })
        with zipfile.ZipFile(Path(pack) / "results" / "reference.zip") as z:
            with z.open("reference/hj_ref0.pixel") as fh:
                ref = pd.read_csv(fh, sep=r"\s+", usecols=["Rain_mm_h", "SnWE_cm"])
        got["precip_total_minus_official_reference_mm"] = got["precip_total_mm"] - float(ref["Rain_mm_h"].sum())
        n = min(len(ref), len(px))
        corr = float(pd.Series(px["SnWE_cm"].values[:n]).corr(pd.Series(ref["SnWE_cm"].values[:n])))
        print(f"[info] vs official reference.zip (made 2024-03 with an older tRIBS): SWE max "
              f"{got['swe_max_cm']:.2f} vs {ref['SnWE_cm'].max():.2f} cm, SWE correlation {corr:.3f} "
              f"(information only, not a check)")

        fails = []
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            ok = v is not None and abs(v - c["expected"]) <= c["tol"]
            print(f"  {'ok  ' if ok else 'FAIL'} {c['name']}: got {v} expected {c['expected']} tol {c['tol']}")
            if not ok:
                fails.append(c["name"])
        if fails:
            print(f"FAIL: {len(fails)} check(s) failed: {fails}")
            return 2
        print(f"PASS: all 9 official black-box tests pass and all {len(EXP['numeric_checks'])} checks "
              f"match expected.json (tRIBS Happy Jack 2002-06-01 + 143183 h, run {el:.0f} s)")
        return 0
    finally:
        os.chdir(cwd0)
        if a.keep:
            print(f"[run] kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
