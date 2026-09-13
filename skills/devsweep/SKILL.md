---
name: devsweep
description: Analyze where developer disk space went and safely reclaim it — build artifacts, dependency directories, package-manager caches, simulators, Docker data, toolchain caches. Classifies every candidate SAFE / REVIEW / DANGEROUS, attributes artifacts to the projects that produced them, and never deletes anything without showing the exact paths and getting explicit approval. Use this whenever the user mentions running out of disk space, "my Mac is full", storage, "what's eating my disk", cleaning up node_modules / DerivedData / Docker / Gradle / caches / simulators / build folders, or freeing space on a dev machine — even if they never say the word "clean". Also use it when they ask to clean a single project, or ask whether some generated directory is safe to delete.
---

# DevSweep

DevSweep is an analysis tool first and a deletion tool second. The user's source code and unique data are irreplaceable; their caches are not. Every decision flows from that asymmetry: when unsure, measure and report rather than delete.

## The core model

Do not rely on a hardcoded list of directory names. Toolchains invent new cache locations constantly, and you will meet ecosystems this skill never enumerated. Instead, classify any candidate by answering three questions. This is what makes DevSweep work on a Zig cache, a Terraform plugin dir, or whatever ships next year.

**1. Is it derivable?** Could this be recreated by running a documented command against inputs that still exist? `node_modules` is derivable from `package.json` plus a lockfile. `DerivedData` is derivable from the Xcode project. A photo library is not derivable from anything.

**2. Are the inputs still present and reachable?** A `node_modules` next to an intact `package-lock.json` is trivially rebuilt. The same directory with no lockfile and no manifest is *orphaned* — nothing can regenerate it, which also means nothing depends on it. Regeneration that needs the network counts as reachable but costly; say so.

**3. Does it hold state that exists nowhere else?** Docker volumes hold databases. Xcode Archives hold the exact binary you shipped and the dSYMs that symbolicate its crash reports. Signing assets and `.env` files hold secrets. These are not caches wearing a cache's clothing, and no size number justifies removing them.

The classification follows directly:

- **SAFE** — derivable, inputs present, regeneration is routine. Old build output, compiler caches, download caches.
- **REVIEW** — derivable but regeneration is slow, needs the network, needs a specific toolchain version, or the artifact belongs to something the user is actively working on. Also: orphaned artifacts, where you should ask why the inputs vanished before assuming it's junk.
- **DANGEROUS** — holds unique state, secrets, or shipped-build provenance. Report it so the user understands their disk, and stop there.

Never move an item to a lower risk tier because it is large. Size determines *priority within a tier*, never the tier itself.

The tiers describe consequence, not category, so the same kind of directory lands differently on different machines. A Unity `Library` is REVIEW by default because reimport is usually a coffee break, but on a project whose `Assets` folder is one megabyte and whose editor is already installed, the real cost is a two-minute package download and SAFE is the honest label. Moving an item between SAFE and REVIEW is allowed and often right. What is not allowed is doing it silently: state the cost you measured and why it changes the answer, so the user is agreeing to a number rather than to your adjective. Nothing ever moves out of DANGEROUS on a cost argument, because that tier is about what cannot be recovered at any price.

## Workflow

Five phases. Skip ahead only when the user's request clearly scopes you (for example "clean docker" starts at Measure with one ecosystem).

### Phase 1 — Detect

Find out which ecosystems exist before paying for expensive scans. Scanning a Gradle cache on a machine with no JVM wastes the user's time.

```
python3 scripts/scan.py --detect
```

Report what you found in a compact list, then move on. Do not narrate each check.

### Phase 2 — Measure

```
python3 scripts/scan.py --roots ~/Projects ~/code --json /tmp/devsweep.json
```

The script walks project roots with pruning (it never descends *into* a `node_modules` it has already counted), sizes candidates with batched `du`, reads modification times, attributes each artifact to its owning project, and sizes the well-known global caches. It emits JSON so you spend your tokens on judgment rather than on parsing `du` output.

Useful flags: `--global-only` (skip project scanning), `--ecosystems js,xcode` (limit scope), `--min-size-mb N` (suppress noise), `--project PATH` (a single project), `--include-docker` (queries the Docker daemon, off by default because a stopped daemon hangs), `--no-discover` (skip the discovery pass below).

If the user names directories, pass those as `--roots`. If they don't, the script checks the usual code locations.

