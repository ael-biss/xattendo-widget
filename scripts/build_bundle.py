#!/usr/bin/env python3
"""
Builds a single self-contained executable bundle (dist/xattendo-widget.pyz).
Compiles all Python modules to bytecode (.pyc) so no .py source files are shipped,
and embeds assets (xattendo.svg, xattendo_done.svg, xattendo_alert.svg) inside the archive.
"""

import os
import py_compile
import shutil
import tempfile
import zipfile

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(REPO_DIR, 'dist')
OUT_FILE = os.path.join(DIST_DIR, 'xattendo-widget.pyz')


def build() -> None:
    os.makedirs(DIST_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage_dir = os.path.join(tmp, 'stage')
        os.makedirs(stage_dir)

        # Compile xattendo_widget package to bytecode (.pyc only, no .py source)
        pkg_src = os.path.join(REPO_DIR, 'xattendo_widget')
        for root, dirs, files in os.walk(pkg_src):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            rel_root = os.path.relpath(root, REPO_DIR)
            out_root = os.path.join(stage_dir, rel_root)
            os.makedirs(out_root, exist_ok=True)
            for fname in files:
                if fname.endswith('.py'):
                    src_py = os.path.join(root, fname)
                    out_pyc = os.path.join(out_root, fname + 'c')
                    py_compile.compile(src_py, cfile=out_pyc, doraise=True, optimize=2)

        # Compile run.py as __main__.pyc entrypoint
        py_compile.compile(
            os.path.join(REPO_DIR, 'run.py'),
            cfile=os.path.join(stage_dir, '__main__.pyc'),
            doraise=True,
            optimize=2,
        )

        # Copy runtime SVG assets
        runtime_assets = ('xattendo.svg', 'xattendo_done.svg', 'xattendo_alert.svg')
        out_assets = os.path.join(stage_dir, 'assets')
        os.makedirs(out_assets, exist_ok=True)
        for asset_name in runtime_assets:
            shutil.copy2(os.path.join(REPO_DIR, 'assets', asset_name), os.path.join(out_assets, asset_name))

        # Pack into executable .pyz with #!/usr/bin/env python3 shebang
        with open(OUT_FILE, 'wb') as out_f:
            out_f.write(b'#!/usr/bin/env python3\n')
            with zipfile.ZipFile(out_f, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(stage_dir):
                    for fname in sorted(files):
                        full = os.path.join(root, fname)
                        arcname = os.path.relpath(full, stage_dir)
                        zf.write(full, arcname)

    os.chmod(OUT_FILE, 0o755)
    size_kb = os.path.getsize(OUT_FILE) / 1024.0
    print(f'✔ Built standalone bundle: {OUT_FILE} ({size_kb:.1f} KB, bytecode-only, no .py source)')


if __name__ == '__main__':
    build()
