"""PiDash startup support; private data is never downloaded from Git."""
from pathlib import Path, PurePosixPath
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import venv
import zipfile

CODE_ROOT = Path(__file__).resolve().parent


def prepare_runtime():
    """PiDash may launch system Python. Re-exec in the project's own venv."""
    if os.name != 'posix':
        return
    env = CODE_ROOT / '.venv'
    python = env / 'bin/python'
    requirements = CODE_ROOT / 'requirements.txt'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = env / '.house-requirements'
    if not python.exists():
        print('Preparing the house Python environment.', flush=True)
        venv.EnvBuilder(with_pip=True).create(env)
    if not stamp.exists() or stamp.read_text().strip() != digest:
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], check=True)
        stamp.write_text(digest, encoding='ascii')
    if Path(sys.prefix).resolve() != env.resolve():
        os.execv(str(python), [str(python), str(CODE_ROOT / 'app.py')])


def restore_seed(archive, target):
    """Install a bounded data-only archive once, without overwriting live data."""
    archive, target = Path(archive), Path(target)
    if (target / 'data/project.json').is_file() or not archive.is_file():
        return False
    if target.exists():
        if target.is_symlink() or any(target.iterdir()):
            raise ValueError('The private directory already contains files; refusing to overwrite it.')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.house-seed-', dir=target.parent))
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > 100 or sum(e.file_size for e in entries) > 200 * 1024 * 1024:
                raise ValueError('Private archive is too large.')
            seen = set()
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                if (entry.orig_filename != name or '\\' in name or path.is_absolute() or '..' in path.parts or ':' in name
                        or not path.parts or path.parts[0] not in {'data', 'source'}
                        or name in seen or stat.S_ISLNK(entry.external_attr >> 16)):
                    raise ValueError('Unsafe private archive entry.')
                seen.add(name)
                if entry.is_dir():
                    if len(path.parts) != 1:
                        raise ValueError('Unexpected archive directory.')
                    continue
                allowed = name in {'data/project.json', 'data/plot.json'} or (
                    len(path.parts) == 2 and path.parts[0] == 'source'
                    and path.suffix.lower() in {'.dxf', '.png', '.jpg', '.jpeg', '.webp'})
                if not allowed or entry.file_size > 100 * 1024 * 1024:
                    raise ValueError('Unexpected private archive file.')
                destination = staging.joinpath(*path.parts)
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with bundle.open(entry) as src, destination.open('xb') as out:
                    shutil.copyfileobj(src, out)
                destination.chmod(0o600)
        if not all((staging / 'data' / name).is_file() for name in ('project.json', 'plot.json')):
            raise ValueError('Private archive is missing project configuration.')
        # Rename only after the entire archive passes validation. Existing files are never replaced.
        if target.exists():
            target.rmdir()  # Only the verified empty directory above can be removed.
        staging.rename(target)
        target.chmod(0o700)
        return True
    finally:
        if staging.exists():
            shutil.rmtree(staging)
