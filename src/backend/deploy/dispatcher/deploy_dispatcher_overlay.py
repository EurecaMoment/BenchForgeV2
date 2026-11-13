"""Prepare/install the owned-context overlay, or build its standalone source bundle.

This does not call the service, inspect tasks, signal processes or start Isaac.
The external supervisor retains its existing source-reload and slot handoff.
"""
import argparse
import ast
import json
from pathlib import Path
import re
import time
import zipfile

from dispatcher_overlay import default_adapter_path

HERE = Path(__file__).resolve().parent
BEGIN = '# BEGIN BenchForge canonical dispatcher overlay'
END = '# END BenchForge canonical dispatcher overlay'
BUNDLE_FILES = ('dispatcher_overlay.py', 'deploy_dispatcher_overlay.py', 'dispatcher_overlay.example.json',
                'DISPATCHER_OVERLAY.md', 'worker_cancellation.py')


def functions(tree):
    return {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}


def replace_node(source, node, replacement):
    lines = source.splitlines(keepends=True)
    return ''.join(lines[:node.lineno - 1]) + replacement + ''.join(lines[node.end_lineno:])


def relocate_cancellation_helper(source, function):
    """Point an installed late-cancel patch to this overlay's helper."""
    if function is None:
        return source
    for call in ast.walk(function):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == 'spec_from_file_location' and len(call.args) >= 2):
            continue
        module, path = call.args[:2]
        if not (isinstance(module, ast.Constant) and module.value == 'capture_cancel_ack'
                and isinstance(path, ast.Constant) and isinstance(path.value, str)
                and path.value.replace('\\', '/').rsplit('/', 1)[-1] == 'worker_cancellation.py'):
            continue
        lines = source.encode('utf-8').splitlines(keepends=True)
        start, end = path.lineno - 1, path.end_lineno - 1
        replacement = repr(str(HERE / 'worker_cancellation.py')).encode('utf-8')
        lines[start:end + 1] = [lines[start][:path.col_offset] + replacement + lines[end][path.end_col_offset:]]
        return b''.join(lines).decode('utf-8')
    return source


def prepare(source, *, backend_python, adapter_path=None, timeout_seconds=20):
    newline = '\r\n' if '\r\n' in source else '\n'
    if source.count(BEGIN) != source.count(END) or source.count(BEGIN) > 1:
        raise ValueError('Ambiguous existing dispatcher overlay; source left untouched')
    source = re.sub(r'^' + re.escape(BEGIN) + r'\r?\n.*?^' + re.escape(END) + r'\r?\n', '', source, flags=re.M | re.S)
    before = ast.parse(source)
    relocated = relocate_cancellation_helper(source, functions(before).get('finish_canceled_capture'))
    if relocated != source:
        source = relocated
        before = ast.parse(source)
    original = functions(before)
    api, execute = original.get('api'), original.get('execute')
    if not isinstance(api, ast.FunctionDef) or not isinstance(execute, ast.FunctionDef):
        raise ValueError('Expected the external dispatcher api/execute functions')
    first = api.body[0]
    if not isinstance(first, ast.If) or '/worker/finish' not in ast.get_source_segment(source, first.test):
        raise ValueError('Dispatcher control route changed; source left untouched')
    source = replace_node(source, first, newline.join([
        "    if path in ('/worker/finish','/worker/context'):",
        '        return _bf_dispatcher_control(path, value)', '']))
    execute = functions(ast.parse(source))['execute']
    if any(isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and
           node.args[0].value == '/inspect' for node in ast.walk(execute)):
        first = execute.body[0]
        text = ast.get_source_segment(source, first)
        if not isinstance(first, ast.If) or text.count("api('/inspect'") != 1 or 'capture_recovery_mode' not in text or 'transport_retry' not in text:
            raise ValueError('Unknown old recovery context; source left untouched')
        source = replace_node(source, first, newline.join([
            "    if job.get('transport_retry',0)>0 and 'capture_recovery_mode' not in job:",
            "        context=api('/worker/context',{'job':identity(job)})",
            "        if context.get('committed') or context.get('finished'):return context",
            "        job={**job,**context['capture_context']}", '']))
    after = ast.parse(source)
    if any(isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and
           node.args[0].value == '/inspect' for node in ast.walk(after)):
        raise ValueError('Dispatcher still calls management /inspect; source left untouched')
    revised = functions(after)
    for name, node in original.items():
        if name not in {'api', 'execute'} and ast.dump(node) != ast.dump(revised.get(name)):
            raise ValueError('Overlay changed an unrelated dispatcher function: ' + name)
    if [ast.dump(node) for node in original['api'].body[1:]] != [ast.dump(node) for node in revised['api'].body[1:]]:
        raise ValueError('Overlay changed the existing HTTP/upload transport')
    if [ast.dump(node) for node in original['execute'].body[1:]] != [ast.dump(node) for node in revised['execute'].body[1:]]:
        raise ValueError('Overlay changed frozen capture execution or resume')
    module_path = str((HERE / 'dispatcher_overlay.py').resolve())
    adapter_path = str(Path(adapter_path or default_adapter_path()).resolve())
    backend_python = str(Path(backend_python).absolute())
    block = newline.join([
        BEGIN,
        'import importlib.util as _bf_overlay_import',
        '_bf_overlay_spec = _bf_overlay_import.spec_from_file_location("bf_dispatcher_overlay", ' + repr(module_path) + ')',
        '_bf_overlay_module = _bf_overlay_import.module_from_spec(_bf_overlay_spec)',
        '_bf_overlay_spec.loader.exec_module(_bf_overlay_module)',
        '_bf_dispatcher_control = _bf_overlay_module.CanonicalControl(',
        '    service_config=CONFIG, backend_python=' + repr(backend_python) + ',',
        '    adapter_path=' + repr(adapter_path) + ', timeout_seconds=' + repr(timeout_seconds) + ')',
        END, '',
    ])
    api = revised['api']
    lines = source.splitlines(keepends=True)
    source = ''.join(lines[:api.lineno - 1]) + block + ''.join(lines[api.lineno - 1:])
    ast.parse(source)
    return source, {'protected_functions': [name for name in original if name not in {'api', 'execute'}],
                    'http_transport_unchanged': True, 'execution_resume_unchanged': True,
                    'context_route': '/worker/context', 'canonical_backend_python': backend_python}


