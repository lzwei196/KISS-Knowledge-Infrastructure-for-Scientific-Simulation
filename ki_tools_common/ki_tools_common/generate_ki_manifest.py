#!/usr/bin/env python3
"""generate_ki_manifest — PROJECT knowledge_infrastructure.yaml (FILE 5) from what exists.

Same doctrine as the format_spec generator (2026-08-15): a manifest that DESCRIBES the KI must be
derived from the KI, never hand-typed into drift. Sources, all already trusted:
  package     <- dag identity;   pipeline <- stage docs / stage dirs;   tools <- tools/*.py
  inputs/outputs <- dag;         validation <- the models DB's real run records (tier, best skill)
Judgment-free: tier_justification states the measured facts, no adjectives. Backup before overwrite.
"""
import argparse, re, sqlite3, sys, datetime as dt
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent))
from ki_projection_common import (SourceShapeError, entry_name, observability, split_reason_items,
                                  tool_files, read_triplet_entries)
from pathlib import Path
import yaml
DB="KISSPATH_ROOT/hydrocraft.db"

def _inputs(dag, ki):
    out={}
    ins=dag.get("inputs")
    if ins is not None and not isinstance(ins,dict):
        raise RuntimeError(f"{ki}: dag inputs is {type(ins).__name__}, expected mapping")
    for s in ("forcing","parameters","initial_conditions","boundary_conditions"):
        rows=(ins or {}).get(s) or []
        if isinstance(rows,dict) and set(rows)<={"_reason","_note"}:
            out[f"{s}_note"]=rows.get("_reason") or rows.get("_note"); rows=[]
        if rows and not isinstance(rows,list):
            raise RuntimeError(f"{ki}: inputs.{s} is {type(rows).__name__}, expected list")
        rows,_note2=split_reason_items(rows)
        if _note2: out[f"{s}_note"]=_note2
        out[s]=[{"name":e.get("name") or e.get("var"),"unit":e.get("unit")}
                for e in rows if isinstance(e,dict) and (e.get("name") or e.get("var"))]
    return out

def build(ki: Path) -> dict:
    dag=yaml.safe_load((ki/"dag.yaml").read_text()) or {}
    ident=dag.get("identity") or {}
    mid=ident.get("model_id")
    if not mid:
        raise SourceShapeError(f"{ki}: dag identity.model_id missing — refuse to invent one")
    con=sqlite3.connect(f"file:{DB}?mode=ro",uri=True); con.row_factory=sqlite3.Row
    row=con.execute("select * from models where ki_path=?",(str(ki),)).fetchone()
    if row is None:
        row=con.execute("select * from models where id=?",(mid,)).fetchone()
        if row and row["ki_path"] and str(row["ki_path"])!=str(ki):
            raise RuntimeError(f"{ki}: DB row {row['id']!r} found by id points at a DIFFERENT "
                               f"KI ({row['ki_path']}) — refusing to splice models (co-review #1/#9)")
    def _nid(x): return re.sub(r"[-_/ ]+","_",str(x)).lower()
    if row and _nid(row["id"])!=_nid(mid) and str(row["ki_path"])==str(ki):
        raise RuntimeError(f"{ki}: dag says model_id={mid!r} but the DB row for this path is "
                           f"{row['id']!r} — fix the dag identity, do not splice two models "
                           f"(this check exists because EF5's dag claimed to be HYPE)")
    # pipeline: stage docs (sN_*.md) or stage dirs (sN_*/)
    stages=sorted({p.stem for p in (ki/"docs").glob("s[0-9]*_*.md")} |
                  {p.name for p in ki.glob("s[0-9]*_*") if p.is_dir()})
    tools=tool_files(ki)          # ONE counting rule, shared with the gate (kimi #13/#15)
    ntrip=len(read_triplet_entries(ki))
    _o=dag.get("outputs")
    if _o is not None and not isinstance(_o,list):
        raise SourceShapeError(f"{ki}: dag outputs is {type(_o).__name__}, expected list")
    outs=list(_o or [])
    obs=[o for o in outs if observability(o).get("comparable_obs_shapes")]
    val={"tier": (row["validation_tier"] if row else None)}   # DB verbatim; null means the DB says nothing — never synthesized
    facts=[]
    if row:
        for k in ("best_nse","best_kge","best_r"):
            if row[k] is not None: facts.append(f"{k.replace('best_','').upper()}={row[k]:.3f}")
        if row["n_scorecards"]: facts.append(f"{row['n_scorecards']} scorecard(s)")
    val["tier_justification"]=("measured: "+", ".join(facts)) if facts else \
        "no scored run recorded in the models DB at generation time"
    if row:
        _mx={k:row[k] for k in ("best_nse","best_kge","best_r") if row[k] is not None}
        if _mx: val["metrics"]=_mx
    return {
      "package":{"name":mid,"language":ident.get("language"),
                 "implementation":ident.get("implementation"),
                 "scientific_reference_version":ident.get("scientific_reference_version"),
                 "binary":{"path":row["binary_path"] if row else None,
                           "type":row["binary_type"] if row else None}},
      "pipeline":{"stages":stages},
      "tools":{"count":len(tools),"files":tools},
      "inputs":_inputs(dag,ki),
      "io_detail":"full I/O contract incl. units/observability: docs/format_spec.yaml",
      "outputs":{"observable":[entry_name(o) for o in obs],
                 "other":[entry_name(o) for o in outs if o not in obs]},
      "validation":val,
      "summary":{"total_tools":len(tools),"total_stage_docs":len(stages),
                 "total_diagnostic_triplets":ntrip,
                 "generated":str(dt.date.today()),
                 "generated_by":"generate_ki_manifest.py (projection; regenerate any time)"}}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--ki_dir",required=True)
    ki=Path(ap.parse_args().ki_dir)
    spec=build(ki)
    out=ki/"knowledge_infrastructure.yaml"
    if out.is_file():
        while True:
            b=out.with_suffix(f".yaml.bak.{dt.datetime.now():%Y%m%dT%H%M%S_%f}")
            try: b.touch(exist_ok=False); b.write_bytes(out.read_bytes()); break
            except FileExistsError: continue
    out.write_text("# knowledge_infrastructure.yaml — the KI's manifest, PROJECTED from dag.yaml,\n"
                   "# the KI contents and the models DB (generate_ki_manifest.py, 2026-08-15).\n\n"
                   + yaml.safe_dump(spec,sort_keys=False,allow_unicode=True,width=100))
    print(f"Generated: {out}")

if __name__=="__main__": main()
