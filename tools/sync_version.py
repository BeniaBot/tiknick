# -*- coding: utf-8 -*-
"""
Single source of truth for the version number: main.py's APP_VERSION.

installer.iss carried its own hand-written `#define AppVersion` and drifted to
0.8.15 while the app was already at 0.8.23 — so "Apps & features" showed the
wrong version and the installer's own DisableDirPage/upgrade notes lied. The
number now flows one way: main.py -> version_info.txt -> installer.iss.

Run standalone (`python tools/sync_version.py`) to rewrite both files;
`--check` only reports drift (that's what the test suite calls).
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    return io.open(os.path.join(ROOT, name), encoding="utf-8").read()


def _write(name, text):
    io.open(os.path.join(ROOT, name), "w", encoding="utf-8", newline="").write(text)


def app_version():
    m = re.search(r'^APP_VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
                  _read("main.py"), re.M)
    if not m:
        raise SystemExit("APP_VERSION not found in main.py")
    return m.group(1)


def _targets(ver):
    a, b, c = ver.split(".")
    quad = "%s.%s.%s.0" % (a, b, c)
    tup = "(%s, %s, %s, 0)" % (a, b, c)

    vi = _read("version_info.txt")
    vi = re.sub(r"filevers=\([^)]*\)", "filevers=" + tup, vi)
    vi = re.sub(r"prodvers=\([^)]*\)", "prodvers=" + tup, vi)
    vi = re.sub(r"StringStruct\('FileVersion', '[^']*'\)",
                "StringStruct('FileVersion', '%s')" % quad, vi)
    vi = re.sub(r"StringStruct\('ProductVersion', '[^']*'\)",
                "StringStruct('ProductVersion', '%s')" % quad, vi)

    iss = _read("installer.iss")
    iss = re.sub(r'#define AppVersion "[^"]*"',
                 '#define AppVersion "%s"' % ver, iss)
    return {"version_info.txt": vi, "installer.iss": iss}


def check():
    """Returns a list of files whose version does not match main.py."""
    ver = app_version()
    return [n for n, new in _targets(ver).items() if _read(n) != new]


def main():
    ver = app_version()
    if "--check" in sys.argv:
        bad = check()
        if bad:
            print("version drift (main.py is %s): %s" % (ver, ", ".join(bad)))
            return 1
        print("version %s is in sync" % ver)
        return 0
    for name, new in _targets(ver).items():
        if _read(name) != new:
            _write(name, new)
            print("updated", name, "->", ver)
        else:
            print(name, "already", ver)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
