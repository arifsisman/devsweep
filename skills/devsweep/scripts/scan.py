#!/usr/bin/env python3
"""DevSweep scanner: detect developer ecosystems, measure their disk footprint,
attribute artifacts to projects, and emit JSON for Claude to reason about.

This script only reads the filesystem. It never deletes anything.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
import sys
import time
from pathlib import Path

HOME = Path.home()

# ---------------------------------------------------------------- catalog ---

# Artifact directories identified by name alone. The owning project's markers
# still decide the ecosystem label where the name is ambiguous.
#   name -> (ecosystem, what, regenerate, risk)
SPECIFIC_DIRS = {
    "node_modules":    ("js", "installed dependencies", "install from lockfile", "SAFE"),
    ".next":           ("js", "Next.js build + cache", "next build", "SAFE"),
    ".nuxt":           ("js", "Nuxt build", "nuxt build", "SAFE"),
    ".svelte-kit":     ("js", "SvelteKit build", "next build", "SAFE"),
    ".angular":        ("js", "Angular cache", "rebuilt automatically", "SAFE"),
    ".nx":             ("js", "Nx task cache", "rebuilt automatically", "SAFE"),
    ".turbo":          ("js", "Turborepo cache", "rebuilt automatically", "SAFE"),
    ".parcel-cache":   ("js", "Parcel cache", "rebuilt automatically", "SAFE"),
    ".vite":           ("js", "Vite cache", "rebuilt automatically", "SAFE"),
    ".nyc_output":     ("js", "coverage intermediates", "re-run tests", "SAFE"),
    "coverage":        ("js", "coverage report", "re-run tests", "SAFE"),
    ".dart_tool":      ("flutter", "Dart tool cache", "flutter pub get", "SAFE"),
    ".gradle":         ("gradle", "project Gradle state", "rebuilt automatically", "SAFE"),
    "DerivedData":     ("xcode", "build intermediates", "next build", "SAFE"),
    "Pods":            ("cocoapods", "CocoaPods dependencies", "pod install", "SAFE"),
    ".build":          ("swift", "SwiftPM build", "swift build", "SAFE"),
    "__pycache__":     ("python", "bytecode", "regenerated on import", "SAFE"),
    ".pytest_cache":   ("python", "pytest cache", "regenerated", "SAFE"),
    ".mypy_cache":     ("python", "mypy cache", "regenerated", "SAFE"),
    ".ruff_cache":     ("python", "ruff cache", "regenerated", "SAFE"),
    ".tox":            ("python", "tox environments", "tox recreates", "SAFE"),
    ".venv":           ("python", "virtual environment", "install from manifest", "SAFE"),
    "venv":            ("python", "virtual environment", "install from manifest", "SAFE"),
    ".terraform":      ("terraform", "provider plugins", "terraform init", "SAFE"),
    ".godot":          ("godot", "import cache", "reimport on open", "SAFE"),
    ".import":         ("godot", "import cache", "reimport on open", "SAFE"),
    "DerivedDataCache": ("unreal", "derived data cache", "rebuilt, very slow", "REVIEW"),
    "Intermediate":    ("unreal", "build intermediates", "rebuild", "REVIEW"),
    ".eslintcache":    ("js", "eslint cache", "regenerated", "SAFE"),
}

# Ambiguous names: only reported when the owning project declares a matching
# ecosystem, because "build" and "target" mean different things everywhere.
#   name -> {ecosystem: (what, regenerate, risk)}
AMBIGUOUS_DIRS = {
    "build": {
        "js":      ("build output", "project build script", "SAFE"),
        "gradle":  ("Gradle build output", "./gradlew build", "SAFE"),
        "flutter": ("Flutter build output", "flutter build", "SAFE"),
        "python":  ("packaging output", "rebuild", "SAFE"),
        "unity":   ("player build", "rebuild", "SAFE"),
    },
    "dist": {
        "js":     ("build output", "project build script", "SAFE"),
        "python": ("packaging output", "rebuild", "SAFE"),
    },
    "out": {
        "js": ("build output", "project build script", "SAFE"),
    },
    "target": {
        "rust":  ("Cargo build output", "cargo build", "SAFE"),
        "maven": ("Maven build output", "mvn package", "SAFE"),
    },
    "bin": {
        "dotnet": ("build output", "dotnet build", "SAFE"),
    },
    "obj": {
        "dotnet": ("build intermediates", "dotnet build", "SAFE"),
    },
    "Library": {
        "unity": ("import cache", "reimport on open, slow", "REVIEW"),
    },
    "Temp": {
        "unity": ("scratch", "recreated", "SAFE"),
    },
    "Binaries": {
        "unreal": ("compiled output", "rebuild", "SAFE"),
    },
    "Builds": {
        "unity": ("player builds", "rebuild", "SAFE"),
    },
}

# Files whose presence identifies a project root and its ecosystem.
PROJECT_MARKERS = [
    ("package.json",      "js"),
    ("Cargo.toml",        "rust"),
    ("go.mod",            "go"),
    ("pom.xml",           "maven"),
    ("build.gradle",      "gradle"),
    ("build.gradle.kts",  "gradle"),
    ("settings.gradle",   "gradle"),
    ("pubspec.yaml",      "flutter"),
    ("Podfile",           "cocoapods"),
    ("Package.swift",     "swift"),
    ("pyproject.toml",    "python"),
    ("requirements.txt",  "python"),
    ("Pipfile",           "python"),
    ("environment.yml",   "python"),
    ("Gemfile",           "ruby"),
    ("project.godot",     "godot"),
    ("Makefile",          "make"),
    ("CMakeLists.txt",    "cmake"),
]

MARKER_SUFFIXES = [
    (".xcodeproj",  "xcode"),
    (".xcworkspace", "xcode"),
    (".csproj",     "dotnet"),
    (".sln",        "dotnet"),
    (".uproject",   "unreal"),
    (".tf",         "terraform"),
]

LOCKFILES = {
    "js":        ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock"],
    "rust":      ["Cargo.lock"],
    "go":        ["go.sum"],
    "flutter":   ["pubspec.lock"],
    "cocoapods": ["Podfile.lock"],
    "ruby":      ["Gemfile.lock"],
    "python":    ["poetry.lock", "uv.lock", "Pipfile.lock", "requirements.txt"],
    "swift":     ["Package.resolved"],
}

# Global caches: (label, path, ecosystem, what, regenerate, native cleanup, risk)
GLOBAL_CACHES = [
    ("npm cache",          "~/.npm/_cacache", "js", "npm download cache", "re-downloaded", "npm cache clean --force", "SAFE"),
    ("yarn cache",         "~/Library/Caches/Yarn", "js", "yarn v1 cache", "re-downloaded", "yarn cache clean", "SAFE"),
    ("yarn berry cache",   "~/.yarn/berry/cache", "js", "yarn berry cache", "re-downloaded", "yarn cache clean", "SAFE"),
    ("pnpm store",         "~/Library/pnpm/store", "js", "pnpm content store", "re-downloaded for every project", "pnpm store prune", "REVIEW"),
    ("pnpm store",         "~/.local/share/pnpm/store", "js", "pnpm content store", "re-downloaded for every project", "pnpm store prune", "REVIEW"),
    ("npx cache",          "~/.npm/_npx", "js", "packages fetched by npx", "re-downloaded on next npx", None, "SAFE"),
    ("bun cache",          "~/.bun/install/cache", "js", "bun cache", "re-downloaded", "bun pm cache rm", "SAFE"),
    ("Playwright browsers", "~/Library/Caches/ms-playwright", "js", "browser binaries", "npx playwright install", None, "REVIEW"),
    ("Electron cache",     "~/Library/Caches/electron", "js", "Electron binaries", "re-downloaded", None, "REVIEW"),
    ("Puppeteer cache",    "~/.cache/puppeteer", "js", "Chromium build", "re-downloaded", None, "REVIEW"),

    ("Simulator runtime mount points", "/Library/Developer/CoreSimulator/Volumes", "xcode", "MOUNT POINTS ONLY: each is a mounted read-only volume from an image below; deleting these frees nothing", "not applicable", "xcrun simctl runtime delete <id>", "REVIEW"),
    ("Simulator system caches", "/Library/Developer/CoreSimulator/Caches", "xcode", "system-level simulator caches", "rebuilt", None, "SAFE"),
    ("SwiftUI Previews", "~/Library/Developer/Xcode/UserData/Previews", "xcode", "preview build cache", "rebuilt on next preview", None, "SAFE"),
    ("Xcode DerivedData",  "~/Library/Developer/Xcode/DerivedData", "xcode", "build intermediates and indexes", "next build", None, "SAFE"),
    ("iOS DeviceSupport",  "~/Library/Developer/Xcode/iOS DeviceSupport", "xcode", "symbols per device iOS version", "re-copied when that device connects", None, "REVIEW"),
    ("watchOS DeviceSupport", "~/Library/Developer/Xcode/watchOS DeviceSupport", "xcode", "symbols per device version", "re-copied on connect", None, "REVIEW"),
    ("tvOS DeviceSupport", "~/Library/Developer/Xcode/tvOS DeviceSupport", "xcode", "symbols per device version", "re-copied on connect", None, "REVIEW"),
    ("Xcode Archives",     "~/Library/Developer/Xcode/Archives", "xcode", "shipped builds and dSYMs", "CANNOT be regenerated", None, "DANGEROUS"),
    ("Xcode Products",     "~/Library/Developer/Xcode/Products", "xcode", "build products", "rebuild", None, "SAFE"),
    ("Xcode cache",        "~/Library/Caches/com.apple.dt.Xcode", "xcode", "Xcode internal cache", "rebuilt", None, "SAFE"),
    ("Simulator devices",  "~/Library/Developer/CoreSimulator/Devices", "xcode", "simulators and their app data", "recreated empty", "xcrun simctl delete unavailable", "REVIEW"),
    ("Simulator runtimes", "~/Library/Developer/CoreSimulator/Profiles/Runtimes", "xcode", "downloaded OS runtimes", "re-downloaded from Apple, slow", None, "REVIEW"),
    ("Simulator caches",   "~/Library/Developer/CoreSimulator/Caches", "xcode", "simulator caches", "rebuilt", None, "SAFE"),
    ("CocoaPods cache",    "~/Library/Caches/CocoaPods", "cocoapods", "pod download cache", "re-downloaded", "pod cache clean --all", "SAFE"),
    ("CocoaPods specs",    "~/.cocoapods/repos", "cocoapods", "spec repositories", "pod repo update, slow", None, "REVIEW"),
    ("SwiftPM cache",      "~/Library/Caches/org.swift.swiftpm", "swift", "SwiftPM dependency cache", "re-cloned", None, "SAFE"),
    ("Provisioning profiles", "~/Library/MobileDevice/Provisioning Profiles", "xcode", "code signing profiles", "re-downloaded, may break signing", None, "DANGEROUS"),

    ("Gradle caches",      "~/.gradle/caches", "gradle", "dependency and build cache", "re-downloaded and rebuilt", None, "SAFE"),
    ("Gradle wrappers",    "~/.gradle/wrapper/dists", "gradle", "Gradle distributions", "re-downloaded on next wrapper run", None, "REVIEW"),
    ("Android AVDs",       "~/.android/avd", "android", "emulators and their data", "recreated empty", None, "REVIEW"),
    ("Android system images", "~/Library/Android/sdk/system-images", "android", "emulator images", "re-downloaded", None, "REVIEW"),
    ("Android NDK",        "~/Library/Android/sdk/ndk", "android", "native toolchains", "re-downloaded", None, "REVIEW"),
    ("Android platforms",  "~/Library/Android/sdk/platforms", "android", "compile SDKs", "re-downloaded", None, "REVIEW"),
    ("Android build-tools", "~/Library/Android/sdk/build-tools", "android", "build tools", "re-downloaded", None, "REVIEW"),

    ("pub cache",          "~/.pub-cache", "flutter", "Dart package cache", "flutter pub get re-downloads for all projects", "dart pub cache clean", "REVIEW"),

    ("pip cache",          "~/Library/Caches/pip", "python", "wheel cache", "re-downloaded", "pip cache purge", "SAFE"),
    ("uv cache",           "~/.cache/uv", "python", "uv cache", "re-downloaded", "uv cache prune", "SAFE"),
    ("uv cache",           "~/Library/Caches/uv", "python", "uv cache", "re-downloaded", "uv cache prune", "SAFE"),
    ("Poetry cache",       "~/Library/Caches/pypoetry", "python", "Poetry cache and virtualenvs", "recreated", "poetry cache clear --all .", "REVIEW"),
    ("Hugging Face cache", "~/.cache/huggingface", "python", "model weights and datasets", "re-downloaded, often many GB and slow", None, "REVIEW"),
    ("PyTorch hub cache",  "~/.cache/torch", "python", "model weights", "re-downloaded", None, "REVIEW"),
    ("conda packages",     "~/miniconda3/pkgs", "python", "conda package cache", "re-downloaded", "conda clean --all", "SAFE"),

    ("Cargo registry",     "~/.cargo/registry", "rust", "crate sources and archives", "re-downloaded", None, "SAFE"),
    ("Cargo git deps",     "~/.cargo/git", "rust", "git dependencies", "re-cloned", None, "SAFE"),
    ("rustup toolchains",  "~/.rustup/toolchains", "rust", "installed toolchains", "rustup toolchain install", None, "REVIEW"),

    ("Go module cache",    "~/go/pkg/mod", "go", "module cache (read-only)", "go mod download", "go clean -modcache", "SAFE"),
    ("Go build cache",     "~/Library/Caches/go-build", "go", "build cache", "rebuilt", "go clean -cache", "SAFE"),

    ("Maven repository",   "~/.m2/repository", "maven", "local repository, may hold internal artifacts", "re-downloaded if public", None, "REVIEW"),
    ("Coursier cache",     "~/Library/Caches/Coursier", "maven", "Scala dependency cache", "re-downloaded", None, "SAFE"),
    ("sbt cache",          "~/.sbt", "maven", "sbt state", "re-downloaded", None, "SAFE"),
    ("Ivy cache",          "~/.ivy2/cache", "maven", "Ivy cache", "re-downloaded", None, "SAFE"),
    ("SDKMAN candidates",  "~/.sdkman/candidates", "maven", "installed JDKs and tools", "re-installed", None, "REVIEW"),

    ("Gem home",           "~/.gem", "ruby", "installed gems", "gem install", "gem cleanup", "REVIEW"),
    ("Gem home",           "~/.local/share/gem", "ruby", "installed gems", "gem install", "gem cleanup", "REVIEW"),
    ("Bundler cache",      "~/.bundle/cache", "ruby", "bundler cache", "re-downloaded", None, "SAFE"),
    ("rbenv versions",     "~/.rbenv/versions", "ruby", "Ruby installations", "re-installed, slow compile", None, "REVIEW"),

    ("NuGet packages",     "~/.nuget/packages", "dotnet", "global package cache", "re-downloaded", "dotnet nuget locals all --clear", "SAFE"),

    ("Homebrew cache",     "~/Library/Caches/Homebrew", "homebrew", "downloaded bottles", "re-downloaded", "brew cleanup -s", "SAFE"),
    ("ccache",             "~/Library/Caches/ccache", "native", "C/C++ compile cache", "rebuilt", "ccache -C", "SAFE"),
    ("ccache",             "~/.ccache", "native", "C/C++ compile cache", "rebuilt", "ccache -C", "SAFE"),
    ("sccache",            "~/.cache/sccache", "native", "shared compile cache", "rebuilt", None, "SAFE"),
    ("nvm versions",       "~/.nvm/versions", "js", "installed Node versions", "nvm install", None, "REVIEW"),
    ("asdf installs",      "~/.asdf/installs", "native", "installed tool versions", "re-installed", None, "REVIEW"),

    ("VS Code caches",     "~/Library/Application Support/Code/CachedData", "editor", "VS Code cached data", "rebuilt", None, "SAFE"),
    ("VS Code extension VSIXs", "~/Library/Application Support/Code/CachedExtensionVSIXs", "editor", "downloaded extension archives", "re-downloaded", None, "SAFE"),
    ("VS Code workspace storage", "~/Library/Application Support/Code/User/workspaceStorage", "editor", "per-workspace state", "partially recreated", None, "REVIEW"),
    ("VS Code local history", "~/Library/Application Support/Code/User/History", "editor", "local file history", "CANNOT be regenerated", None, "DANGEROUS"),
    ("VS Code extensions", "~/.vscode/extensions", "editor", "installed extensions", "reinstalled", None, "REVIEW"),
    ("JetBrains caches",   "~/Library/Caches/JetBrains", "editor", "IDE indexes", "reindexed on open, slow", None, "SAFE"),
    ("JetBrains logs",     "~/Library/Logs/JetBrains", "editor", "IDE logs", "recreated", None, "SAFE"),

    ("Codex state",        "~/.codex", "ai-tools", "Codex CLI sessions and caches", "sessions are not regenerable", None, "REVIEW"),
    ("Gemini / Antigravity state", "~/.gemini", "ai-tools", "Gemini CLI and Antigravity IDE state, browser recordings", "conversations are not regenerable; recordings are", None, "REVIEW"),
    ("Cursor state",       "~/.cursor", "ai-tools", "Cursor extensions and state", "reinstalled", None, "REVIEW"),
    ("Claude app bundles", "~/Library/Application Support/Claude/vm_bundles", "ai-tools", "Claude desktop VM bundles", "re-downloaded by the app", None, "REVIEW"),
    ("Vagrant boxes",      "~/.vagrant.d/boxes", "vm", "Vagrant base boxes", "re-downloaded, large", None, "REVIEW"),
    ("minikube cache",     "~/.minikube/cache", "k8s", "cluster images", "re-downloaded", None, "SAFE"),
    ("Colima VM",          "~/.colima", "vm", "Linux VM disk images", "CANNOT be regenerated", None, "DANGEROUS"),
    ("Lima VMs",           "~/.lima", "vm", "Linux VM disk images", "CANNOT be regenerated", None, "DANGEROUS"),
    ("Docker Desktop data", "~/Library/Containers/com.docker.docker/Data", "docker", "Docker VM disk image", "see Docker section", None, "REVIEW"),
]

# Roots whose direct children get sized during discovery. Anything large that
# the catalog has no rule for still gets reported, so the report is complete
# rather than limited to what this file happens to know about.
DISCOVER_ROOTS = [
    "~", "~/Library", "~/Library/Caches", "~/Library/Application Support",
    "~/Library/Containers", "~/Library/Developer", "~/Library/Developer/Xcode",
    "~/Library/Developer/CoreSimulator", "/Library/Developer",
    "/Library/Developer/CoreSimulator", "~/.cache", "~/.local/share",
]

# Personal data DevSweep has no business measuring. Reported as not scanned.
DISCOVER_SKIP = {
    "Pictures", "Movies", "Music", "Photos Library.photoslibrary", "Mail",
    "Messages", "Photos", "CloudStorage", "Mobile Documents", "Group Containers",
    "Biome", "Safari", "Accounts", "Keychains", ".Trash", "Cookies", "Suggestions",
    "com.apple.mail", "com.apple.Photos", "IdentityServices", "PersonalizationPortrait",
}

# ecosystem -> command that proves the toolchain is installed
ECOSYSTEM_COMMANDS = {
    "js": ["node", "npm", "yarn", "pnpm", "bun", "deno"],
    "python": ["python3", "pip3", "uv", "poetry", "conda"],
    "rust": ["cargo", "rustup"],
    "go": ["go"],
    "maven": ["mvn", "java", "sbt"],
    "gradle": ["gradle"],
    "android": ["adb", "sdkmanager", "emulator"],
    "flutter": ["flutter", "dart"],
    "xcode": ["xcodebuild", "xcrun"],
    "cocoapods": ["pod"],
    "swift": ["swift"],
    "ruby": ["ruby", "bundle", "gem"],
    "dotnet": ["dotnet"],
    "docker": ["docker"],
    "homebrew": ["brew"],
    "terraform": ["terraform"],
    "native": ["ccache", "cmake"],
    "ai-tools": ["claude", "codex", "gemini", "cursor"],
}

DEFAULT_ROOTS = ["~/Projects", "~/projects", "~/code", "~/Code", "~/src",
                 "~/dev", "~/Developer", "~/repos", "~/work", "~/git", "~/Sites"]

# Never descend into these while looking for projects.
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".Trash", "Library", "Applications", "Photos Library.photoslibrary",
    "Pictures", "Movies", "Music", "Public", "Applications (Parallels)",
    ".cache", ".local", ".rustup", ".cargo", ".npm", ".gradle", ".m2", ".nvm",
    "node_modules",
}


# ------------------------------------------------------------------ utils ---

def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def human(n: int) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def du_sizes(paths: list[Path], timeout: int = 300, deadline: float | None = None) -> dict[str, int]:
    """Batched `du -skx`. Returns path string -> bytes; missing entries mean du failed.

    Plain `du`, deliberately: `du -x` looks like the right way to avoid walking
    into mounted volumes, but macOS firmlinks put /Library on a different device
    from its own children, so `-x` silently reports zero for real directories.
    Mount points are excluded by `size_excluding_mounts` instead, which knows the
    difference between a boundary that hides bytes and one that duplicates them.
    """
    out: dict[str, int] = {}
    if not paths:
        return out

    def one(path: Path) -> tuple[str, int | None]:
        if deadline and time.monotonic() > deadline:
            return str(path), None
        try:
            r = subprocess.run(["du", "-sk", "--", str(path)],
                               capture_output=True, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            return str(path), None
        for line in r.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2 and parts[1] == str(path):
                try:
                    return str(path), int(parts[0]) * 1024
                except ValueError:
                    break
        return str(path), None

    # Four workers roughly halves wall clock against a sequential walk; beyond
    # that the disk is the limit and extra threads only add contention.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for path_str, size in pool.map(one, paths):
            if size is not None:
                out[path_str] = size
    return out


def recent_mtime(path: Path, budget: int = 4000) -> float:
    """Newest mtime found by a bounded breadth-first sample of the tree.

    A directory's own mtime changes only when a direct child is created or
    removed, so content-addressed caches (npm, uv, pip, cargo) look untouched
    for years while receiving new files every day. Sampling a few thousand
    entries across the top levels catches real activity at a fixed cost.
    """
    best = 0.0
    queue: list[Path] = [path]
    seen = 0
    while queue and seen < budget:
        d = queue.pop(0)
        try:
            with os.scandir(d) as it:
                for e in it:
                    seen += 1
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if st.st_mtime > best:
                        best = st.st_mtime
                    if e.is_dir(follow_symlinks=False):
                        queue.append(Path(e.path))
                    if seen >= budget:
                        break
        except OSError:
            continue
    return best


# Entries that change without anyone doing work: opening a folder in Finder
# writes .DS_Store, a build daemon writes logs, a cache rewrites itself. Counting
# them makes a project abandoned two years ago look like it was touched today,
# which is the difference between a safe cleanup candidate and a wrong answer.
ACTIVITY_NOISE_NAMES = {
    ".DS_Store", ".localized", "Thumbs.db", ".Trash",
    "node_modules", "build", "dist", "out", "target", "bin", "obj",
    "Library", "Temp", "Logs", "logs", "DerivedData", "Pods", ".build",
    ".next", ".nuxt", ".angular", ".nx", ".turbo", ".parcel-cache", ".vite",
    ".gradle", ".dart_tool", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".venv", "venv", "coverage", ".terraform",
    ".idea", ".vscode", ".cache",
}
ACTIVITY_NOISE_SUFFIXES = (".log", ".pid", ".lock", ".tmp", ".swp")


def is_activity_noise(name: str) -> bool:
    return name in ACTIVITY_NOISE_NAMES or name.endswith(ACTIVITY_NOISE_SUFFIXES)


def newest_mtime(path: Path, limit: int = 200) -> float:
    """Most recent mtime among the top-level entries, ignoring noise."""
    best = 0.0
    try:
        for i, entry in enumerate(os.scandir(path)):
            if i >= limit:
                break
            if is_activity_noise(entry.name):
                continue
            try:
                best = max(best, entry.stat(follow_symlinks=False).st_mtime)
            except OSError:
                pass
    except OSError:
        pass
    return best


def project_activity(project: Path) -> tuple[float, str]:
    """Best guess at when someone last worked here. Returns (mtime, source)."""
    for rel, label in ((".git/HEAD", "git"), (".git/index", "git")):
        p = project / rel
        try:
            return p.stat().st_mtime, label
        except OSError:
            continue
    return newest_mtime(project), "files (noise filtered)"


def days_since(ts: float) -> int | None:
    if not ts:
        return None
    return int((time.time() - ts) / 86400)


def any_child_is_mount(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            return any(is_mount_point(e.path) for e in it if e.is_dir(follow_symlinks=False))
    except OSError:
        return False


def size_excluding_mounts(path: str) -> tuple[int | None, bool]:
    """Size a directory without counting mounted volumes inside it.

    macOS mounts each installed simulator runtime as a read-only APFS volume
    under /Library/Developer/CoreSimulator/Volumes. Walking into one reports the
    expanded contents (34 GB on a real machine) when the bytes on disk are a
    much smaller backing image counted elsewhere, and deleting the mount point
    frees nothing. Returns (bytes, contained_a_mount).
    """
    if is_mount_point(path):
        return 0, True
    try:
        children = [os.path.join(path, c) for c in os.listdir(path)]
    except OSError:
        return du_sizes([Path(path)]).get(path), False
    mounts = [c for c in children if is_mount_point(c)]
    if not mounts:
        return du_sizes([Path(path)]).get(path), False
    keep = [Path(c) for c in children if c not in mounts]
    sizes = du_sizes(keep)
    return sum(v for v in sizes.values() if v is not None), True


def is_mount_point(path: str) -> bool:
    try:
        return os.path.ismount(path)
    except OSError:
        return False


def dir_identity(path: str) -> tuple[int, int] | str:
    """Stable identity for a directory, falling back to its path if stat fails."""
    try:
        st = os.stat(path)
        return (st.st_dev, st.st_ino)
    except OSError:
        return os.path.realpath(path)


def dedupe_roots(roots: list[Path]) -> list[Path]:
    """Collapse roots that are really the same directory or nested inside another.

    macOS filesystems are case-insensitive by default, so ~/Projects and
    ~/projects are one directory reached by two names. Scanning both would
    double every number this tool reports, which is the one failure mode that
    makes the whole report untrustworthy.
    """
    # Identity by (device, inode) rather than by string: os.path.normcase is a
    # no-op on POSIX, so comparing lowercased paths would not catch this, and
    # hardlinked or symlinked roots would slip through a purely textual check.
    canonical: dict[tuple[int, int], Path] = {}
    for r in roots:
        try:
            real = os.path.realpath(r)
            st = os.stat(real)
        except OSError:
            continue
        if not os.path.isdir(real):
            continue
        canonical.setdefault((st.st_dev, st.st_ino), Path(real))
    paths = sorted(canonical.values(), key=lambda p: len(str(p)))
    kept: list[Path] = []
    for candidate in paths:
        if any(str(candidate).startswith(str(k).rstrip(os.sep) + os.sep) for k in kept):
            continue
        kept.append(candidate)
    return kept


def running_process_commands() -> str:
    """One `ps` snapshot. A node_modules that a live dev server is executing
    out of is not a cleanup candidate no matter how the numbers look."""
    try:
        r = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, timeout=10)
        return r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


def private_registry(project: Path) -> str | None:
    """Return a short reason if reinstalling would need a private registry or
    stored credentials, which makes 'just run npm ci' a much bigger promise."""
    for name in (".npmrc", ".yarnrc.yml", ".yarnrc", "bunfig.toml"):
        f = project / name
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        low = text.lower()
        if "_authtoken" in low or "_auth=" in low or "npmauthtoken" in low:
            return f"{name} carries an auth token"
        for line in low.splitlines():
            if "registry" in line and "=" in line and "registry.npmjs.org" not in line and "registry.yarnpkg.com" not in line:
                return f"{name} points at a non-public registry"
    return None


def detect_ecosystem(directory: Path) -> set[str]:
    """Which ecosystems does this directory look like a project root for?"""
    found: set[str] = set()
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return found
    names = {e.name for e in entries}
    for marker, eco in PROJECT_MARKERS:
        if marker in names:
            found.add(eco)
    for name in names:
        for suffix, eco in MARKER_SUFFIXES:
            if name.endswith(suffix):
                found.add(eco)
    if "ProjectSettings" in names and "Assets" in names:
        found.add("unity")
    return found


def find_lockfiles(project: Path, ecosystems: set[str]) -> list[str]:
    present = []
    for eco in ecosystems:
        for lf in LOCKFILES.get(eco, []):
            if (project / lf).exists():
                present.append(lf)
    return present


def gitignored(repo: Path, paths: list[Path]) -> set[str]:
    """Batch `git check-ignore`. A project declaring a path as ignored output is
    strong evidence the path is derivable."""
    if not paths or not (repo / ".git").exists():
        return set()
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "--stdin"],
            input="\n".join(str(p) for p in paths),
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


# --------------------------------------------------------------- scanning ---

def walk_projects(root: Path, max_depth: int, artifacts_out: list[dict],
                  seen_paths: set | None = None) -> None:
    """Walk `root` looking for project roots and their artifact directories.

    Pruning matters: once a node_modules is recorded we do not descend into it,
    which is the difference between a scan that takes seconds and one that takes
    an hour.
    """
    if seen_paths is None:
        seen_paths = set()
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = list(os.scandir(directory))
        except (OSError, PermissionError):
            continue

        ecosystems = detect_ecosystem(directory)
        subdirs = []
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            subdirs.append(entry)

        found_here: list[dict] = []
        descend: list[os.DirEntry] = []

        for entry in subdirs:
            name = entry.name
            if name in SPECIFIC_DIRS:
                eco, what, regen, risk = SPECIFIC_DIRS[name]
                found_here.append({"path": entry.path, "name": name, "ecosystem": eco,
                                   "what": what, "regenerate": regen, "risk": risk})
                continue
            if name in AMBIGUOUS_DIRS:
                options = AMBIGUOUS_DIRS[name]
                match = next((e for e in ecosystems if e in options), None)
                if match:
                    what, regen, risk = options[match]
                    found_here.append({"path": entry.path, "name": name, "ecosystem": match,
                                       "what": what, "regenerate": regen, "risk": risk})
                    continue
                # Ambiguous name with no matching project marker: not our business.
                if ecosystems:
                    continue
            if name in SKIP_DIRS or name.startswith("."):
                if name not in (".github",):
                    continue
            descend.append(entry)

        deduped = []
        for a in found_here:
            ident = dir_identity(a["path"])
            if ident in seen_paths:
                continue
            seen_paths.add(ident)
            deduped.append(a)
        found_here = deduped

        if found_here:
            activity, source = project_activity(directory)
            ignored = gitignored(directory, [Path(a["path"]) for a in found_here])
            for a in found_here:
                a["project"] = str(directory)
                a["project_ecosystems"] = sorted(ecosystems)
                a["project_lockfiles"] = find_lockfiles(directory, ecosystems)
                a["project_last_activity_days"] = days_since(activity)
                a["project_activity_source"] = source
                a["gitignored"] = a["path"] in ignored
                if "js" in ecosystems:
                    a["project_private_registry"] = private_registry(directory)
                artifacts_out.append(a)

        for entry in descend:
            stack.append((Path(entry.path), depth + 1))


def scan_globals(ecosystems: set[str] | None) -> list[dict]:
    results = []
    seen = set()
    for label, raw, eco, what, regen, native, risk in GLOBAL_CACHES:
        if ecosystems and eco not in ecosystems:
            continue
        path = expand(raw)
        if not path.exists() or str(path) in seen:
            continue
        seen.add(str(path))
        results.append({
            "label": label, "path": str(path), "ecosystem": eco, "what": what,
            "regenerate": regen, "native_cleanup": native, "risk": risk,
            "scope": "global",
        })
    return results


def discover_large(known_paths: list[str], project_roots: list[str],
                   min_bytes: int, budget_seconds: float = 120.0
                   ) -> tuple[list[dict], list[str], bool]:
    """Size the direct children of DISCOVER_ROOTS and return the big ones the
    catalog does not already account for.

    Skip a child when a catalog path lives inside it (a deeper root will look
    there) or when it lives inside a catalog path or a scanned project root
    (already counted). What remains is exactly the set the catalog would have
    missed: AI tool state, model caches, VM images, whatever ships next year.
    """
    known = [os.path.realpath(k) for k in known_paths + project_roots]
    candidates: list[Path] = []
    skipped_personal: list[str] = []
    seen_ids: set = set()
    for raw in DISCOVER_ROOTS:
        root = expand(raw)
        if not root.is_dir():
            continue
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if e.name in DISCOVER_SKIP:
                skipped_personal.append(e.path)
                continue
            real = os.path.realpath(e.path)
            if any(k == real or k.startswith(real + os.sep) for k in known):
                continue   # a catalog entry or project root is inside; handled elsewhere
            if any(real.startswith(k + os.sep) for k in known):
                continue   # already counted as part of something known
            if os.path.expanduser("~") == real or real in [os.path.expanduser(r) for r in DISCOVER_ROOTS]:
                continue   # it is itself a discovery root; its children get sized instead
            if is_mount_point(real) or any_child_is_mount(real):
                continue   # mounted volumes: their bytes live in a backing image counted elsewhere
            ident = dir_identity(real)
            if ident in seen_ids:
                continue
            seen_ids.add(ident)
            candidates.append(Path(real))
    deadline = time.monotonic() + budget_seconds
    sizes = du_sizes(candidates, timeout=600, deadline=deadline)
    # Only a real timeout counts as incomplete. Individual du failures are
    # normal (permission-denied system paths) and saying "incomplete" for those
    # would teach the reader to ignore the flag.
    incomplete = time.monotonic() > deadline
    found = []
    for c in candidates:
        b = sizes.get(str(c))
        if b is None or b < min_bytes:
            continue
        name = c.name.lower()
        if "cache" in name:
            hint = "name suggests a cache"
        elif c.parent == expand("~/Library/Containers"):
            hint = "sandboxed app container; may hold app data"
        elif c.parent == expand("~/Library/Application Support"):
            hint = "application state; often mixes caches with settings"
        elif name.startswith("."):
            hint = "hidden tool directory"
        else:
            hint = ""
        found.append({
            "path": str(c), "bytes": b, "size": human(b), "risk": "UNKNOWN",
            "scope": "uncatalogued", "hint": hint,
            "last_activity_days": days_since(recent_mtime(c, budget=800)),
        })
    found.sort(key=lambda x: x["bytes"], reverse=True)
    return found, sorted(set(skipped_personal)), incomplete


def detect_installed() -> dict:
    tools = {}
    for eco, commands in ECOSYSTEM_COMMANDS.items():
        present = [c for c in commands if shutil.which(c)]
        if present:
            tools[eco] = present
    return tools


def simulator_runtimes(timeout: int = 30) -> list[dict]:
    """Ask simctl where the installed runtime images actually live, and size those.

    Hardcoding the path does not survive: on one machine an iOS 18 runtime sits
    in /Library/Developer/CoreSimulator/Cryptex/Images while the iOS 26 runtime
    beside it lives under /System/Library/AssetsV2, because Apple moved the
    storage between releases. simctl knows where each one is, so ask it rather
    than guessing, and size the backing image rather than the mount it presents.
    """
    if not shutil.which("xcrun"):
        return []
    try:
        r = subprocess.run(["xcrun", "simctl", "runtime", "list", "-j"],
                           capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    entries = []
    for ident, info in (data.items() if isinstance(data, dict) else []):
        path = info.get("path")
        if not path:
            continue
        size = du_sizes([Path(path)]).get(path)
        entries.append({
            "label": f"Simulator runtime {info.get('runtimeIdentifier') or info.get('build') or ident}",
            "path": path,
            "ecosystem": "xcode",
            "what": "backing disk image for an installed simulator runtime",
            "regenerate": "re-downloaded via Xcode Settings > Components, multi-GB",
            "native_cleanup": f"xcrun simctl runtime delete {ident}",
            "risk": "REVIEW",
            "scope": "simulator-runtime",
            "build": info.get("build"),
            "state": info.get("state"),
            "bytes": size,
            "size": human(size) if size is not None else "?",
        })
    entries.sort(key=lambda e: e["bytes"] or 0, reverse=True)
    return entries


def docker_usage(timeout: int = 20) -> dict | None:
    if not shutil.which("docker"):
        return None
    try:
        r = subprocess.run(["docker", "system", "df", "-v", "--format", "json"],
                           capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return {"error": "docker daemon did not respond"}
    if r.returncode != 0:
        return {"error": (r.stderr or "docker error").strip()[:200]}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"raw": r.stdout[:4000]}


# ------------------------------------------------------------------- main ---

def main() -> int:
    ap = argparse.ArgumentParser(description="DevSweep scanner (read-only)")
    ap.add_argument("--detect", action="store_true", help="only report which ecosystems exist")
    ap.add_argument("--roots", nargs="*", default=None, help="project roots to scan")
    ap.add_argument("--project", default=None, help="scan a single project directory")
    ap.add_argument("--global-only", action="store_true", help="skip project scanning")
    ap.add_argument("--ecosystems", default=None, help="comma separated subset, e.g. js,xcode")
    ap.add_argument("--min-size-mb", type=float, default=10.0, help="hide candidates below this size")
    ap.add_argument("--max-depth", type=int, default=5, help="directory depth under each root")
    ap.add_argument("--include-docker", action="store_true", help="query the Docker daemon")
    ap.add_argument("--json", default=None, help="write JSON here instead of stdout")
    ap.add_argument("--no-discover", action="store_true", help="skip discovery of large uncatalogued directories")
    ap.add_argument("--discover-min-mb", type=float, default=500.0, help="report uncatalogued dirs at or above this size")
    ap.add_argument("--discover-budget", type=float, default=120.0, help="seconds to spend on discovery before stopping")
    args = ap.parse_args()

    eco_filter = set(args.ecosystems.split(",")) if args.ecosystems else None
    installed = detect_installed()

    if args.detect:
        report = {"installed": installed,
                  "global_paths_present": [g["label"] + " -> " + g["path"]
                                           for g in scan_globals(eco_filter)]}
        print(json.dumps(report, indent=2))
        return 0

    artifacts: list[dict] = []
    scanned_roots: list[str] = []
    if not args.global_only:
        if args.project:
            roots = [expand(args.project)]
        elif args.roots:
            roots = [expand(r) for r in args.roots]
        else:
            roots = [expand(r) for r in DEFAULT_ROOTS]
        seen_paths: set = set()
        for root in dedupe_roots(roots):
            scanned_roots.append(str(root))
            walk_projects(root, args.max_depth, artifacts, seen_paths)

    globals_found = scan_globals(eco_filter)

    if eco_filter:
        artifacts = [a for a in artifacts if a["ecosystem"] in eco_filter]

    # Size everything in one pass, mount-aware from the start. Checking for
    # mounts first matters for speed as well as accuracy: walking into the
    # simulator runtime volumes costs about 25 seconds and every byte it
    # returns is discarded afterwards.
    all_items = artifacts + globals_found
    mounted: dict[str, tuple[int | None, bool]] = {}
    plain: list[Path] = []
    for item in all_items:
        path = item["path"]
        if not os.path.isdir(path):
            plain.append(Path(path))
            continue
        if is_mount_point(path) or any_child_is_mount(path):
            mounted[path] = size_excluding_mounts(path)
        else:
            plain.append(Path(path))
    sizes = du_sizes(plain)
    for path, (corrected, _) in mounted.items():
        if corrected is not None:
            sizes[path] = corrected
    threshold = int(args.min_size_mb * 1024 * 1024)

    ps_snapshot = running_process_commands()
    for item in artifacts + globals_found:
        item["bytes"] = sizes.get(item["path"])
        item["size"] = human(item["bytes"]) if item["bytes"] is not None else "?"
        try:
            item["dir_mtime_days"] = days_since(Path(item["path"]).stat().st_mtime)
        except OSError:
            item["dir_mtime_days"] = None
        # Sampled activity is the number to trust; dir mtime is kept only so a
        # reader can see how misleading it would have been.
        item["last_activity_days"] = (
            days_since(recent_mtime(Path(item["path"]), budget=1500))
            if (item["bytes"] or 0) >= 50 * 1024 * 1024 else None)
        item["in_use_by_running_process"] = item["path"] in ps_snapshot
        item["contains_mounted_volumes"] = item["path"] in mounted

    artifacts = [a for a in artifacts if (a["bytes"] or 0) >= threshold]
    globals_found = [g for g in globals_found if (g["bytes"] or 0) >= threshold]

    # Group project artifacts by project so the report can show where space went.
    projects: dict[str, dict] = {}
    for a in artifacts:
        p = projects.setdefault(a["project"], {
            "path": a["project"],
            "ecosystems": a["project_ecosystems"],
            "lockfiles": a["project_lockfiles"],
            "last_activity_days": a["project_last_activity_days"],
            "activity_source": a["project_activity_source"],
            "artifacts": [],
            "bytes": 0,
        })
        p["artifacts"].append({k: a.get(k) for k in
                               ("path", "name", "ecosystem", "what", "regenerate",
                                "risk", "bytes", "size", "last_activity_days", "dir_mtime_days",
                                "gitignored", "in_use_by_running_process", "project_private_registry")})
        p["bytes"] += a["bytes"] or 0

    for p in projects.values():
        p["size"] = human(p["bytes"])
        p["artifacts"].sort(key=lambda x: x["bytes"] or 0, reverse=True)

    project_list = sorted(projects.values(), key=lambda p: p["bytes"], reverse=True)
    globals_found.sort(key=lambda g: g["bytes"] or 0, reverse=True)

    uncatalogued: list[dict] = []
    skipped_personal: list[str] = []
    discovery_incomplete = False
    if not args.no_discover:
        uncatalogued, skipped_personal, discovery_incomplete = discover_large(
            [g["path"] for g in scan_globals(None)] + [a["path"] for a in artifacts],
            scanned_roots, int(args.discover_min_mb * 1024 * 1024),
            budget_seconds=args.discover_budget)

    runtimes = simulator_runtimes() if (not eco_filter or "xcode" in eco_filter) else []

    totals = {"SAFE": 0, "REVIEW": 0, "DANGEROUS": 0, "UNKNOWN": 0}
    for item in artifacts + globals_found + uncatalogued + runtimes:
        totals[item["risk"]] = totals.get(item["risk"], 0) + (item["bytes"] or 0)

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "installed_ecosystems": installed,
        "scanned_roots": scanned_roots,
        "min_size_mb": args.min_size_mb,
        "totals_bytes": totals,
        "totals_human": {k: human(v) for k, v in totals.items()},
        "grand_total_bytes": sum(totals.values()),
        "grand_total_human": human(sum(totals.values())),
        "projects": project_list,
        "global_caches": globals_found,
        "simulator_runtimes": runtimes,
        "uncatalogued_large_dirs": uncatalogued,
        "personal_dirs_not_scanned": skipped_personal,
        "discovery_incomplete": discovery_incomplete,
        "note": "Risk values are defaults from the catalog; UNKNOWN entries need the "
                "three questions in SKILL.md. last_activity_days is a sampled content "
                "mtime and is the one to trust; dir_mtime_days is shown only for "
                "comparison. This script never deletes.",
    }

    if args.include_docker:
        result["docker"] = docker_usage()

    text = json.dumps(result, indent=2)
    if args.json:
        Path(args.json).write_text(text)
        print(f"wrote {args.json}")
        print(f"total {result['grand_total_human']}  "
              f"SAFE {result['totals_human']['SAFE']}  "
              f"REVIEW {result['totals_human']['REVIEW']}  "
              f"DANGEROUS {result['totals_human']['DANGEROUS']}")
        if runtimes:
            print(f"{len(runtimes)} simulator runtimes "
                  f"({human(sum(r['bytes'] or 0 for r in runtimes))})")
        print(f"{len(project_list)} projects, {len(globals_found)} global caches, "
              f"{len(uncatalogued)} uncatalogued dirs >= {args.discover_min_mb:g} MB "
              f"({result['totals_human']['UNKNOWN']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