**The discovery pass is what keeps the catalog from blinding you.** After the catalogued scan, the script sizes the direct children of the places developer tooling accumulates (`~`, `~/Library/*`, `~/.cache`, `/Library/Developer`, and so on) and reports anything large that no catalog rule covers, as `uncatalogued_large_dirs` with risk UNKNOWN. On a real machine this is routinely where the biggest items live: an AI tool that kept three copies of its state, a 12 GB model cache, a system-level simulator runtime volume, a folder of drone footage on the Desktop. A report that lists 120 GB of catalogued caches while 30 GB of duplicates sits unmentioned two directories away has failed at the one question the user asked. Skipping personal locations is deliberate; the JSON lists them under `personal_dirs_not_scanned` so you can say what you did not look at.

Read the JSON. Trust its sizes, with one caveat worth internalising: a size is only meaningful if removing the thing frees it. Mounted volumes, sparse files, hardlinked and clonefile-backed trees all report bytes that either live somewhere else or cannot be recovered by deleting the path you are looking at. The scanner measures without crossing mount points and flags `contains_mounted_volumes`; when a number looks too good, ask what deleting it would actually return before you put it in a total. Use `last_activity_days` for staleness, never `dir_mtime_days`: a directory's own mtime changes only when a direct child appears or disappears, so content-addressed caches look untouched for years while receiving files daily. The script samples the contents to get the real number and keeps the raw mtime only so you can see the gap. Treat risk labels as defaults rather than verdicts, and `in_use_by_running_process` and `project_private_registry` as hard stops for a proposal until you have said why they matter.

### Phase 3 — Classify

Walk the candidates through the three questions. The script pre-labels the well-known ones; your job is the cases it could not know:

- An artifact in a project whose git HEAD moved this week is REVIEW even if its type is normally SAFE. The user is working there, and a rebuild costs them time right now.
- An artifact in a project untouched for a year is SAFE, and a strong candidate.
- An unrecognized directory that smells generated (named `build`, `target`, `out`, `.cache`, sits beside a manifest, contains no tracked files) gets reasoned about from first principles. Say explicitly that you are inferring, and put it in REVIEW unless you can name the command that regenerates it.
- Every `uncatalogued_large_dirs` entry gets the three questions. Look inside it: a directory of dated session folders with `.pb` conversation files is state someone may want; a directory of `.jpg` screenshot frames beside it is regenerable noise; three sibling copies of the same tree are two copies too many, and checking that they are copies rather than hardlinks takes one `stat` on the same file in each. Name what it appears to be, say how confident you are, and give it a tier.
- Anything you cannot explain, report as unknown rather than guessing. "I don't know what this 4 GB directory is" is a useful sentence.
- Something in use beats every other signal. The scanner flags artifacts a running process is executing out of; a `node_modules` with a live dev server in it stays off the list regardless of size or age.
- A project that reinstalls from a private registry or a stored token (`project_private_registry` in the JSON) is a project whose "just run npm ci" may need a VPN, an unexpired credential, and a licence. Say so; it changes the tier.

Consult `references/ecosystems.md` for the per-ecosystem catalog: what each path holds, the exact regeneration command, the native cleanup command, and the specific traps. Read the sections for the ecosystems you actually detected, not the whole file.

### Phase 4 — Report

Lead with the shape of the problem, then the ranked opportunities. The user should finish reading understanding *where their disk went*, not just what you propose to remove.

```
DevSweep

Disk                   494 GB, 418 GB used, 35 GB free
Developer storage      148.7 GB
  Safe to reclaim       54.2 GB
  Review recommended    28.2 GB
  Potentially important 17.3 GB
  Unclassified          48.9 GB   (large directories outside the catalog, see below)

Top opportunities
  1. node_modules, 14 dormant projects   21.4 GB  SAFE     ~/Projects/*/node_modules
  2. Xcode DerivedData                   16.8 GB  SAFE     ~/Library/Developer/Xcode/DerivedData
  3. Docker build cache                   9.7 GB  SAFE     docker builder prune
  4. Simulator runtimes, iOS 16.x/17.x   18.2 GB  REVIEW   /Library/Developer/CoreSimulator/Volumes
  5. Docker volumes (3)                  11.8 GB  DANGEROUS
```

Every row carries a path or the native command that addresses it. A row the user cannot locate is a row they cannot act on. Follow the ranked list with a short section for large things that are not developer storage at all if the discovery pass turned them up (a 12 GB folder of video on the Desktop, a 46 GB Applications folder). Flag them in a sentence each so the user does not chase them through DevSweep, then leave them alone.

When artifacts group by project, show that grouping — it is the view that makes the number make sense:

```
accounting-app                    18.7 GB   last commit 7 months ago
  node_modules      9.8 GB    npm ci
  .nx               3.1 GB    regenerated on next build
  dist              1.7 GB    npm run build
  .angular/cache    1.2 GB    regenerated on next build
  reclaimable      15.8 GB    SAFE
```

