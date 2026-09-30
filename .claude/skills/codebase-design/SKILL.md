---
name: codebase-design
description: Use when designing, adding or restructuring a module, class, service layer, abstraction or interface, or when judging whether a wrapper/pass-through layer is worth keeping. Vocabulary and tests for deep modules and seams.
---

# Codebase design

Aim for **deep modules**: a lot of behaviour behind a small interface, placed at a clean seam, testable through that interface. Use these terms exactly.

- **Module** — anything with an interface and an implementation (function, class, package). Not "component"/"service".
- **Interface** — everything a caller must know: signature, invariants, ordering, error modes, required config. Not just the type signature.
- **Depth** — behaviour a caller can use per unit of interface learned. Deep = small interface, lots behind it. Shallow = interface nearly as complex as the body.
- **Seam** — a place where behaviour can change without editing there; where a module's interface lives. Say "seam", not "boundary".
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Leverage** (callers) and **locality** (maintainers): what depth buys. Fix once, fixed everywhere.

## Rules

1. **Deletion test.** Imagine deleting the module. Complexity vanishes → it was a pass-through, remove or flag it. Complexity reappears across N callers → it earns its keep, leave it.
2. **One adapter = hypothetical seam; two = real.** No interface/ABC/factory unless something actually varies across it (matches CLAUDE.md §1).
3. **The interface is the test surface.** If a test must reach past the interface, the module is the wrong shape.
4. **Accept dependencies, don't create them.** Return results instead of mutating side effects.
5. **Shrink the interface first:** fewer methods, simpler params, hide more inside.

## How to apply here

- Apply while designing; do not refactor code outside the task. Friction found elsewhere (oversized file, pass-through layer, leaky seam) → one line in the reply, no fix.
- For hot spots, check `git log` for churn and CodeGraph for callers/blast radius before proposing a change.
- A full architecture survey is a separate, user-requested task, not a side effect.
