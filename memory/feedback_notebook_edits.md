---
name: feedback_notebook_edits
description: User prefers inline analysis via Bash/Python over editing the notebook
metadata:
  type: feedback
---

Do not edit the notebook to run analyses. Run Python inline via Bash instead.

**Why:** User explicitly rejected a NotebookEdit and asked for inline  code running in Claude Code.

**How to apply:** When the user asks for a quick analysis or exploration, use `python3 -c` or a temp script via Bash rather than modifying the .ipynb file.