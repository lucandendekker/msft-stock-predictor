from pathlib import Path
import importlib.util


def test_apt_package_list_uses_unix_newlines(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'tools/package_space.py'
    spec = importlib.util.spec_from_file_location('package_space', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = module.package(tmp_path / 'upload')
    assert (destination / 'packages.txt').read_bytes() == b'libgomp1\n'
