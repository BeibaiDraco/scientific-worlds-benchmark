"""Bind unchanged neural physics/public views without importing the Mac runner."""
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PACKAGE = 'sw_frozen_neural'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_release(root):
    root = Path(root).resolve()
    manifest = json.loads((HERE/'DEPENDENCIES.json').read_text())
    for name, expected in manifest['files'].items():
        if digest(root/name) != expected:
            raise RuntimeError('frozen_dependency_changed:' + name)
    if PACKAGE in sys.modules:
        if Path(sys.modules[PACKAGE].__file__).resolve() != root/'b720/__init__.py':
            raise RuntimeError('different_release_already_loaded')
    else:
        spec = importlib.util.spec_from_file_location(PACKAGE, root/'b720/__init__.py',
            submodule_search_locations=[str(root/'b720')])
        module = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = module
        spec.loader.exec_module(module)
    return {name: importlib.import_module(PACKAGE+'.'+name) for name in
            ('world', 'resources', 'context', 'prompts', 'integrity')}


def runtime_manifest(path):
    path = Path(path).resolve()
    value = json.loads(path.read_text())
    if value.get('schema') != 'b720-linux-runtime-v1' or value.get('dedicated_runtime') is not True:
        raise RuntimeError('unqualified_runtime_manifest')
    for key in ('python', 'base_prefix', 'environment_prefix', 'scientific_path'):
        location = Path(value[key]).resolve()
        if str(location) != value[key] or location in (Path('/'),Path('/home'),Path('/project')):
            raise RuntimeError('unsafe_runtime_path:' + key)
    python = Path(value['python'])
    if not python.is_file() or digest(python) != value['python_sha256']:
        raise RuntimeError('runtime_interpreter_changed')
    if not any(python.is_relative_to(Path(value[key])) for key in ('base_prefix','environment_prefix')):
        raise RuntimeError('interpreter_outside_dedicated_prefixes')
    site = Path(value['scientific_path'])
    if not (site/'numpy').is_dir() or not (site/'scipy').is_dir():
        raise RuntimeError('scientific_libraries_missing')
    if tuple(value['python_version'][:2]) < (3,11):
        raise RuntimeError('Python_3_11_or_newer_required')
    if value['numpy_version'] != '2.2.2' or value['scipy_version'] != '1.17.1':
        raise RuntimeError('scientific_library_versions_changed')
    return value, digest(path)


def capture_runtime(destination):
    """Explicit selected-host metadata action; no worker, model or world."""
    import numpy, scipy
    value = {'schema':'b720-linux-runtime-v1', 'dedicated_runtime':True,
        'python':str(Path(sys.executable).resolve()),
        'python_sha256':digest(Path(sys.executable).resolve()),
        'base_prefix':str(Path(sys.base_prefix).resolve()),
        'environment_prefix':str(Path(sys.prefix).resolve()),
        'scientific_path':str(Path(numpy.__file__).resolve().parent.parent),
        'python_version':list(sys.version_info[:3]),
        'numpy_version':numpy.__version__, 'scipy_version':scipy.__version__,
        'scope':'Runtime metadata only; actual isolated import/action checks still required.'}
    if Path(scipy.__file__).resolve().parent.parent != Path(value['scientific_path']):
        raise RuntimeError('numpy_scipy_must_share_dedicated_site')
    Path(destination).write_text(json.dumps(value,indent=2)+'\n')
    return value