def bundle(output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in BUNDLE_FILES:
            archive.write(HERE / name, 'dispatcher-overlay/' + name)
        archive.write(default_adapter_path(), 'dispatcher-overlay/capture_finish.py')
    return {'operation': 'bundled', 'path': str(output), 'files': [*BUNDLE_FILES, 'capture_finish.py']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Private overlay settings, separate from the native service config')
    parser.add_argument('--dispatcher', type=Path)
    parser.add_argument('--backend-python', type=Path)
    parser.add_argument('--adapter-path', type=Path)
    parser.add_argument('--timeout-seconds', type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path, help='Prepare a candidate without changing the dispatcher')
    mode.add_argument('--apply', action='store_true', help='Back up and atomically replace only the named dispatcher source')
    mode.add_argument('--bundle', type=Path, help='Package overlay sources and canonical adapters; no credentials or native installation')
    options = parser.parse_args()
    if options.bundle:
        print(json.dumps(bundle(options.bundle)))
        return
    settings = json.loads(options.config.read_text(encoding='utf8')) if options.config else {}
    dispatcher = options.dispatcher or settings.get('dispatcher')
    backend = options.backend_python or settings.get('backend_python')
    adapter = options.adapter_path or settings.get('adapter_path') or default_adapter_path()
    timeout = options.timeout_seconds if options.timeout_seconds is not None else settings.get('timeout_seconds', 20)
    if not dispatcher or not backend:
        parser.error('Provide the existing dispatcher and the canonical backend Python')
    dispatcher, backend, adapter = Path(dispatcher).resolve(), Path(backend).absolute(), Path(adapter).resolve()
    if not all(path.is_file() for path in (dispatcher, backend, adapter)):
        parser.error('Dispatcher, backend Python and canonical adapter must already exist')
    if type(timeout) is not int or not 1 <= timeout <= 60:
        parser.error('Control timeout must be an integer in 1..60 seconds')
    current = dispatcher.read_bytes()
    candidate, receipt = prepare(current.decode('utf8'), backend_python=backend, adapter_path=adapter, timeout_seconds=timeout)
    encoded = candidate.encode('utf8')
    if options.apply:
        backup = dispatcher.with_name(dispatcher.name + '.before-benchforge-overlay-' + str(time.time_ns()))
        backup.write_bytes(current)
        temporary = dispatcher.with_name(dispatcher.name + '.benchforge-overlay-new')
        temporary.write_bytes(encoded)
        temporary.replace(dispatcher)
        receipt.update(operation='applied', dispatcher=str(dispatcher), backup=str(backup))
    else:
        output = options.output.resolve()
        if output == dispatcher:
            parser.error('Use --apply for the existing dispatcher; --output prepares a separate candidate')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
        receipt.update(operation='prepared', dispatcher=str(dispatcher), output=str(output))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
