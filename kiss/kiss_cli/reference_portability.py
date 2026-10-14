"""Classify reference-case paths without rewriting source or claiming a test pass.

Only four top-level case files are eligible. Executable defaults need a bounded
AST proof connecting their actual uses to an explicit CLI/environment binding. Unknown
code shapes remain blocked; simply declaring an unrelated option proves nothing.
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import tokenize

from . import paths


class _Runner:
    def __init__(self, text):
        self.tree = ast.parse(text)
        lines = text.splitlines()
        self.comments = {token.start[0]: token.string
                         for token in tokenize.generate_tokens(io.StringIO(text).readline)
                         if token.type == tokenize.COMMENT and
                         not lines[token.start[0] - 1][:token.start[1]].strip()}
        self.parent = {c: n for n in ast.walk(self.tree) for c in ast.iter_child_nodes(n)}
        self.functions = {n.name: n for n in self.tree.body if isinstance(n, ast.FunctionDef)}
        self.assignments = {}
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                self.assignments.setdefault((self.scope(n), n.targets[0].id), []).append(n)
        self.options = {}
        self.parsed = {}
        parsers = {key for key, values in self.assignments.items() if len(values) == 1
                   and isinstance(values[0].value, ast.Call)
                   and isinstance(values[0].value.func, ast.Attribute)
                   and isinstance(values[0].value.func.value, ast.Name)
                   and values[0].value.func.value.id == 'argparse'
                   and values[0].value.func.attr == 'ArgumentParser'}
        imported = any(isinstance(n, ast.Import) and any(a.name == 'argparse' and a.asname in {None, 'argparse'} for a in n.names) for n in self.tree.body)
        shadowed = any((isinstance(n, ast.Name) and n.id == 'argparse' and isinstance(n.ctx, ast.Store)) or
                       (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == 'argparse') for n in ast.walk(self.tree))
        if not imported or shadowed:
            parsers.clear()
        self.parsers = parsers
        for n in ast.walk(self.tree):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute) or not isinstance(n.func.value, ast.Name):
                continue
            key = self.scope(n), n.func.value.id
            if key not in parsers:
                continue
            if n.func.attr == 'add_argument':
                flags = [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith('--')]
                if flags:
                    dest = next((k.value.value for k in n.keywords if k.arg == 'dest' and isinstance(k.value, ast.Constant)), flags[0][2:].replace('-', '_'))
                    self.options.setdefault(key, set()).add(dest)
            elif n.func.attr == 'parse_args' and not n.args and not n.keywords:
                par = self.parent.get(n)
                if isinstance(par, ast.Assign) and len(par.targets) == 1 and isinstance(par.targets[0], ast.Name):
                    self.parsed[(self.scope(n), par.targets[0].id)] = key

    def qualified(self, node):
        """Resolve ordinary import aliases, refusing rebound module names."""
        if isinstance(node, ast.Attribute):
            base = self.qualified(node.value)
            return base + '.' + node.attr if base else None
        if not isinstance(node, ast.Name):
            return None
        imports = {a.name for item in ast.walk(self.tree) if isinstance(item, ast.Import)
                   for a in item.names if (a.asname or a.name) == node.id}
        imports.update((item.module or '') + '.' + a.name
                       for item in ast.walk(self.tree) if isinstance(item, ast.ImportFrom)
                       for a in item.names if (a.asname or a.name) == node.id)
        if not imports:
            return node.id
        if len(imports) != 1 or any(
                (isinstance(item, ast.Name) and item.id == node.id and isinstance(item.ctx, (ast.Store, ast.Del))) or
                (isinstance(item, ast.arg) and item.arg == node.id) or
                (isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == node.id)
                for item in ast.walk(self.tree)):
            return None
        return next(iter(imports))

    def environment_override(self, node):
        """A named, unmodified environment binding can head an env-only selector."""
        if not (isinstance(node, ast.Call) and self.qualified(node.func) == 'os.environ.get'
                and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str) and node.args[0].value and not node.keywords):
            return False
        key = node.args[0].value
        for item in ast.walk(self.tree):
            if isinstance(item, ast.Attribute) and self.qualified(item) == 'os.environ':
                parent = self.parent.get(item)
                # An escaped mapping can be cleared or updated through its
                # alias. Only direct reads participate in this small proof.
                if not (isinstance(parent, ast.Attribute) and parent.value is item
                        and parent.attr in {'get', 'items', 'keys', 'values', 'copy'}
                        and isinstance(parent.ctx, ast.Load)):
                    if not (isinstance(parent, ast.Subscript) and parent.value is item
                            and isinstance(parent.ctx, ast.Load)):
                        return False
            if isinstance(item, ast.Attribute) and isinstance(item.ctx, (ast.Store, ast.Del)):
                name = self.qualified(item)
                if name and (name == 'os.environ' or name.startswith('os.environ.')):
                    return False
            if (isinstance(item, ast.Subscript) and isinstance(item.ctx, (ast.Store, ast.Del))
                    and self.qualified(item.value) == 'os.environ'):
                if not isinstance(item.slice, ast.Constant) or item.slice.value == key:
                    return False
            if isinstance(item, ast.Call) and self.qualified(item.func) in {
                    'os.environ.clear', 'os.environ.update', 'os.environ.pop', 'os.environ.setdefault',
                    'os.environ.__setitem__', 'os.environ.__delitem__'}:
                if (not item.args or not isinstance(item.args[0], ast.Constant)
                        or item.args[0].value == key or self.qualified(item.func) in {'os.environ.clear', 'os.environ.update'}):
                    return False
        return True

    @staticmethod
    def _selected_assignment(statement):
        # The optional second item is a diagnostic source label, never code.
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            return None
        target, value = statement.targets[0], statement.value
        if isinstance(target, ast.Name):
            return target.id, value
        if (isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple)
                and len(target.elts) == len(value.elts) == 2
                and all(isinstance(t, ast.Name) for t in target.elts)
                and isinstance(value.elts[1], ast.Constant)):
            return target.elts[0].id, value.elts[0]
        return None

    def branch_default(self, node):
        """A parsed option selects the same destination before an else default."""
        statement = next((p for p in self.ancestors(node) if isinstance(p, ast.stmt)), None)
        selected = self._selected_assignment(statement)
        if not selected or node not in ast.walk(selected[1]):
            return False
        child = statement
        while isinstance(self.parent.get(child), ast.If):
            guard = self.parent[child]
            if child not in guard.orelse:
                return False
            if len(guard.body) == 1:
                explicit = self._selected_assignment(guard.body[0])
                if (explicit and explicit[0] == selected[0] and self.override(guard.test)
                        and ast.dump(explicit[1]) == ast.dump(guard.test)):
                    return True
            child = guard
        return False

    @staticmethod
    def _returns_binding(guard, binding):
        """No normal path through this true branch reaches later defaults."""
        if (not isinstance(guard, ast.If) or guard.orelse or not guard.body
                or ast.dump(guard.test) != ast.dump(binding)):
            return False
        last = guard.body[-1]
        if not (isinstance(last, ast.Return) and last.value is not None
                and ast.dump(last.value) == ast.dump(binding)):
            return False
        return not any(isinstance(n, (ast.Break, ast.Continue, ast.For, ast.While,
                                      ast.Try, ast.With, ast.Yield, ast.YieldFrom, ast.Await))
                       for statement in guard.body for n in ast.walk(statement))

    def prior_override_return(self, node):
        """Prove a prior explicit selector returns before this fallback is reached.

        Supports a direct if or a labelled explicit-candidate loop. It does not
        bless the fallback's commands as pure: an explicit binding bypasses that
        entire region, including version probes and missing-engine diagnostics.
        """
        scope = self.scope(node)
        if not isinstance(scope, ast.FunctionDef):
            return False
        statement = node
        while self.parent.get(statement) is not scope:
            statement = self.parent.get(statement)
            if statement is None:
                return False
        for preceding in scope.body[:scope.body.index(statement)]:
            if (isinstance(preceding, ast.If) and self.override(preceding.test)
                    and self._returns_binding(preceding, preceding.test)):
                return True
            if not (isinstance(preceding, ast.For) and not preceding.orelse
                    and isinstance(preceding.target, ast.Tuple) and len(preceding.target.elts) == 2
                    and all(isinstance(t, ast.Name) for t in preceding.target.elts)
                    and isinstance(preceding.iter, ast.Name) and len(preceding.body) == 1):
                continue
            assignment = self.assignment(preceding.iter)
            values = assignment.value if assignment else None
            if (not isinstance(values, (ast.List, ast.Tuple)) or not values.elts
                    or not isinstance(values.elts[0], (ast.List, ast.Tuple))
                    or len(values.elts[0].elts) != 2 or not self.override(values.elts[0].elts[1])
                    or self.loads(preceding.iter.id, scope) != [preceding.iter]):
                continue
            candidate = ast.Name(id=preceding.target.elts[1].id, ctx=ast.Load())
            if self._returns_binding(preceding.body[0], candidate):
                return True
        return False

    def pack_override(self):
        """Do not exempt pack.server_default without its companion runner proof."""
        keys = [n for n in ast.walk(self.tree) if isinstance(n, ast.Constant) and n.value == 'server_default']
        if not keys:
            return False
        for key in keys:
            access = self.parent.get(key)
            if not (isinstance(access, ast.Subscript) and access.slice is key
                    and isinstance(access.ctx, ast.Load) and isinstance(access.value, ast.Name)
                    and self.prior_override_return(access)):
                return False
            scope = self.scope(access)
            if not scope.args.args or access.value.id != scope.args.args[0].arg:
                return False
            # A whole mapping or a computed key could consume the same default
            # without a literal server_default node. Check every pack use, not
            # just the syntactically obvious key accesses.
            # Include closure reads in local helpers; a nested function can
            # otherwise consume the mapping before the explicit-path branch.
            for use in (n for n in ast.walk(scope) if isinstance(n, ast.Name)
                        and isinstance(n.ctx, ast.Load) and n.id == access.value.id):
                parent = self.parent.get(use)
                if (isinstance(parent, ast.Subscript) and parent.value is use
                        and isinstance(parent.ctx, ast.Load) and isinstance(parent.slice, ast.Constant)
                        and isinstance(parent.slice.value, str)):
                    continue
                if (isinstance(parent, ast.Call) and use in parent.args
                        and self.prior_override_return(use)):
                    continue
                return False
            calls = self.function_calls(scope)
            if not calls:
                return False
            for call in calls:
                source = call.args[0] if call.args else None
                if not (isinstance(source, ast.Subscript) and isinstance(source.slice, ast.Constant)
                        and source.slice.value == 'pack' and isinstance(source.value, ast.Name)):
                    return False
                assignment = self.assignment(source.value)
                expected = "json.loads((HERE / 'manifest.json').read_text())"
                if not assignment or ast.unparse(assignment.value) != expected:
                    return False
                # The loaded manifest may only supply this proven resolver.
                # No aliases, unknown consumers or dynamic lookups are proof.
                for use in self.loads(source.value.id, self.scope(assignment)):
                    field = self.parent.get(use)
                    consumer = self.parent.get(field)
                    if not (isinstance(field, ast.Subscript) and field.value is use
                            and isinstance(field.ctx, ast.Load) and isinstance(field.slice, ast.Constant)
                            and field.slice.value == 'pack' and consumer in calls
                            and consumer.args and consumer.args[0] is field):
                        return False
                here = self.assignments.get((self.tree, 'HERE'), [])
                if len(here) != 1 or ast.unparse(here[0].value) != 'Path(__file__).resolve().parent':
                    return False
        return True

    def scope(self, n):
        while n in self.parent:
            n = self.parent[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n
        return self.tree

    def ancestors(self, n):
        while n in self.parent:
            n = self.parent[n]
            yield n
            if isinstance(n, ast.stmt):
                break

    def assignment(self, n):
        scope = self.scope(n)
        if self.unsupported_write(n.id, scope):
            return None
        values = self.assignments.get((scope, n.id), self.assignments.get((self.tree, n.id), []))
        if values and self.unsupported_write(n.id, self.scope(values[0])):
            return None
        return values[0] if len(values) == 1 else None

    def unsupported_write(self, name, scope):
        for node in ast.walk(scope):
            if (isinstance(node, ast.Name) and node.id == name and self.scope(node) is scope
                    and isinstance(node.ctx, (ast.Store, ast.Del))):
                parent = self.parent.get(node)
                if not (isinstance(parent, ast.Assign) and len(parent.targets) == 1
                        and parent.targets[0] is node):
                    return True
        return False

    def override(self, n, seen=frozenset()):
        if id(n) in seen:
            return False
        seen = seen | {id(n)}
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            parser = self.parsed.get((self.scope(n), n.value.id))
            key = self.scope(n), n.value.id
            assignments = self.assignments.get(key, [])
            if len(assignments) != 1 or self.unsupported_write(n.value.id, self.scope(n)):
                return False
            # Namespace mutation or passing the whole namespace to unknown
            # code means the option no longer proves an available override.
            for item in ast.walk(self.scope(n)):
                if isinstance(item, ast.Name) and item.id == n.value.id and isinstance(item.ctx, ast.Load):
                    parent = self.parent.get(item)
                    if not isinstance(parent, ast.Attribute) or parent.value is not item or not isinstance(parent.ctx, ast.Load):
                        return False
            return n.attr in self.options.get(parser, set())
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
            return self.override(n.values[0], seen)
        if isinstance(n, ast.Name):
            if self.unsupported_write(n.id, self.scope(n)):
                return False
            assignment = self.assignment(n)
            if assignment:
                return self.override(assignment.value, seen)
            scope = self.scope(n)
            if isinstance(scope, ast.FunctionDef):
                params = [p.arg for p in scope.args.args]
                if n.id in params:
                    index = params.index(n.id)
                    calls = self.function_calls(scope)
                    return bool(calls) and all(len(c.args) > index and self.override(c.args[index], seen) for c in calls)
        return False

    def function_calls(self, fun):
        calls = []
        for name in ast.walk(self.tree):
            if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Load) and name.id == fun.name:
                parent = self.parent.get(name)
                if not isinstance(parent, ast.Call) or parent.func is not name:
                    return []  # Aliases/dynamic dispatch are outside this proof.
                calls.append(parent)
        return calls

    def diagnostic(self, n):
        for p in self.ancestors(n):
            if isinstance(p, ast.Call):
                rebound = any((isinstance(x, ast.Name) and x.id == 'print' and isinstance(x.ctx, ast.Store)) or
                              (isinstance(x, (ast.FunctionDef, ast.ClassDef)) and x.name == 'print') or
                              (isinstance(x, ast.arg) and x.arg == 'print') or
                              (isinstance(x, ast.alias) and (x.asname or x.name) == 'print') for x in ast.walk(self.tree))
                return isinstance(p.func, ast.Name) and p.func.id == 'print' and not rebound
            if isinstance(p, ast.Expr) and isinstance(p.value, ast.Constant) and isinstance(p.value.value, str):
                owner = self.parent.get(p)
                return isinstance(owner, (ast.Module, ast.FunctionDef, ast.ClassDef)) and owner.body[0] is p
        return False

    def selected(self, n, seen=frozenset()):
        """A sequence is consumed by a candidate selector, not an argv list."""
        if id(n) in seen:
            return False
        seen = seen | {id(n)}
        p = self.parent.get(n)
        if isinstance(p, ast.For) and p.iter is n and isinstance(p.target, ast.Name):
            calls = [c for s in p.body for c in ast.walk(s) if isinstance(c, ast.Call)]
            # The narrow selector proof accepts path/existence predicates,
            # not arbitrary execution hidden before returning a candidate.
            probes = [c for c in calls if self.import_probe(c, p)]
            result_names = {self.parent[c].targets[0].id for c in probes}
            def metadata_call(c):
                if ast.unparse(c.func) == 'tempfile.gettempdir' and not c.args and not c.keywords:
                    return bool(probes)
                if isinstance(c.func, ast.Attribute) and c.func.attr in {'strip', 'splitlines'} and not c.args and not c.keywords:
                    return any(isinstance(x, ast.Attribute) and x.attr == 'stdout' and isinstance(x.value, ast.Name)
                               and x.value.id in result_names for x in ast.walk(c.func.value))
                return False
            pure = all(self.pure_call(c) or c in probes or metadata_call(c) for c in calls)
            def returned(r):
                if not isinstance(r, ast.Return) or not any(isinstance(x, ast.Name) and x.id == p.target.id for x in ast.walk(r)):
                    return False
                node = r
                while node in self.parent and self.parent[node] is not p:
                    node = self.parent[node]
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and not node.test.value:
                        return False
                return True
            return pure and any(returned(r) for statement in p.body for r in ast.walk(statement))
        if isinstance(p, ast.comprehension) and p.iter is n:
            expression = self.parent.get(p)
            pure = all(self.pure_call(c) or self.selector_predicate(c) for item in [*p.ifs, getattr(expression, 'elt', ast.Constant(None))] for c in ast.walk(item) if isinstance(c, ast.Call))
            return pure and any(isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id == 'next' for a in self.ancestors(p))
        if isinstance(p, ast.Assign) and len(p.targets) == 1 and isinstance(p.targets[0], ast.Name):
            uses = self.loads(p.targets[0].id, self.scope(p))
            return bool(uses) and all(self.selected(u, seen) or self._append_use(u) for u in uses)
        if isinstance(p, ast.Call) and n in p.args and isinstance(p.func, ast.Name) and p.func.id in self.functions:
            fun = self.functions[p.func.id]
            index = p.args.index(n)
            if index < len(fun.args.args):
                uses = self.loads(fun.args.args[index].arg, fun)
                return bool(uses) and all(self.selected(u, seen) for u in uses)
        return False

    def pure_call(self, call):
        allowed = {'Path', 'pathlib.Path', 'str', 'all', 'any', 'bool', 'os.path.isfile', 'os.path.isdir',
                   'os.path.exists', 'os.path.abspath', 'os.path.join', 'os.access'}
        if self.qualified(call.func) in allowed:
            return True
        return (isinstance(call.func, ast.Attribute) and call.func.attr in
                {'is_file', 'is_dir', 'exists', 'resolve'} and
                any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'Path'
                    for n in ast.walk(call.func.value)) and
                all(self.pure_call(n) for n in ast.walk(call.func.value) if isinstance(n, ast.Call)))

    def selector_predicate(self, call):
        if not isinstance(call.func, ast.Name):
            return False
        scope = self.scope(call)
        if isinstance(scope, ast.FunctionDef) and call.func.id in [p.arg for p in scope.args.args]:
            index = [p.arg for p in scope.args.args].index(call.func.id)
            callers = self.function_calls(scope)
            def pure_callback(value):
                if isinstance(value, ast.Lambda):
                    return all(self.pure_call(c) for c in ast.walk(value.body) if isinstance(c, ast.Call))
                return ast.unparse(value) in {'os.path.isfile', 'os.path.isdir', 'os.path.exists'}
            return bool(callers) and all(len(c.args) > index and pure_callback(c.args[index]) for c in callers)
        fun = self.functions.get(call.func.id)
        if not fun or not self.function_calls(fun) or len(fun.args.args) != 1 or len(fun.body) != 1:
            return False
        statement = fun.body[0]
        if isinstance(statement, ast.Try):
            if (len(statement.body) != 1 or statement.orelse or statement.finalbody or
                    any(len(h.body) != 1 or not isinstance(h.body[0], ast.Return) or
                        not isinstance(h.body[0].value, ast.Constant) or h.body[0].value.value is not False for h in statement.handlers)):
                return False
            statement = statement.body[0]
        if not isinstance(statement, ast.Return):
            return False
        comparison = statement.value
        return (isinstance(comparison, ast.Compare) and len(comparison.ops) == 1
                and isinstance(comparison.ops[0], ast.Eq) and len(comparison.comparators) == 1
                and isinstance(comparison.comparators[0], ast.Constant) and comparison.comparators[0].value == 0
                and isinstance(comparison.left, ast.Attribute) and comparison.left.attr == 'returncode'
                and isinstance(comparison.left.value, ast.Call)
                and self.import_command(comparison.left.value, fun.args.args[0].arg))

    def import_command(self, call, candidate):
        if ast.unparse(call.func) != 'subprocess.run' or len(call.args) != 1:
            return False
        argv = call.args[0]
        if not (isinstance(argv, (ast.List, ast.Tuple)) and len(argv.elts) == 3
                and isinstance(argv.elts[0], ast.Name) and argv.elts[0].id == candidate
                and isinstance(argv.elts[1], ast.Constant) and argv.elts[1].value == '-c'
                and all(k.arg in {'capture_output', 'text', 'timeout', 'cwd'} for k in call.keywords)):
            return False
        snippet = argv.elts[2]
        if isinstance(snippet, ast.Name):
            definition = self.assignment(snippet)
            snippet = definition.value if definition else None
        if not isinstance(snippet, ast.Constant) or not isinstance(snippet.value, str):
            return False
        try:
            script = ast.parse(snippet.value)
        except SyntaxError:
            return False
        metadata = set()
        imports = set()
        for statement in script.body:
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    imports.add(alias.asname or alias.name.split('.')[0])
                    if alias.name == 'importlib.metadata':
                        metadata.add(alias.asname or alias.name)
            elif isinstance(statement, ast.ImportFrom):
                imports.update(a.asname or a.name for a in statement.names)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and isinstance(statement.value.func, ast.Name) and statement.value.func.id == 'print' and not statement.value.keywords:
                for value in statement.value.args:
                    version = (isinstance(value, ast.Attribute) and value.attr == '__version__'
                               and isinstance(value.value, ast.Name) and value.value.id in imports)
                    query = (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                             and value.func.attr == 'version' and ast.unparse(value.func.value) in metadata
                             and len(value.args) == 1 and isinstance(value.args[0], ast.Constant)
                             and isinstance(value.args[0].value, str) and not value.keywords)
                    if not isinstance(value, ast.Constant) and not version and not query:
                        return False
            else:
                return False
        if not imports:
            return False
        return True

    def import_probe(self, call, loop):
        if not self.import_command(call, loop.target.id):
            return False
        assignment = self.parent.get(call)
        if not (isinstance(assignment, ast.Assign) and len(assignment.targets) == 1 and isinstance(assignment.targets[0], ast.Name)):
            return False
        result = assignment.targets[0].id
        if len(self.assignments.get((self.scope(call), result), [])) != 1:
            return False
        for guard in ast.walk(loop):
            if (isinstance(guard, ast.If) and guard.lineno > call.lineno and len(guard.body) == 1
                    and isinstance(guard.body[0], ast.Return) and isinstance(guard.test, ast.Compare)
                    and ast.unparse(guard.test.left) == f'{result}.returncode'
                    and len(guard.test.ops) == 1 and isinstance(guard.test.ops[0], ast.Eq)
                    and len(guard.test.comparators) == 1 and isinstance(guard.test.comparators[0], ast.Constant)
                    and guard.test.comparators[0].value == 0):
                returned = guard.body[0].value
                returned = returned.elts[0] if isinstance(returned, ast.Tuple) and returned.elts else returned
                if isinstance(returned, ast.Name) and returned.id == loop.target.id:
                    return True
        return False

    def guarded_path(self, n):
        """Recognize an optional PATH search fallback, never an unconditional prepend."""
        stmt = next((p for p in self.ancestors(n) if isinstance(p, ast.Assign)), None)
        if not stmt or len(stmt.targets) != 1:
            return False
        target = stmt.targets[0]
        if not (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                and isinstance(target.slice, ast.Constant) and target.slice.value == 'PATH'):
            return False
        env = target.value.id
        guard = self.parent.get(stmt)
        if not (isinstance(guard, ast.If) and stmt in guard.body and
                isinstance(guard.test, ast.UnaryOp) and isinstance(guard.test.op, ast.Not)):
            return False
        lookup = guard.test.operand
        if not (isinstance(lookup, ast.Call) and ast.unparse(lookup.func) == 'shutil.which'
                and len(lookup.args) == 1 and isinstance(lookup.args[0], ast.Constant) and not lookup.keywords):
            return False
        assigns = self.assignments.get((self.scope(stmt), env), [])
        if len(assigns) != 1 or ast.unparse(assigns[0].value) != 'dict(os.environ)' or assigns[0].lineno >= guard.lineno:
            return False
        # Exact fallback + path separator + original PATH, with no replacement.
        value = stmt.value
        if not (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)
                and isinstance(value.left, ast.BinOp) and isinstance(value.left.op, ast.Add)
                and n in ast.walk(value.left.left) and ast.unparse(value.left.right) == 'os.pathsep'
                and ast.unparse(value.right) == f"{env}.get('PATH', '')"):
            return False
        stores = [a for a in ast.walk(self.scope(stmt)) if isinstance(a, ast.Subscript)
                  and isinstance(a.ctx, ast.Store) and isinstance(a.value, ast.Name)
                  and a.value.id == env and isinstance(a.slice, ast.Constant) and a.slice.value == 'PATH']
        if stores != [target]:
            return False
        return any(isinstance(c, ast.Call) and c.lineno > guard.end_lineno
                   and ast.unparse(c.func) == 'shutil.which' and c.args
                   and ast.dump(c.args[0]) == ast.dump(lookup.args[0])
                   and any(k.arg == 'path' and ast.unparse(k.value) == f"{env}['PATH']" for k in c.keywords)
                   for c in ast.walk(self.scope(stmt)))

    def guarded_option_default(self, n):
        """Set one parsed option only when its explicit alternatives are absent."""
        statement = next((p for p in self.ancestors(n) if isinstance(p, ast.stmt)), None)
        guard = self.parent.get(statement) if isinstance(statement, ast.Assign) else statement
        if not (isinstance(guard, ast.If) and not guard.orelse and len(guard.body) == 1
                and isinstance(guard.body[0], ast.Assign) and len(guard.body[0].targets) == 1
                and isinstance(guard.test, ast.BoolOp) and isinstance(guard.test.op, ast.And)
                and len(guard.test.values) == 2):
            return False
        assignment = guard.body[0]
        target = assignment.targets[0]
        if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                and isinstance(assignment.value, ast.Name)):
            return False
        namespace = target.value.id
        key = self.scope(guard), namespace
        parser = self.parsed.get(key)
        if target.attr not in self.options.get(parser, set()) or len(self.assignments.get(key, [])) != 1:
            return False
        missing, exists = guard.test.values
        if not (isinstance(missing, ast.UnaryOp) and isinstance(missing.op, ast.Not)):
            return False
        options = missing.operand.values if isinstance(missing.operand, ast.BoolOp) and isinstance(missing.operand.op, ast.Or) else [missing.operand]
        targeted = False
        for option in options:
            if isinstance(option, ast.Attribute) and isinstance(option.value, ast.Name) and option.value.id == namespace and option.attr in self.options.get(parser, set()):
                targeted |= option.attr == target.attr
            elif not (isinstance(option, ast.Call) and ast.unparse(option.func) == 'os.environ.get'
                      and len(option.args) == 1 and isinstance(option.args[0], ast.Constant)
                      and isinstance(option.args[0].value, str) and not option.keywords):
                return False
        if not targeted or not (isinstance(exists, ast.Call) and isinstance(exists.func, ast.Attribute)
                and exists.func.attr in {'is_file', 'is_dir', 'exists'} and not exists.args and not exists.keywords
                and isinstance(exists.func.value, ast.Call) and isinstance(exists.func.value.func, ast.Name)
                and exists.func.value.func.id == 'Path' and len(exists.func.value.args) == 1
                and not exists.func.value.keywords and isinstance(exists.func.value.args[0], ast.Name)
                and exists.func.value.args[0].id == assignment.value.id):
            return False
        if not isinstance(n, ast.Name) or n.id != assignment.value.id:
            return False
        # This exact guarded fallback is the only namespace mutation allowed.
        for item in ast.walk(self.scope(guard)):
            if isinstance(item, ast.Name) and item.id == namespace and isinstance(item.ctx, ast.Load):
                parent = self.parent.get(item)
                if not isinstance(parent, ast.Attribute) or parent.value is not item:
                    return False
                if not isinstance(parent.ctx, ast.Load) and parent is not target:
                    return False
        return n is assignment.value or n is exists.func.value.args[0]

    def _append_use(self, n):
        p = self.parent.get(n)
        return isinstance(p, ast.Attribute) and p.value is n and p.attr == 'append'

    def loads(self, name, scope):
        result = []
        for n in ast.walk(scope):
            if not isinstance(n, ast.Name) or not isinstance(n.ctx, ast.Load) or n.id != name:
                continue
            local = self.scope(n)
            if local is scope:
                result.append(n)
            elif scope is self.tree and (local, name) not in self.assignments:
                if not isinstance(local, ast.FunctionDef) or name not in {p.arg for p in local.args.args}:
                    result.append(n)
        return result

    def safe_use(self, n, seen=frozenset()):
        if self.diagnostic(n):
            return True
        if self.guarded_path(n):
            return True
        if self.guarded_option_default(n):
            return True
        if self.branch_default(n) or self.prior_override_return(n):
            return True
        if id(n) in seen:
            return False
        seen = seen | {id(n)}
        for p in self.ancestors(n):
            if isinstance(p, ast.BoolOp) and isinstance(p.op, ast.Or):
                containing = next((i for i, v in enumerate(p.values) if n in ast.walk(v)), 0)
                if any(self.override(v) for v in p.values[:containing]):
                    return True
            if isinstance(p, (ast.Tuple, ast.List)):
                containing = next((i for i, v in enumerate(p.elts) if n in ast.walk(v)), 0)
                if any(self.override(v) for v in p.elts[:containing]) and self.selected(p):
                    return True
                if containing and self.environment_override(p.elts[0]) and self.selected(p):
                    return True
            if isinstance(p, ast.Call):
                # A default passed into a local selector's parameter must be
                # used only after that selector's proven override parameter.
                if isinstance(p.func, ast.Name) and p.func.id in self.functions:
                    for i, value in enumerate(p.args):
                        if n in ast.walk(value):
                            fun = self.functions[p.func.id]
                            if self.function_calls(fun) and i < len(fun.args.args):
                                uses = self.loads(fun.args.args[i].arg, fun)
                                if uses and all(self.safe_use(u, seen) for u in uses):
                                    return True
                if isinstance(p.func, ast.Attribute) and p.func.attr == 'append' and isinstance(p.func.value, ast.Name):
                    base = self.assignment(p.func.value)
                    if base and isinstance(base.value, (ast.Tuple, ast.List)) and any(self.override(e) for e in base.value.elts) and self.selected(base.value):
                        return True
                if isinstance(p.func, ast.Attribute) and p.func.attr == 'add_argument' and any(k.arg == 'default' and n in ast.walk(k.value) for k in p.keywords):
                    return (isinstance(p.func.value, ast.Name) and
                            (self.scope(p), p.func.value.id) in self.parsers and
                            any(isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith('--') for a in p.args))
            if isinstance(p, ast.Assign) and len(p.targets) == 1 and isinstance(p.targets[0], ast.Name):
                # Derived path tuples/strings can flow to a proven selector.
                uses = self.loads(p.targets[0].id, self.scope(p))
                pure = not any(isinstance(x, (ast.Call, ast.Await, ast.Yield, ast.Lambda)) for x in ast.walk(p.value))
                if pure and uses and all(self.safe_use(u, seen) for u in uses):
                    return True
        return False

    def classify(self, line, path):
        if path in self.comments.get(line, ''):
            return 'provenance', 'Full-line Python comment; source bytes retained'
        strings = [n for n in ast.walk(self.tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and path in n.value and n.lineno <= line <= n.end_lineno]
        if not strings:
            return 'blocked', 'Path is not a proven configurable literal or provenance string'
        if all(self.diagnostic(n) for n in strings):
            return 'provenance', 'Runner docstring or printed diagnostic; no test outcome inferred'
        if all(self.safe_use(n) for n in strings):
            return 'configurable_default', 'AST connects every default use to an explicit CLI/environment binding and guarded selection'
        return 'blocked', 'Runner path has no bounded proof that every use is an overridable default'


def _json_category(text, filename, matched, runner=None):
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return 'blocked', 'Invalid reference-case JSON'
    if not isinstance(doc, dict):
        return 'blocked', 'Reference-case JSON must be an object'
    allowed = []
    if filename == 'expected.json':
        for key in ('recorded_with', 'engine_version', 'run_tweak'):
            if key in doc:
                allowed.append(doc.pop(key))
        notes = doc.get('notes')
        if isinstance(notes, list) and all(isinstance(v, str) for v in notes):
            allowed.extend(doc.pop('notes'))
        category = 'provenance'
    else:
        engine = doc.get('engine')
        if isinstance(engine, dict):
            for key in ('binary', 'default_binary', 'binary_default', 'python', 'source', 'build'):
                if key in engine:
                    allowed.append(engine.pop(key))
        pack = doc.get('pack')
        if (isinstance(pack, dict) and isinstance(pack.get('server_default'), str)
                and runner is not None and runner.pack_override()):
            allowed.append(pack.pop('server_default'))
        category = 'runtime_binding_metadata'
    if any(isinstance(v, str) and matched in v for v in allowed) and matched not in json.dumps(doc, ensure_ascii=False):
        return category, 'Known recorded provenance or external engine-binding field; source bytes retained'
    return 'blocked', 'Path occurs outside recognized provenance/engine fields'


def classify_reference_paths(ki) -> dict[str, list[dict]]:
    """Return scanner-aligned classifications; core files and fixtures stay strict."""
    out = {}
    for relative in sorted(ki.portability.files):
        rel = Path(relative)
        if len(rel.parts) != 3 or rel.parts[0] != 'test_cases' or rel.name not in {'README.md', 'expected.json', 'manifest.json', 'run_reference.py'}:
            continue
        file = ki.root / rel
        if file.is_symlink():
            continue
        try:
            text = file.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        runner = None
        if rel.name in {'run_reference.py', 'manifest.json'}:
            try:
                companion = file.with_name('run_reference.py')
                if not companion.is_symlink():
                    runner = _Runner(text if rel.name == 'run_reference.py' else companion.read_text(encoding='utf-8'))
            except (OSError, UnicodeError, SyntaxError, ValueError, tokenize.TokenError):
                pass
        rows = []
        for number, line in enumerate(text.splitlines(), 1):
            for matched, role in paths.scan_text(line):
                if rel.name == 'README.md':
                    category, reason = 'provenance', 'Reference-case documentation; local runtime binding still required'
                elif rel.suffix == '.json':
                    category, reason = _json_category(text, rel.name, matched, runner)
                elif runner is not None:
                    category, reason = runner.classify(number, matched)
                else:
                    category, reason = 'blocked', 'Runner cannot be parsed'
                rows.append({'line': number, 'path': matched, 'role': role,
                             'classification': category, 'reason': reason})
        out[rel.as_posix()] = rows
    return out