Attach the regeneration command to each line. That is what turns a scary deletion into an obviously reversible one. Never count source files, `.git`, or config as reclaimable, and never present a total that includes DANGEROUS items as if it were available space.

### Phase 5 — Clean

Only on an explicit, affirmative instruction to delete. "What's taking space" and "show me" are not that instruction. When intent is ambiguous, analyze and stop — the user can always say yes afterward, but nobody can un-delete.

Before touching anything, show the complete list: every path, its size, the total, and what will need regenerating. Then ask. Wait for a clear yes.

```
Ready to remove:

  ~/Projects/accounting-app/node_modules        9.8 GB   restore: npm ci
  ~/Projects/accounting-app/dist                1.7 GB   restore: npm run build
  ~/Library/Developer/Xcode/DerivedData        16.8 GB   rebuilt on next build

  Total 28.3 GB. No source files, git history, or config are included.

Proceed?
```

Two rules that apply to every ecosystem, not just the one in front of you.

**Close the tool before removing its cache.** Deleting a cache out from under a running editor, daemon, or build leaves it writing into a directory that no longer exists, and the resulting half-state is harder to fix than the reimport you were avoiding. Unity, Xcode, JetBrains, Docker and Gradle daemons all behave this way. Say which thing to quit, and check it is actually stopped rather than assuming.

**Say what deletion will really return.** On APFS, copies made by Finder, `cp -c`, and package managers like npm are clonefiles that share blocks, and pnpm and some dependency layouts use hardlinks. In all of those cases `du` counts bytes that deleting one copy does not free. Neither `stat` nor `du` can tell you the difference, so when a candidate is plausibly a clone or a hardlinked tree, say the recovered space may be smaller and that the number after deletion is the real one. A user who was promised 14 GB and got 2 will not trust the next number you give them.

Prefer a tool's own cleanup command over `rm` whenever one exists. Package managers and Docker keep internal indexes that a manual delete leaves inconsistent; `docker builder prune` and `xcrun simctl delete unavailable` do bookkeeping that `rm -rf` skips. `references/ecosystems.md` lists the native command for each ecosystem.

When you do delete directly, delete the specific resolved paths you showed the user, one at a time. A wildcard is never allowed to decide what gets removed: `rm -rf ~/Library/Developer/Xcode/DerivedData/*` lets the shell choose the list at execution time, after the user approved something else. Either remove the directory itself when the tool recreates it (`rm -rf ~/Library/Developer/Xcode/DerivedData` is fine; Xcode makes a new one) or enumerate the children, show them, and remove those. Re-check each path immediately before removing it: that it still exists, that it is the path you showed, and that it is not a symlink pointing somewhere else. Report what actually got freed afterwards by re-measuring, not by repeating your estimate.

If any single removal fails, stop and report rather than continuing down the list.

## Safety rules

These override everything above, including a user who is in a hurry.

Never delete without explicit approval for that specific run. Approval does not carry over from an earlier conversation or an earlier batch.

Never delete, and never propose deleting, unless the user names the specific item themselves and asks for it:

- source code, `.git`, or anything tracked by git
- SSH keys, certificates, keychains, provisioning profiles, signing identities
- `.env` files, credentials, tokens, config
- databases, Docker volumes, Xcode Archives
- anything under a path you were not asked to scan

Never run broad destructive commands. `rm -rf ~/Library/*`, `rm -rf ~/.*`, and `docker system prune --volumes` are all forbidden regardless of how much space they would free; targeted removal of enumerated paths is always possible instead.

Resolve every path before acting on it and confirm it stays within the intended root. Do not follow symlinks out of the cleanup location.

If a scan turns up something that looks like a security problem rather than a space problem — world-readable keys, a committed `.env` — mention it plainly and move on. It is not yours to fix.

## Intent routing

| The user says | You do |
|---|---|
| "clean my dev files", "free up space" | Full workflow, stopping at the approval gate |
| "what's taking developer space?" | Detect, Measure, Report. No deletion proposal |
| "clean node" / "clean xcode" / "clean docker" | Scope to that ecosystem, full workflow |
| "clean this project" | `--project .`, full workflow |
| "deep scan" | Widen roots and depth; warn that it is slow |
| "safe clean" | Propose SAFE candidates only; still ask before deleting |
| "dry run" | Complete analysis, no filesystem changes, state plainly that nothing was touched |

Dry run is the default whenever intent to delete is not explicit.

## Reference files

- `references/ecosystems.md` — per-ecosystem catalog: paths, regeneration commands, native cleanup commands, and traps. Read the sections matching what you detected.
- `scripts/scan.py` — detection, sizing, project attribution, and default classification. Run it rather than reimplementing `du` orchestration.
