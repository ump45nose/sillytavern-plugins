"""Offline packaging contract for independent MoviePilot plugins and Theme worker."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tomllib


def check(root: Path) -> None:
    manifest = json.loads((root / 'package.v2.json').read_text())
    assert {'FilmWatchlist', 'MediaCapabilities', 'ThemeStudio', 'MediaArchive', 'DiscRemux'} <= set(manifest)
    for identity, directory in [('FilmWatchlist', 'filmwatchlist'), ('ThemeStudio', 'themestudio'),
                                ('MediaArchive', 'mediaarchive'), ('DiscRemux', 'discremux'),
                                ('MediaCapabilities', 'mediacapabilities')]:
        plugin = root / 'plugins.v2' / directory
        assert plugin.is_dir() and not plugin.is_symlink()
        module = ast.parse((plugin / '__init__.py').read_text())
        cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == identity)
        assignments = {target.id: ast.literal_eval(node.value) for node in cls.body
                       if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                       for target in node.targets if isinstance(target, ast.Name)}
        assert assignments['plugin_version'] == manifest[identity]['version']
        assert assignments['plugin_config_prefix'] == directory + '_'
        if identity in {'MediaArchive', 'DiscRemux'}:
            assert (plugin / 'dist' / 'remoteEntry.js').is_file()
            tree = ast.parse((plugin / 'workflow.py').read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or '').startswith(('app.', 'httpx', 'subprocess', 'pathlib'))
    app = root / 'apps' / 'emby-theme-worker'
    project = tomllib.loads((app / 'pyproject.toml').read_text())
    assert project['project']['name'] == 'emby-theme-worker'
    assert project['project']['scripts']['emby-theme-worker'] == 'emby_theme_worker.cli:main'
    assert not any('moviepilot' in dependency.lower() for dependency in project['project']['dependencies'])
    for path in (app / 'emby_theme_worker').glob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(('app.plugins', 'filmwatchlist'))
    assert (app / 'moviepilot' / 'plugins.v2' / 'themestudio').resolve() == root / 'plugins.v2' / 'themestudio'
    assert (app / 'moviepilot' / 'frontend').resolve() == root / 'frontends' / 'theme-studio'
    assert (app / 'moviepilot' / 'package.v2.json').resolve() == root / 'package.v2.json'
    assert (root / 'plugins.v2' / 'themestudio' / 'dist' / 'remoteEntry.js').is_file()
    assert "new URL('../../plugins.v2/themestudio/dist', import.meta.url)" in (root / 'frontends/theme-studio/vite.config.js').read_text()
    # Independent build contexts still contain their ordinary COPY inputs.
    for name in ('Dockerfile', 'compose.yaml', 'README.md', 'requirements.lock',
                 'requirements-audio.lock', 'config/config.yaml'):
        assert (app / name).is_file()
    print('Media layout contracts: OK')


if __name__ == '__main__':
    check(Path(__file__).resolve().parents[1])
