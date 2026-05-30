# Trump's Truth Dataset

A dataset of Donald Trump's posts ("Truths") on Truth Social, scraped from the
public archive at [trumpstruth.org](https://trumpstruth.org). Includes post text,
timestamps, image descriptions, and **video transcripts**.

The dataset is stored as **JSONL** (`data/dataset.jsonl`), which you scrape
yourself (see [Download the dataset](#download-the-dataset)). **For analysis,
don't read the JSONL directly** — first convert it once to **Parquet**
([instructions](#generate-the-parquet-file-do-this-next)) and load that. Parquet
is columnar, compressed, and typed, so it loads into pandas in milliseconds and
keeps every query fast. All analysis examples in this README — and in Claude —
use `data/dataset.parquet`.

## Contents

- [Dataset overview](#dataset-overview)
- [Schema](#schema) · [Example record](#example-record)
- [Exploring the dataset with Claude (no code)](#exploring-the-dataset-with-claude-no-code)
  - [Loading the project](#loading-the-project)
  - [Choosing the model](#choosing-the-model)
  - [Example prompts](#example-prompts)
- [Environment setup (macOS)](#environment-setup-macos)
- [Using VS Code's integrated terminal](#using-vs-codes-integrated-terminal)
- [Setting up Jupyter notebooks in VS Code](#setting-up-jupyter-notebooks-in-vs-code)
- [Download the dataset](#download-the-dataset)
- [Generate the Parquet file (do this next)](#generate-the-parquet-file-do-this-next)
- [Loading the data with pandas](#loading-the-data-with-pandas)
- [Source & attribution](#source--attribution)
- Related: [analysis-recommendations.md](analysis-recommendations.md) — analysis
  patterns, methodologies & visualization guide

## Dataset overview

| | |
|---|---|
| Format | JSONL (one post per line, UTF-8) |
| Coverage | February 14, 2022 – present |
| Size | ~37,000 posts (as of May 2026) |
| Source | <https://trumpstruth.org> |

## Schema

Each line is a JSON object with these fields:

| Field | Type | Description |
|---|---|---|
| `id` | string | Archive ID (from `/statuses/<id>`) |
| `url` | string | Archive URL on trumpstruth.org |
| `timestamp` | string | Original timestamp as displayed (US Eastern) |
| `timestamp_iso` | string | ISO 8601 timestamp in UTC |
| `text` | string | Post body text (empty if image/video only) |
| `truth_social_url` | string | Original post URL on truthsocial.com |
| `attachments` | array | Media attachments (see below) |
| `is_retruth` | bool | `true` if this is a re-truth of another account |
| `scraped_at` | string | UTC ISO 8601 time the record was scraped |

**Attachment objects** inside `attachments`:

- Image — `{"type": "image", "url": ..., "description": ...}`
  where `description` is the full image-description text.
- Video — `{"type": "video", "url": ..., "caption_url": ..., "transcript": ...}`
  where `transcript` is the spoken text parsed from the video's caption file.

### Example record

```json
{
  "id": "38881",
  "url": "https://trumpstruth.org/statuses/38881",
  "timestamp": "May 30, 2026, 12:46 AM",
  "timestamp_iso": "2026-05-30T04:46:00+00:00",
  "text": "",
  "truth_social_url": "https://truthsocial.com/@realDonaldTrump/116661707551593139",
  "attachments": [
    {"type": "image", "url": "https://.../73d93e349c8c5c1f.png",
     "description": "Tweet by a verified user discussing George Hill..."}
  ],
  "is_retruth": false,
  "scraped_at": "2026-05-30T05:01:12+00:00"
}
```

## Environment setup (macOS)

Use **pyenv** to manage Python versions and **pyenv-virtualenv** to keep this
project's dependencies isolated from everything else on your machine.

**Why this combination?** macOS ships with a system Python that you shouldn't modify — installing packages into it can break OS tools. pyenv lets you install and switch between any Python version independently of the system. pyenv-virtualenv goes a step further: it creates a self-contained environment per project, so the packages you install here (pandas, pyarrow, etc.) don't conflict with other project's dependencies and nothing from other projects conflicts with this one. The `pyenv local` command in step 4 means the correct environment activates automatically whenever you `cd` into this folder — no manual activation required.

### 1. Install Homebrew

If you don't have Homebrew, install it from [brew.sh](https://brew.sh) or open the **Terminal** app and run:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install pyenv and pyenv-virtualenv

```bash
brew install pyenv pyenv-virtualenv
```

### 3. Configure your shell

**Which file to edit:** macOS has used **zsh** as the default shell since macOS Catalina (2019), so if you're using the built-in Terminal app you almost certainly want `~/.zshrc`. The `~/.bash_profile` alternative is only needed if you've manually switched to bash. Not sure which you're using? Run `echo $SHELL` in Terminal — if it prints `/bin/zsh`, use `~/.zshrc`.

**If `~/.zshrc` doesn't exist yet:** The file isn't created automatically — many fresh macOS installs don't have one. Check with:

```bash
ls ~/.zshrc
```

If you see `No such file or directory`, create it:

```bash
touch ~/.zshrc
```

Then open it in a text editor (e.g. `open -e ~/.zshrc` to use TextEdit) and add the lines below.

Add the following to your shell config (`~/.zshrc` for zsh, `~/.bash_profile` for
bash):

```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"
```

Reload your shell:

```bash
source ~/.zshrc   # or source ~/.bash_profile
```

### 4. Install Python and create a virtual environment

First, make sure you're in the project root folder. In Terminal, `cd` into it:

```bash
cd /path/to/truth-dataset
```

Replace `/path/to/truth-dataset` with the actual path — e.g. if the folder is on
your Desktop: `cd ~/Desktop/truth-dataset`. All project commands from here on
must be run from this folder.

```bash
# Install a recent Python version (adjust as needed)
pyenv install 3.12

# Create a virtual environment named "dataset"
pyenv virtualenv 3.12 dataset

# Activate it in this project directory (auto-activates on cd)
pyenv local dataset
```

The `pyenv local` command writes a `.python-version` file to the project root.
From then on, any `cd` into this directory automatically activates the
`dataset` environment.

### 5. Install dependencies

```bash
pip install -r requirements.txt
```

## Using VS Code's integrated terminal

Instead of switching to a separate Terminal app, you can run all project commands from VS Code's built-in terminal — it's the same shell, right inside the editor.

**Open it:** `Terminal → New Terminal` from the menu bar, or press `` Ctrl+` ``.

VS Code opens the terminal at the project root by default. Because `pyenv local dataset` wrote a `.python-version` file here, pyenv should activate the `dataset` environment automatically when the terminal opens. Verify it's working:

```bash
which python   # should show a path inside ~/.pyenv/shims or ~/.pyenv/versions
python --version
```

### Auto-activation not working?

VS Code's integrated terminal can open as a **non-login shell** that doesn't fully initialise pyenv. The fix is a one-time project-level setting. Create `.vscode/settings.json` in the project root:

```json
{
  "terminal.integrated.profiles.osx": {
    "zsh": {
      "path": "zsh",
      "args": ["-l"]
    }
  },
  "terminal.integrated.defaultProfile.osx": "zsh"
}
```

The `-l` flag makes the shell a **login shell**, which sources `~/.zshrc` on startup — including the `pyenv init` lines you added during environment setup. After saving, close and reopen the terminal and the `dataset` environment should activate automatically whenever you open a terminal in this project.

> **Applies only to macOS.** The `osx` suffix in the settings keys means these only affect macOS; other platforms are unaffected.

If you'd rather set this globally (for all projects, not just this one), open VS Code user settings with `Cmd+Shift+P → Preferences: Open User Settings (JSON)` and add the same keys there.

## Setting up Jupyter notebooks in VS Code

> **You can skip this for now.** If you're just getting started, you don't need
> Jupyter yet — Claude Code lets you explore the dataset interactively without
> it. Come back here once you have something worth preserving (see
> [Why save findings to Jupyter notebooks](#why-save-findings-to-jupyter-notebooks)).
> Fair warning: getting the kernel to pick up the right pyenv environment can be
> a little tricky and frustrating the first time — take your time with step 3.

1. Install the **Jupyter** extension from the VS Code Marketplace.
2. Open (or create) a `.ipynb` file.
3. Click **Select Kernel** in the top-right of the notebook editor and choose the
   `dataset` pyenv environment — it will appear as a Python interpreter
   option once the virtualenv is active.

## Download the dataset

The JSONL file is not included in this repository. Scrape it yourself using the
included [`scraper.py`](scraper.py):

```bash
# Full scrape — 10 seconds between page requests to be polite
python scraper.py --delay 10

# Incremental: fetch only posts newer than what's already stored, then stop
python scraper.py --update

# Delete the existing data file and re-scrape everything from scratch
python scraper.py --fresh
```

| Flag | Description |
|---|---|
| `--update` | Incremental mode — fetch only new posts, then stop |
| `--fresh` | Delete the output file and re-scrape the whole archive |
| `--oldest-first` | Full scrape ordered oldest-first |
| `--per-page N` | Posts per request: 10, 25, 50, or 100 (default 100) |
| `--delay N` | Seconds between page requests (default 1.0) |
| `--no-transcripts` | Skip fetching video transcripts (faster) |
| `--transcript-delay N` | Seconds between transcript requests (default 0.3) |

Deduplication is always on (keyed on post `id`), so re-running never creates
duplicates. The typical workflow is one full scrape, then `--update` on a
schedule to pull in new posts.

## Generate the Parquet file (do this next)

Once you have `data/dataset.jsonl`, convert it to Parquet **once**. Everything
downstream loads this file — it's columnar, compressed (~3–5× smaller), typed,
and loads into pandas in milliseconds, which is what keeps analysis fast.

Run the included [`compile.py`](compile.py) script:

```bash
python compile.py
```

This reads `data/dataset.jsonl` and writes `data/dataset.parquet`. Alongside the
raw fields it adds **derived analysis columns** that do not exist in the JSONL:

| Column | Description |
|---|---|
| `n_images`, `n_videos` | counts of each attachment type |
| `image_descriptions` | all image descriptions joined |
| `video_transcripts` | all video transcripts joined |
| `all_text` | post text + image descriptions + transcripts in one column (covers media-only posts) |
| `timestamp` | `timestamp_iso` parsed to a real UTC datetime |

Re-run it any time the JSONL changes (e.g. after `scraper.py --update`) to
refresh the Parquet.

## Loading the data with pandas

Always load the **Parquet** file (not the JSONL) for analysis:

```python
import pandas as pd

df = pd.read_parquet("data/dataset.parquet")   # fast, typed, low memory
print(len(df), "posts")

# Full-text search across post text, image descriptions, and transcripts
hits = df[df["all_text"].str.contains("truth", case=False, na=False)]

# Posts per month
df.set_index("timestamp").resample("ME").size()
```

The flattened columns (`all_text`, `image_descriptions`, `video_transcripts`,
`n_images`, `n_videos`) make text analysis and NLP straightforward without
unpacking the nested `attachments` list.

> For data-science patterns, methodologies, and visualization recommendations
> for exploring this dataset, see
> **[analysis-recommendations.md](analysis-recommendations.md)**.

## Exploring the dataset with Claude (no code)

You don't have to write any Python to analyze this dataset. Open the project in
VS Code with the Claude Code extension, describe what you want in plain English,
and Claude reads the files, writes and runs the code for you, and shows you the
results — tables, charts, exports, whatever you need.

### Loading the project

1. Install the **Claude Code** extension from the VS Code Marketplace.
2. Open this project folder in VS Code (`File → Open Folder…`).
3. Login to your Claude account.
4. Open the Claude Code panel and start asking questions about the dataset.

> **Tip:** Start a session with *"Read the README and
> `analysis-recommendations.md`, then load `data/dataset.parquet` (generate it
> first if it doesn't exist)."* That gives Claude the schema and recommended
> methods up front, and ensures it works from the **Parquet** file rather
> than re-parsing the JSONL on every query.

### Choosing the model

For this dataset, use **Claude Opus 4.8** — it's the most capable model and
handles the multi-step reasoning here (filtering, aggregation, topic analysis,
writing and debugging analysis code) more reliably than smaller, faster models.

Type `/model` in the Claude Code panel and select **Opus 4.8** from the list, or
run it directly: `claude --model claude-opus-4-8`.

### Example prompts

These are things you can simply *ask* — no code required.

**Explore & filter**

- *"How many posts are there per month in 2024? Show it as a table."*
- *"Show me the 10 longest posts by word count."*
- *"How many posts are media-only (no text), and what share of the total is that?"*
- *"List every re-truth (`is_retruth` = true) and which account it came from."*

**Search & summarize**

- *"Find every post that mentions 'x' and summarize the main themes."*
- *"Search the video transcripts for mentions of the 'x' and quote the 5 most
  notable passages."*
- *"Summarize what Trump posted about during the week of 'x'"*

**Visualize**

- *"Plot daily posting volume across the whole dataset and highlight the 10
  busiest days."*
- *"Make an interactive Plotly chart of posts per week, colored by whether they
  contain media."*
- *"Generate a calendar heatmap of posting activity for 2025."*
- *"Show a bar chart of the most frequently used meaningful words across all
  posts (excluding common function words such as 'the', 'and', 'is')."*

**Transform & export**

- *"Export all 2023 posts that have transcripts to a CSV called
  `x.csv`."*
- *"Convert the dataset to Parquet with the flattened analysis columns."*
- *"Create a table of post counts by day of week and hour of day."*

**Deeper analysis**

- *"What were the top 10 topics in posts from early 2025? Give example posts for
  each."*
- *"Compare the vocabulary used in 2022 vs 2026 — which words are distinctive to
  each year?"*
- *"Score each post's sentiment and plot the monthly average over time."*

### Why save findings to Jupyter notebooks

Claude Code is fast for exploration — you can ask questions, iterate, and get
answers in seconds. But chat sessions are ephemeral: once the conversation is
gone, so is the code. Jupyter notebooks are the standard tool researchers and
data scientists use to make that work *permanent and reproducible*.

A notebook stores code, outputs, and prose in a single file. Every chart, table,
and intermediate result is embedded alongside the code that produced it, so
anyone (including future you) can open it, read the reasoning, re-run the cells
to reproduce the results, and extend the analysis from where you left off. This
is why notebooks are the dominant format for published data science work and
academic research: they function simultaneously as a lab notebook, a report, and
a runnable program.

**Recommended workflow**

1. **Explore with Claude Code.** Ask questions conversationally — Claude writes
   and runs the code for you, you see the results immediately. Use this phase to
   discover what's interesting: spikes in posting volume, recurring topics,
   sentiment shifts, unusual patterns.

2. **Identify something worth keeping.** Once you find an analysis you want to
   preserve — a chart, a filtered dataset, a statistical summary — ask Claude to
   save it.

3. **Have Claude write it to a notebook.** Say something like:
   *"Save this sentiment analysis as a Jupyter notebook at
   `notebooks/sentiment_over_time.ipynb`, with a markdown cell explaining what
   we found."* Claude creates the notebook with the code, outputs, and a plain-
   English explanation already filled in.

4. **Re-run and extend in VS Code.** Open the notebook in VS Code (Jupyter
   extension required — see [Setting up Jupyter notebooks in VS Code](#setting-up-jupyter-notebooks-in-vs-code)),
   re-run all cells to verify it reproduces cleanly, then add your own
   annotations or extend the analysis further.

This pattern gives you the speed of AI-assisted exploration and the permanence
and reproducibility of a proper research record.

## Source & attribution

Data is scraped from [trumpstruth.org](https://trumpstruth.org), an archive of
Truth Social posts maintained as a project of Defending Democracy Together.