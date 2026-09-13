# DevSweep

A Claude Code plugin that works out where your developer disk space went, and reclaims it without touching anything you cannot rebuild.

Development machines accumulate tens of gigabytes of caches, build output, dependency trees, simulator images and container layers. Most of it is regenerable and some of it is not, and the two look identical from the outside. DevSweep measures the difference, explains it, and asks before it removes anything.

## What it does

Ask it in plain language:

- "where did my disk space go?"
- "my mac is full and it's all dev junk"
- "is it safe to delete the Library folder in this Unity project?"
- "clear out node_modules in projects I haven't touched in months"
- "clean docker"

It runs five phases: detect which toolchains exist, measure their footprint, classify every candidate, report where the space went, and only then propose a removal list. Analysis is the default; deletion needs an explicit yes.

## How it decides what is safe

Rather than matching a fixed list of directory names, every candidate answers three questions:

1. **Is it derivable?** Could a documented command recreate it from inputs that still exist?
2. **Are those inputs still present?** A `node_modules` beside an intact lockfile rebuilds in one command. The same directory with no manifest is orphaned.
3. **Does it hold state that exists nowhere else?** Docker volumes hold databases. Xcode Archives hold the dSYMs that symbolicate crash reports from shipped builds.

That yields three tiers. **SAFE** is derivable with inputs present. **REVIEW** is derivable but slow, network-dependent, or belongs to something you are actively working on. **DANGEROUS** holds unique state and is reported, never proposed.

Because the model is about consequence rather than category, it also handles toolchains the catalog has never heard of.

## What it catches that a manual sweep misses

These are the failure modes it was built against, each found during development on a real machine:

- **Mounted volumes.** macOS mounts simulator runtimes as read-only volumes. Walking into them reports 34 GB against an 8 GB backing image, and deleting the mount point frees nothing.
- **Directory mtime.** A directory's own timestamp changes only when a direct child appears, so content-addressed caches look untouched for years while receiving files daily. DevSweep samples contents instead.
- **Clonefiles and hardlinks.** On APFS, copies share blocks and `du` counts them twice. Reported sizes can overstate what deletion returns, and DevSweep says so rather than promising a number it cannot deliver.
- **Things in use.** A `node_modules` with a live dev server inside it stays off the list regardless of size.
- **Regeneration you cannot actually perform.** A project that reinstalls from a private registry needs a VPN and an unexpired credential. That changes the tier.
- **Activity noise.** Opening a folder in Finder writes `.DS_Store`; a build daemon writes logs. Both make an abandoned project look active.

## Ecosystems

JavaScript/TypeScript, Xcode and Apple platforms, Android, Flutter, Docker, Python, Rust, Go, JVM, Ruby, .NET, Swift, Unity, Unreal, Godot, Terraform, virtual machines, AI coding tools, editors and IDEs, and the usual package managers. Anything not in the catalog goes through a discovery pass and is reported as unclassified rather than ignored.

## Safety

- Nothing is deleted without approval for that specific run.
- Source code, `.git`, SSH keys, certificates, provisioning profiles, `.env` files, databases, Docker volumes and Xcode Archives are never proposed.
- No wildcards in deletion commands. A glob lets the shell decide the list after you approved something else.
- A tool's own cleanup command is preferred over `rm` where one exists, because package managers and Docker keep indexes that a manual delete leaves inconsistent.
- Paths are re-checked immediately before removal, and space freed is re-measured afterwards rather than estimated.

## Install

```
/plugin marketplace add arifsisman/devsweep
/plugin install devsweep
```

Or clone into your skills directory:

```
git clone https://github.com/arifsisman/devsweep.git
cp -R devsweep/skills/devsweep ~/.claude/skills/
```

## The scanner

`skills/devsweep/scripts/scan.py` does the filesystem work: ecosystem detection, pruned directory walking, parallel sizing, project attribution, and mount-aware measurement. It is read-only and never deletes.

```
python3 scan.py --detect
python3 scan.py --roots ~/Projects --json /tmp/devsweep.json
python3 scan.py --project . --ecosystems js
```

Useful flags: `--global-only`, `--ecosystems`, `--min-size-mb`, `--include-docker`, `--no-discover`, `--discover-budget`.

## Development

Built and refined over four evaluation rounds against a real machine, comparing the skill against an unaided baseline on the same tasks. Pass rate went from 95% to 100% while the unaided baseline held around 80%; the evaluation prompts are in `skills/devsweep/evals/`.

## License

MIT
