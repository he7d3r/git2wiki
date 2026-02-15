# git2wiki

`git2wiki` is a Pywikibot-based script that synchronizes JavaScript and CSS pages on a MediaWiki site with source files from local Git repositories.

It scans one or more local repositories, processes `.js` and `.css` files (including optional JS minification), wraps them appropriately for on-wiki usage, and publishes them to wiki pages under a configurable prefix. All behavior is controlled via a YAML configuration file.

---

## What It Does

At a high level, the script:

1. Scans a configured root directory for repositories.
2. Looks for files under a configurable `src/` directory (by default).
3. For each `.js` and `.css` file:
   - Optionally minifies JavaScript.
   - Wraps content in `<nowiki>` blocks.
   - Optionally injects a tracking comment.
   - Builds an edit summary referencing the GitHub repository.
4. Publishes the result to a MediaWiki site using Pywikibot.
5. Optionally updates a global wiki page defined in the configuration.

### `<nowiki>` Wrapping

MediaWiki parses JS/CSS pages as normal wikitext. This can cause unintended behavior if the source code contains:

- `{{template}}`-like patterns inside strings
- `[[Category:...]]` links
- Other wiki syntax

All code is therefore wrapped in `<nowiki>` to prevent template substitution, category assignment, and other wikitext parsing side effects. This guarantees that the published script matches the repository content exactly.

### Tracking Comment

MediaWiki does not currently provide a proper interface for cross-wiki gadget or user script usage statistics (see [T34858](https://phabricator.wikimedia.org/T34858) and [T3886](https://phabricator.wikimedia.org/T3886)).

As a workaround, some script authors inject synthetic links (e.g. `[[File:UserName Script.js]]`) so that `Special:GlobalUsage` or `Special:WhatLinksHere` can be used to monitor usage.

The optional `tracking_template` automates this pattern, enabling:

- Cross-wiki usage discovery
- Safer deprecation and breaking-change notifications
- Script maintenance visibility

### `{{subst:...}}` in `global.js`

The example `global.js` uses `{{subst:...}}` to aggregate multiple JS subpages into a single script:

```
{{<includeonly>subst:</includeonly>User:A/Tools/B.js}}
{{<includeonly>subst:</includeonly>User:A/Tools/C.js}}
```

Using `subst:` inserts the referenced page contents at save time, effectively producing a compiled global script from modular subpages.

---

## Requirements

- Python 3.10+
- A working Pywikibot installation and user configuration
- Node.js (required by `execjs` for JS minification)

---

## Setup with Poetry

Clone the repository and install dependencies:

```bash
git clone https://github.com/he7d3r/git2wiki.git
cd git2wiki
poetry install
```

Activate the virtual environment:
```bash
poetry shell
```

Ensure Pywikibot is correctly configured (user-config.py, family, lang, etc.) according to the [Pywikibot documentation](https://www.mediawiki.org/wiki/Manual:Pywikibot/Installation).

---

## Configuration

All behavior is controlled by a YAML configuration file.

Copy the generic `config.example.yaml` and adapt it to your needs:

```bash
cp config.example.yaml config.yaml
nano config.yaml
```

### Key Fields

- `github_user`: GitHub username used to construct repository URLs.
- `user_prefix`: Wiki page prefix where files will be published.
- `root_dir`: Root directory containing your local repositories.
- `repo_filter`: Optional substring filter for filenames.
- `tracking_template`: Optional comment injected at the top of each page.
- `wrapping`: Defines how JS and CSS are wrapped on-wiki.
- `global_page`: Optional page that is always updated.

Environment variables like `$HOME` are supported in `root_dir`.

---

## Expected Repository Structure

By default, the script assumes:

```
<root_dir>/
  repo1/
    src/
      file.js
      file.css
  repo2/
    src/
      ...
```

The `src` directory name can be changed via:

```yaml
paths:
  src_directory_name: "src"
```

---

## Running the Script

From your Pywikibot directory:

```bash
python pwb.py git2wiki.py -configfile:/full/path/to/config.yaml
```

The `-configfile` parameter must point to your YAML configuration file.

---

## Typical Workflow

1. Update your local Git repositories.
2. Run `git2wiki`.
3. The script publishes updated JS/CSS pages to your wiki.
4. Review edits as needed.

---

## Notes

- JavaScript files are minified using `uglipyjs` (if available).
- If minification fails, the original code is used.
- All configuration is externalized; the script contains no hard-coded usernames or paths.
- Designed to remain small, explicit, and easy to adapt.

---

## License

[MIT License](./LICENSE).
