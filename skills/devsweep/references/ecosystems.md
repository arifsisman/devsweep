# Ecosystem catalog

Read only the sections for ecosystems the detect phase actually found.

Each entry gives: what the path holds, how it comes back, the native cleanup command where one exists, and the traps. Paths are macOS; Linux differences are noted inline. `~` is the user's home.

Default risk shown per entry is a starting point. Project activity overrides it: an artifact belonging to a repo whose HEAD moved this week is REVIEW no matter what the table says.

## Contents

- [JavaScript / TypeScript](#javascript--typescript)
- [Xcode / Apple platforms](#xcode--apple-platforms)
- [Android](#android)
- [Flutter / Dart](#flutter--dart)
- [Docker](#docker)
- [Python](#python)
- [Rust](#rust)
- [Go](#go)
- [Java / JVM](#java--jvm)
- [Ruby](#ruby)
- [.NET](#net)
- [Swift (non-Xcode)](#swift-non-xcode)
- [Game engines](#game-engines)
- [Infrastructure tools](#infrastructure-tools)
- [Package managers and system tools](#package-managers-and-system-tools)
- [AI coding tools](#ai-coding-tools)
- [Editors and IDEs](#editors-and-ides)
- [Patterns for unrecognized directories](#patterns-for-unrecognized-directories)

---

## JavaScript / TypeScript

Identify the package manager from the lockfile before proposing anything: `package-lock.json` → npm, `yarn.lock` → yarn, `pnpm-lock.yaml` → pnpm, `bun.lockb` / `bun.lock` → bun. The regeneration command differs and using the wrong one rewrites the lockfile, which is a real change to the repo.

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `<project>/node_modules` | Installed dependencies | `npm ci` / `yarn install --immutable` / `pnpm install --frozen-lockfile` / `bun install` | SAFE with lockfile, REVIEW without |
| `<project>/dist`, `build`, `out` | Build output | the project's build script | SAFE |
| `<project>/.next` | Next.js build + cache | `next build`; dev server rebuilds | SAFE |
| `<project>/.nuxt`, `.output` | Nuxt build | `nuxt build` | SAFE |
| `<project>/.svelte-kit` | SvelteKit build | next build or dev | SAFE |
| `<project>/.angular/cache` | Angular build cache | rebuilt automatically | SAFE |
| `<project>/.nx`, `.turbo` | Monorepo task cache | rebuilt automatically | SAFE |
| `<project>/.parcel-cache`, `.vite` | Bundler caches | rebuilt automatically | SAFE |
| `<project>/coverage`, `.nyc_output` | Test coverage output | re-run tests | SAFE |
| `<project>/.eslintcache`, `tsconfig.tsbuildinfo` | Incremental caches | rebuilt automatically | SAFE |
| `~/.npm/_cacache` | npm download cache | re-downloaded on demand | SAFE |
| `~/.npm/_npx` | Packages fetched by `npx` | re-downloaded on next `npx` | SAFE |
| `~/Library/Caches/Yarn`, `~/.cache/yarn` | yarn v1 cache | re-downloaded | SAFE |
| `~/.cache/yarn/berry`, `~/.yarn/berry/cache` | yarn berry cache | re-downloaded | SAFE |
| `~/Library/pnpm/store`, `~/.local/share/pnpm/store` | pnpm content-addressed store | re-downloaded | REVIEW |
| `~/.bun/install/cache` | bun cache | re-downloaded | SAFE |
| `~/.cache/ms-playwright`, `~/Library/Caches/ms-playwright` | Playwright browsers | `npx playwright install` | REVIEW |
| `~/.electron`, `~/Library/Caches/electron` | Electron binaries | re-downloaded on build | REVIEW |
| `~/.cache/puppeteer` | Chromium for Puppeteer | re-downloaded on install | REVIEW |

Native cleanup: `npm cache clean --force`, `yarn cache clean`, `pnpm store prune`, `bun pm cache rm`.

The pnpm store is REVIEW rather than SAFE for a reason: every pnpm project on the machine hardlinks into it, so pruning it while projects still reference it forces a full re-download across all of them. `pnpm store prune` removes only unreferenced content and is the right tool.

Deleting a `node_modules` that contains patched dependencies (look for `patches/` or a `postinstall` that edits files) means the patch has to reapply cleanly. Usually fine, occasionally not.

## Xcode / Apple platforms

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `~/Library/Developer/Xcode/DerivedData` | Build intermediates, indexes, module cache | next build; index rebuilds on open | SAFE |
| `~/Library/Developer/Xcode/UserData/Previews` | SwiftUI preview build cache | rebuilt on next preview | SAFE |
| Runtime images, location from `xcrun simctl runtime list -j` | Backing disk images for installed runtimes; the real footprint | Xcode Settings > Components re-downloads, multi-GB | REVIEW |
| `/Library/Developer/CoreSimulator/Caches` | System-level simulator caches | rebuilt | SAFE |
| `/Library/Developer/CoreSimulator/Volumes` | **Mount points, not storage.** Each is a mounted read-only APFS volume from an image above | nothing to regenerate | never a candidate |
| `~/Library/Developer/Xcode/iOS DeviceSupport` | Symbols from devices you attached | re-copied when that device connects | REVIEW |
| `~/Library/Developer/Xcode/watchOS DeviceSupport`, `tvOS DeviceSupport` | as above | as above | REVIEW |
| `~/Library/Developer/CoreSimulator/Caches` | Simulator caches | rebuilt | SAFE |
| `~/Library/Developer/CoreSimulator/Devices` | Simulator devices *and their installed app data* | recreated empty | REVIEW |
| `~/Library/Developer/CoreSimulator/Profiles/Runtimes` | Downloaded OS runtimes | re-downloaded from Apple, multi-GB, slow | REVIEW |
| `~/Library/Developer/Xcode/Archives` | Shipped builds + dSYMs | **cannot be regenerated** | DANGEROUS |
| `~/Library/Developer/Xcode/Products` | Build products | rebuild | SAFE |
| `~/Library/Caches/com.apple.dt.Xcode` | Xcode's own cache | rebuilt | SAFE |
| `~/Library/Developer/XCPGDevices` | Playground devices | recreated | SAFE |
| `<project>/Pods` | CocoaPods dependencies | `pod install` | SAFE with `Podfile.lock` |
| `~/Library/Caches/CocoaPods` | Pod download cache | re-downloaded | SAFE |
| `~/.cocoapods/repos` | Pod spec repos | `pod repo update`, slow clone | REVIEW |
| `<project>/.build` | SwiftPM build dir | `swift build` | SAFE |
| `~/Library/Caches/org.swift.swiftpm` | SwiftPM dependency cache | re-cloned | SAFE |
| `<project>/Carthage/Build` | Carthage output | `carthage bootstrap` | REVIEW |
| `~/Library/MobileDevice/Provisioning Profiles` | Provisioning profiles | re-downloaded, may break signing | DANGEROUS |

Native cleanup: `xcrun simctl delete unavailable` removes simulators whose runtime is gone, which is almost always pure win — but check `xcrun simctl list devices unavailable` first, because on a well-maintained machine it frees nothing and proposing it wastes the user's trust. `xcrun simctl runtime list` is the authority on installed runtimes and prints their true combined size; `xcrun simctl runtime delete <id>` is the only correct way to remove one.

Do not hardcode where runtime images live. On one machine an iOS 18 runtime sits under `/Library/Developer/CoreSimulator/Cryptex/Images` while the iOS 26 runtime beside it lives under `/System/Library/AssetsV2/com_apple_MobileAsset_iOSSimulatorRuntime`, because Apple moved the storage between releases and left the old one in place. A catalog that knows only one of those paths reports half the real number. `xcrun simctl runtime list -j` gives the exact path of each installed runtime; the scanner uses it and reports the results under `simulator_runtimes`.

Be careful with the arithmetic here, because the obvious measurement is wrong. `/Library/Developer/CoreSimulator/Volumes/iOS_*` are **mount points**: each is a read-only APFS volume mounted from a backing image under `Cryptex/Images`. A `du` that follows them reports the expanded contents, on a real machine 34 GB against an 8 GB backing image, so a report that lists both the volumes and the images has counted the same bytes twice and invented the difference. Deleting a mount point frees nothing. Size the images, quote `simctl runtime list`, and treat the mount paths as scenery. The scanner uses `du -x` for exactly this reason and sets `contains_mounted_volumes` on anything holding a mount. `xcodebuild -alltargets clean` for a single project. `pod cache clean --all`.

Archives are the one place in this catalog where the right answer is almost always "keep". They contain the dSYMs needed to symbolicate crash reports from builds already in users' hands. Losing them means losing the ability to debug production crashes for that version. If the user has App Store builds from the last year or two, say this explicitly rather than listing the size and moving on.

Simulator *devices* carry the app data of everything ever installed on them — sometimes the only copy of a test database or a login state someone set up by hand. Deleting unavailable ones is safe; wiping all devices is a REVIEW that should mention this.

DeviceSupport directories are per-iOS-version and reappear the next time you plug in a device running that version — which requires having the device. Old versions for devices the user no longer owns are effectively dead weight; current ones cost a slow re-sync.

## Android

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `~/.gradle/caches` | Gradle dependency + build cache | re-downloaded and rebuilt | SAFE |
| `~/.gradle/wrapper/dists` | Gradle distributions per version | re-downloaded on next wrapper run | REVIEW |
| `~/.gradle/daemon` | Daemon logs | recreated | SAFE |
| `<project>/.gradle` | Project-local Gradle state | recreated | SAFE |
| `<project>/build`, `<module>/build` | Build output | `./gradlew build` | SAFE |
| `~/.android/avd` | Emulator virtual devices **and their data** | recreated empty via AVD Manager | REVIEW |
| `~/Library/Android/sdk/system-images` | Emulator system images | re-downloaded, multi-GB | REVIEW |
| `~/Library/Android/sdk/platforms/android-NN` | Compile SDKs | re-downloaded | REVIEW |
| `~/Library/Android/sdk/build-tools/<ver>` | Build tools | re-downloaded | REVIEW |
| `~/Library/Android/sdk/ndk/<ver>` | NDK, very large | re-downloaded | REVIEW |
| `~/.android/build-cache` | Legacy build cache | rebuilt | SAFE |

Before proposing removal of any SDK platform, build-tools, or NDK version, check what the projects on this machine actually declare: grep `compileSdk`, `targetSdk`, `buildToolsVersion`, and `ndkVersion` across `build.gradle` files. Removing a version an active project pins produces a confusing failure on the next build. Say which projects you checked.

AVDs hold user data the same way simulator devices do.

## Flutter / Dart

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `<project>/build` | Build output | `flutter build` | SAFE |
| `<project>/.dart_tool` | Package config, build cache | `flutter pub get` | SAFE |
| `<project>/ios/Pods`, `macos/Pods` | CocoaPods deps | `pod install` via `flutter build` | SAFE |
| `<project>/android/.gradle`, `android/build` | Gradle state | rebuilt | SAFE |
| `~/.pub-cache` | Global package cache | `flutter pub get` re-downloads | REVIEW |
| `~/.pub-cache/git` | Git-sourced packages | re-cloned | REVIEW |
| Flutter SDK `bin/cache` | Engine binaries per platform | `flutter precache`, large download | REVIEW |

Native cleanup: `flutter clean` in a project (removes `build` and `.dart_tool`), `dart pub cache clean`.

`~/.pub-cache` is shared by every Flutter project; clearing it forces re-download for all of them. It is REVIEW, not SAFE, for the same reason as the pnpm store.

## Docker

Never delete Docker data with `rm`. The daemon keeps its own metadata and manual deletion corrupts it. Use the CLI.

| Object | Reclaim with | Risk |
|---|---|---|
| Stopped containers | `docker container prune` | SAFE (unless a container holds state never committed or mounted out) |
| Dangling images | `docker image prune` | SAFE |
| Unused images | `docker image prune -a` | REVIEW — re-pull or rebuild needed |
| Build cache | `docker builder prune` | SAFE — rebuilds are slower afterwards |
| Unused volumes | `docker volume prune` | **DANGEROUS** |
| Everything | `docker system prune` | REVIEW, and never with `--volumes` |

Volumes are where databases live. A "dangling" volume is frequently the Postgres data directory of a compose project the user brought down last week and will bring up again. There is no undo. List them with sizes so the user can see what they have, name what each appears to be attached to, and leave the decision entirely with them.

`docker system df -v` gives per-object sizes. On macOS the entire Docker footprint also shows up as one large disk image (`~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw` or `~/.docker/desktop/vms/...`); note that pruning inside Docker does not always shrink that file, and reclaiming it needs Docker Desktop's own disk-space tooling.

## Python

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `<project>/.venv`, `venv`, `env` | Virtual environment | `uv sync` / `pip install -r requirements.txt` / `poetry install` | SAFE with a manifest, REVIEW without |
| `<project>/__pycache__`, `*.pyc` | Bytecode | regenerated on import | SAFE |
| `<project>/.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox` | Tool caches | regenerated | SAFE |
| `<project>/build`, `dist`, `*.egg-info` | Packaging output | rebuild | SAFE |
| `~/Library/Caches/pip`, `~/.cache/pip` | Wheel cache | re-downloaded | SAFE |
| `~/.cache/uv`, `~/Library/Caches/uv` | uv cache | re-downloaded | SAFE |
| `~/.cache/huggingface` | Model weights (`hub/`) and datasets | re-downloaded, often many GB and slow | REVIEW |
| `~/.cache/torch` | PyTorch hub weights | re-downloaded | REVIEW |
| `~/Library/Caches/pypoetry`, `~/.cache/pypoetry` | Poetry cache + virtualenvs | re-created | REVIEW |
| `~/.conda/pkgs`, `~/anaconda3/pkgs`, `~/miniconda3/pkgs` | Conda package cache | re-downloaded | SAFE |
| Conda `envs/` | Full environments | recreate from an env file if one exists | REVIEW |

Native cleanup: `uv cache prune`, `pip cache purge`, `poetry cache clear --all .`, `conda clean --all`.

A `.venv` without any manifest beside it (no `requirements.txt`, `pyproject.toml`, `Pipfile`, or `environment.yml`) is orphaned — reinstalling is guesswork. Freeze it first (`pip freeze > requirements.txt`) or leave it alone.

## Rust

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `<project>/target` | Build output, often many GB | `cargo build` | SAFE |
| `~/.cargo/registry/cache`, `registry/src` | Crate sources and archives | re-downloaded | SAFE |
| `~/.cargo/git` | Git dependencies | re-cloned | SAFE |
| `~/.rustup/toolchains/<name>` | Installed toolchains | `rustup toolchain install` | REVIEW |

Native cleanup: `cargo clean` per project; `cargo cache -a` if `cargo-cache` is installed; `rustup toolchain uninstall` for a specific toolchain.

`target` directories are usually the single largest Rust win and are pure build output. Check for toolchains pinned by `rust-toolchain.toml` before proposing to remove any toolchain.

## Go

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `~/go/pkg/mod` | Module cache (read-only files) | `go mod download` | SAFE |
| `~/go/pkg/sumdb` | Checksum DB cache | re-fetched | SAFE |
| `~/Library/Caches/go-build`, `~/.cache/go-build` | Build cache | rebuilt | SAFE |
| `<project>/bin`, compiled binaries | Output | `go build` | SAFE |

Native cleanup: `go clean -modcache` and `go clean -cache`. Use these rather than `rm` — the module cache is deliberately read-only and a plain delete fails partway, leaving it inconsistent.

## Java / JVM

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `~/.m2/repository` | Maven local repository | re-downloaded | REVIEW |
| `~/.gradle/caches` | see Android | | SAFE |
| `~/.ivy2/cache`, `~/.sbt`, `~/.coursier/cache` | Scala/sbt caches | re-downloaded | SAFE |
| `<project>/target` (Maven), `build` (Gradle) | Build output | rebuild | SAFE |
| `~/.sdkman/candidates` | Installed JDKs and tools | re-installed | REVIEW |

`~/.m2/repository` is REVIEW rather than SAFE because teams sometimes `mvn install` internal artifacts there that exist in no remote repository. Check for directories under it that do not correspond to anything on Maven Central before clearing it wholesale, or limit the proposal to the parts with a matching remote.

## Ruby

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `<project>/vendor/bundle` | Bundled gems | `bundle install` | SAFE with `Gemfile.lock` |
| `~/.gem`, `~/.local/share/gem` | Installed gems | `gem install` | REVIEW |
| `~/.bundle/cache` | Bundler cache | re-downloaded | SAFE |
| `~/.rbenv/versions`, `~/.rvm/rubies` | Ruby installations | re-installed, slow compile | REVIEW |

Native cleanup: `gem cleanup` removes superseded gem versions.

## .NET

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `<project>/bin`, `obj` | Build output | `dotnet build` | SAFE |
| `~/.nuget/packages` | NuGet global package cache | re-downloaded | SAFE |
| `~/.local/share/NuGet/http-cache` | HTTP cache | re-downloaded | SAFE |
| `~/.dotnet/toolResolverCache`, `~/.templateengine` | Tool caches | rebuilt | SAFE |

Native cleanup: `dotnet nuget locals all --clear`.

## Swift (non-Xcode)

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `<project>/.build` | SwiftPM build | `swift build` | SAFE |
| `~/Library/Caches/org.swift.swiftpm` | Dependency cache | re-cloned | SAFE |

## Game engines

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| Unity `<project>/Library` | Import cache, very large | reimport on open, slow | REVIEW |
| Unity `<project>/Library/com.unity.addressables` | **Content build state** if Addressables is used | cannot be regenerated | DANGEROUS |
| Unity `<project>/Temp`, `Obj`, `Logs` | Scratch | recreated | SAFE |
| Unity `<project>/Builds` | Player builds | rebuild | SAFE |
| `~/Library/Unity/cache` | Global asset/package cache | re-downloaded | SAFE |
| Unreal `<project>/Intermediate`, `Saved`, `DerivedDataCache` | Build + DDC | rebuilt, very slow | REVIEW |
| Unreal `<project>/Binaries` | Compiled output | rebuild | SAFE |
| Godot `<project>/.godot`, `.import` | Import cache | reimport | SAFE |

Before calling a Unity `Library` disposable, check for **Addressables**. If the project uses them, `Library/com.unity.addressables` holds content-state files that record what shipped in each content build; losing them breaks the ability to produce a compatible content update for a release already in players' hands. It is the one genuinely non-regenerable thing that lives inside `Library`, so look for `Assets/AddressableAssetsData` and say what you found. Everything else in there is cache.

Unity's `Library` reimport on a large project can take tens of minutes; Unreal's DDC rebuild can take hours. Both are technically derivable and both are REVIEW because of that cost. Unity's `Saved`/Unreal's `Saved` can contain crash logs and editor layouts the user may want.

## Infrastructure tools

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `<project>/.terraform` | Provider plugins, modules | `terraform init` | SAFE |
| `<project>/.terraform.tfstate*`, `terraform.tfstate*` | **State files** | nothing | DANGEROUS |
| `~/.terraform.d/plugin-cache` | Shared plugin cache | re-downloaded | SAFE |
| `~/.vagrant.d/boxes` | Vagrant boxes | re-downloaded, large | REVIEW |
| `<project>/.vagrant` | VM instance links | recreated, but destroys the VM link | REVIEW |
| `~/.minikube/cache`, `~/.kube/cache` | Cluster caches | re-downloaded | SAFE |
| VM images (UTM, Parallels, VMware, Lima, Colima) | Full virtual machines | nothing | DANGEROUS |

Terraform state is the mapping between config and real cloud resources. Losing it strands live infrastructure. It sits in the same directory as the safe-to-delete plugin cache, so be precise about which path you are naming.

## Package managers and system tools

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `~/Library/Caches/Homebrew` | Downloaded bottles | re-downloaded | SAFE |
| `$(brew --cache)` | same, authoritative location | | SAFE |
| Homebrew old versions | Superseded installs | reinstallable | SAFE |
| `~/Library/Caches/ccache`, `~/.ccache` | C/C++ compile cache | rebuilt | SAFE |
| `~/.cache/sccache` | Rust/C++ shared cache | rebuilt | SAFE |
| `~/.nvm/.cache`, `~/.nvm/versions` | Node versions | `nvm install` | REVIEW |
| `~/.asdf/installs`, `~/.mise` | Tool versions | reinstalled | REVIEW |
| `/nix/store` | Nix store | `nix-collect-garbage` only | REVIEW |

Native cleanup: `brew cleanup -s` (and `brew autoremove`), `ccache -C`, `nix-collect-garbage -d`.

Never delete a language-version manager's installed versions without checking `.nvmrc`, `.tool-versions`, `.node-version` and similar files across the user's projects first.

## AI coding tools

A newer category and a large one: several assistants, each keeping multi-GB state, sometimes in duplicate.

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `~/.claude` | Claude Code sessions, plugins, caches | sessions are history, not regenerable | REVIEW |
| `~/Library/Application Support/Claude/vm_bundles` | Claude desktop VM bundles | re-downloaded by the app | REVIEW |
| `~/Library/Application Support/Claude/Cache*` | Electron caches | rebuilt | SAFE |
| `~/.codex`, `~/.cache/codex-runtimes` | Codex sessions and runtimes | runtimes re-download; sessions do not | REVIEW |
| `~/.gemini/antigravity*` | Antigravity IDE state; `browser_recordings/` is screenshot frames | recordings regenerate by use; conversations do not | REVIEW |
| `~/.cursor` | Cursor extensions and state | reinstalled | REVIEW |

Look for sibling copies: `antigravity`, `antigravity-backup`, `antigravity-ide` side by side is a tool that copied its state instead of moving it. Confirm they are real copies (same relative file, `stat -f %i` differs) before calling the extras waste, then the extras are SAFE and the original stays REVIEW. Inside any of these, the disposable part is usually recordings, caches, and downloaded runtimes; the part to keep is conversation and session history, which is small and irreplaceable.

## Editors and IDEs

| Path | Holds | Comes back via | Risk |
|---|---|---|---|
| `~/Library/Caches/JetBrains/<IDE>` | Indexes, caches | reindexed on open, slow | SAFE |
| `~/Library/Logs/JetBrains/<IDE>` | Logs | recreated | SAFE |
| `~/Library/Application Support/JetBrains/<IDE>` | **Settings, plugins, keymaps** | reconfigured by hand | DANGEROUS |
| `~/Library/Application Support/Code/Cache*`, `CachedData`, `CachedExtensionVSIXs` | VS Code caches | rebuilt | SAFE |
| `~/Library/Application Support/Code/User/workspaceStorage` | Per-workspace state, some unsaved | partially recreated | REVIEW |
| `~/Library/Application Support/Code/User/History` | **Local file history** | nothing | DANGEROUS |
| `~/.vscode/extensions` | Installed extensions | reinstalled | REVIEW |
| `~/Library/Application Support/Code/logs` | Logs | recreated | SAFE |

The distinction that matters here is Caches versus Application Support. The first is disposable by design; the second holds configuration the user spent years accumulating. VS Code's `User/History` is a local undo history for files that may never have been committed.

## Patterns for unrecognized directories

When you meet something not in this catalog, reason from the three questions rather than guessing from the name. Signals that a directory is generated:

- It sits beside a manifest or lockfile that describes how to rebuild it.
- It is listed in the project's `.gitignore`, and `git check-ignore -q <path>` confirms it.
- It contains no files tracked by git (`git ls-files <path>` is empty inside a repo).
- Its name matches the conventional output directory for a build tool that is present.
- Its contents are timestamped close together and close to a build event.

Signals that it is not:

- It contains files git tracks, or the directory is itself a git repo.
- It holds databases (`*.sqlite`, `*.db`, `data/` inside a volume), key material (`*.pem`, `*.p12`, `id_*`), or `.env` files.
- Nothing on the machine knows how to recreate it — no tool, no manifest, no documented command.
- Its files have widely varying timestamps, suggesting accumulated rather than generated content.

Two checks before any proposal, regardless of what the directory is:

- **Is something running out of it?** `ps -axo command` grepped for the path. A live dev server, an IDE indexer, or a build daemon inside the directory means the answer is "not now", whatever the tier says. The scanner sets `in_use_by_running_process` for this.
- **Does regeneration need something the user might not have?** A `.npmrc` with `_authToken` or a non-public registry, a `rust-toolchain.toml` pinning a removed toolchain, a Unity version no longer installed. Each turns "run one command" into "get on the VPN, renew a token, reinstall an editor". The scanner sets `project_private_registry` for the npm case; the others you check by reading the manifest.

`git check-ignore` is the single most useful check available: a directory the project itself declares as ignored output is the project telling you it is derivable. It is not proof — people gitignore secrets too — so pair it with a look at what is inside.

When the signals conflict or you cannot name the regeneration command, report the directory with its size and say you could not classify it. An honest unknown is more useful than a confident wrong answer.
