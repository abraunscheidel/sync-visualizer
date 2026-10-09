# Backlog

The list of work lives on GitHub, so it stays put and can be looked at from anywhere:

- **Board:** https://github.com/users/abraunscheidel/projects/1 (private)
- **Issues:** https://github.com/abraunscheidel/sync-visualizer/issues

Each item is an issue. Its text says what it is and points at the section of `docs/design.md` that holds the reasoning. Labels:

| Label | Meaning |
|---|---|
| `next` | Planned next. Take them in issue-number order (1 to 4 were the order set in October 2026). |
| `plugin-authoring` | Makes it easier to write a plugin for a new experiment (design doc 28.15). |
| `later` | Parked: an idea, or a decision to revisit. |
| `design` | Needs a design discussion before it is built. |

When work starts, finishes or is added: move or close the issue (a commit message that says `Closes #N` does it), or ask Claude, which can
use `gh` (the `GH_TOKEN` on this machine has `repo` and `project` access). Decisions and designs still go in `docs/design.md`;
this file and `docs/checklists.md` are the only other places that say what to do next.

Done work is not listed here: `git log` and the closed issues are the record.
