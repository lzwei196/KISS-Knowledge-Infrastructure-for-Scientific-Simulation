#!/usr/bin/env python3
"""Offline planning-interface census, NOT a scientific KI pass/fail test.

Reads KI descriptions through current Desktop/shared-Flow parsers. Never imports
model tools, launches providers, downloads data, or edits a KI/project. JSON/CSV
outputs contain declaration-level evidence and parser results for every package.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'kiss'), str(REPO / 'ki_tools_common')]
import yaml
from kiss_cli import preparation, observatory
from kiss_cli.catalog import Catalog
from ki_tools_common.flow import ki_inputs, plan

DOCS = ('SKILL.md', 'dag.yaml', 'docs/format_spec.yaml', 'knowledge_infrastructure.yaml')


def document(path):
    if not path.is_file():
        return {}, 'missing'
    try:
        doc = yaml.safe_load(path.read_text(encoding='utf-8'))
        return (doc, 'mapping') if isinstance(doc, dict) else ({}, type(doc).__name__)
    except Exception as e:
        return {}, f'{type(e).__name__}: {str(e)[:160]}'


def declared_rows(doc):
    section = doc.get('inputs') or {}
    if isinstance(section, dict):
        return [dict(row, _section=key) for key, values in section.items()
                for row in preparation.flatten_declarations(values)]
    return [dict(row, _section='ungrouped') for row in preparation.flatten_declarations(section)]


def present(value):
    return value is not None and value != '' and value != [] and value != {}


def inspect(ki, origin, roots, indexes):
    dag, dag_shape = document(ki.root / 'dag.yaml')
    spec, spec_shape = document(ki.root / 'docs/format_spec.yaml')
    manifest, manifest_shape = document(ki.root / 'knowledge_infrastructure.yaml')
    raw = declared_rows(dag)
    errors = {}
    try:
        desktop = preparation._model_inputs(ki)
    except Exception as e:
        desktop = []
        errors['desktop_reader'] = f'{type(e).__name__}: {e}'
    try:
        shared, note = ki_inputs.model_inputs(roots.root, ki.name, ki_root=ki.root)
    except Exception as e:
        shared, note = [], f'{type(e).__name__}: {e}'
        errors['shared_reader'] = note
    scientific = [r for r in shared if r.get('category') != '_meta']
    stages = ki_inputs.skill_stages(ki.root)
    try:
        derived = plan.derive_plan_for_model(ki.name, {'models': [ki.name]}, indexes, roots, ki_root=ki.root)
        full = {'models': [ki.name], 'plans': [derived]}
        starter, inventory = plan.to_artifacts(full, 'Static interface census; no scientific case selected', {ki.name: ki.root})
    except Exception as e:
        derived, starter, inventory = {}, {}, {}
        errors['draft_builder'] = f'{type(e).__name__}: {e}'
    tools_section = manifest.get('tools') or {}
    declared_tools = (tools_section.get('files') or []) if isinstance(tools_section, dict) else tools_section
    if not isinstance(declared_tools, list):
        declared_tools = []
    tool_rows = []
    for tool in declared_tools:
        if isinstance(tool, dict):
            tool = tool.get('path') or tool.get('file')
        if not isinstance(tool, str):
            continue
        p = ki.root / tool
        inside = p.resolve().is_relative_to(ki.root.resolve())
        tool_rows.append({'path': tool, 'exists_under_ki': inside and p.is_file()})
    docs = {name: hashlib.sha256((ki.root / name).read_bytes()).hexdigest()
            for name in DOCS if (ki.root / name).is_file()}
    domain, domain_evidence = observatory.classify(ki)
    defaults = [r for r in desktop if 'default' in r and present(r['default'])]
    pipeline = manifest.get('pipeline') or {}
    manifest_stages = (pipeline.get('stages') or []) if isinstance(pipeline, dict) else pipeline
    row = {
        'name': ki.name, 'origin': origin, 'root': str(ki.root),
        'domain': domain, 'domain_evidence': domain_evidence,
        'document_hashes': docs, 'dag_shape': dag_shape, 'format_spec_shape': spec_shape,
        'manifest_shape': manifest_shape,
        'dag_input_count': len(raw), 'dag_section_counts': dict(Counter(r['_section'] for r in raw)),
        'dag_fields_present': dict(Counter(k for r in raw for k,v in r.items() if present(v))),
        'dag_source_kinds': dict(Counter(str(r.get('source_kind') or '(unspecified)') for r in raw)),
        'desktop_input_count': len(desktop), 'desktop_group_counts': dict(Counter(r['group'] for r in desktop)),
        'desktop_default_field_count': len(defaults),
        'desktop_valid_range_count': sum(present(r.get('valid_range')) for r in desktop),
        'desktop_format_count': sum(present(r.get('format') or r.get('model_input_format')) for r in desktop),
        'shared_input_count': len(scientific), 'shared_reader_note': note,
        'canonical_input_count': sum(bool(r.get('canonical_id')) for r in scientific),
        'ki_internal_count': len(derived.get('ki_internal') or []),
        'draft_inventory_count': len(inventory.get('items') or []),
        'draft_steps': len(starter.get('steps') or []),
        'draft_steps_with_tool': sum(bool(s.get('tool')) for s in starter.get('steps') or []),
        'draft_steps_with_inputs': sum(bool(s.get('inputs')) for s in starter.get('steps') or []),
        'skill_stage_count': len(stages),
        'manifest_stage_count': len(manifest_stages) if isinstance(manifest_stages, list) else 0,
        'manifest_tool_count': len(tool_rows),
        'manifest_tool_existing_count': sum(t['exists_under_ki'] for t in tool_rows),
        'reader_errors': errors,
        'requirements': desktop,
        'shared_requirements': scientific,
        'skill_stages': stages,
        'manifest_tools': tool_rows,
        'status': 'static interface evidence only; no scientific pass/fail verdict',
    }
    return row


def summarize(rows):
    return {
        'packages': len(rows),
        'domains': dict(sorted(Counter(r['domain'] for r in rows).items())),
        'dag_mapping': sum(r['dag_shape'] == 'mapping' for r in rows),
        'missing_dag': [r['name'] for r in rows if r['dag_shape'] == 'missing'],
        'format_spec_mapping': sum(r['format_spec_shape'] == 'mapping' for r in rows),
        'desktop_nonempty': sum(r['desktop_input_count'] > 0 for r in rows),
        'desktop_empty': [r['name'] for r in rows if not r['desktop_input_count']],
        'shared_nonempty': sum(r['shared_input_count'] > 0 for r in rows),
        'shared_empty': [r['name'] for r in rows if not r['shared_input_count']],
        'draft_inventory_nonempty': sum(r['draft_inventory_count'] > 0 for r in rows),
        'skill_stages_nonempty': sum(r['skill_stage_count'] > 0 for r in rows),
        'skill_stages_empty': [r['name'] for r in rows if not r['skill_stage_count']],
        'with_default_field': sum(r['desktop_default_field_count'] > 0 for r in rows),
        'with_valid_range_field': sum(r['desktop_valid_range_count'] > 0 for r in rows),
        'with_ki_internals': sum(r['ki_internal_count'] > 0 for r in rows),
        'with_declared_applicability': sum(r['dag_fields_present'].get('applicability',0) > 0 for r in rows),
        'sum_desktop_inputs': sum(r['desktop_input_count'] for r in rows),
        'sum_shared_inputs': sum(r['shared_input_count'] for r in rows),
        'sum_draft_inventory': sum(r['draft_inventory_count'] for r in rows),
        'sum_ki_internal': sum(r['ki_internal_count'] for r in rows),
        'sum_draft_steps': sum(r['draft_steps'] for r in rows),
        'sum_draft_steps_with_tool': sum(r['draft_steps_with_tool'] for r in rows),
        'reader_errors': {r['name']:r['reader_errors'] for r in rows if r['reader_errors']},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--include-local-library', action='store_true', help='Read configured local KI snapshot and user imports, not credentials')
    args = parser.parse_args()
    roots = plan.DataRoots.bundled(REPO/'ki_tools_common/ki_tools_common/flow/data')
    indexes = plan.build_indexes(roots)
    libraries = [('repository', Catalog(REPO/'models'))]
    if args.include_local_library:
        from kiss_cli.firstrun import data_dir
        from kiss_cli.ki_updates import active_library_root
        active = active_library_root()
        if active:
            libraries.append(('active_snapshot', Catalog(active/'models')))
        user = data_dir()/'user_models'
        if user.is_dir():
            libraries.append(('user_import', Catalog(user)))
    rows = []
    for origin, catalog in libraries:
        for name in sorted(catalog.packages):
            rows.append(inspect(catalog.packages[name], origin, roots, indexes))
        print(f'{origin}: inspected {len(catalog.packages)} KI descriptions', flush=True)
    summary = {origin: summarize([r for r in rows if r['origin'] == origin]) for origin,_ in libraries}
    repo_rows = {r['name']: r for r in rows if r['origin'] == 'repository'}
    changed = [r['name'] for r in rows if r['origin'] == 'active_snapshot' and
               (r['name'] not in repo_rows or r['document_hashes'] != repo_rows[r['name']]['document_hashes'])]
    report = {'method':'Offline current-reader census; different readers are not equal definitions of inputs. No live agent/model/download. No scientific validation claim.',
              'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
              'active_snapshot_changed_descriptions':changed, 'summary':summary, 'packages':rows}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'census.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)+'\n',encoding='utf-8')
    fields = ['origin','name','domain','dag_shape','dag_input_count','desktop_input_count','shared_input_count',
              'canonical_input_count','ki_internal_count','draft_inventory_count','skill_stage_count',
              'manifest_stage_count','desktop_default_field_count','desktop_valid_range_count',
              'desktop_format_count','manifest_tool_count','manifest_tool_existing_count','root']
    with (args.output/'matrix.csv').open('w',newline='',encoding='utf-8') as handle:
        writer = csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({'summary':summary,'changed_descriptions':changed},indent=2))


if __name__ == '__main__':
    main()
