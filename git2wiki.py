#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Sync git repositories with wiki pages.

Architecture:
- Domain layer: SourceFile, WikiPage, PageProcessor strategies
- Infrastructure: WikiPublisher (pywikibot), FileSystemScanner
- Config: SyncConfig
"""

from __future__ import annotations

import os
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import execjs
import pkg_resources
import pywikibot
import pywikibot.bot
import uglipyjs

# ============================================================
# Configuration
# ============================================================


@dataclass(frozen=True)
class SyncConfig:
    user_prefix: str
    github_user: str
    tracking_template: str | None
    allow_null_edits: bool
    repo_filter: str | None
    root_dir: Path
    github_summary_template: str
    uglify_summary_template: str


def parse_args() -> SyncConfig:
    user_prefix: str | None = None
    github_user: str | None = None
    tracking: str | None = None
    allow_null_edits = False
    repo_filter: str | None = None
    root_dir: Path | None = None

    for arg in pywikibot.handle_args():
        option, _, value = arg.partition(":")
        if not value and option not in ("-all", "-track"):
            pywikibot.error(f"Option {option} requires a value")

        if option == "-all":
            allow_null_edits = True
        elif option == "-track":
            tracking = "[[File:%s]] (workaround for [[phab:T35355]])"
        elif option == "-prefix":
            user_prefix = value
        elif option == "-repo":
            repo_filter = value
        elif option == "-mypath":
            root_dir = Path(value)
        elif option == "-github":
            github_user = value

    missing_params = []
    if not github_user:
        missing_params.append("-github:<username>")
    if not user_prefix:
        missing_params.append("-prefix:<value>")

    if missing_params:
        additional_text = (
            "\nUsage: git2wiki.py -github:<username> [options]\n\n"
            "Required parameters:\n"
            "  -github:<username>    GitHub username for the repository\n\n"
            "Optional parameters:\n"
            "  -prefix:<value>       Wiki page prefix (e.g.: User:A/B/)\n"
            "  -repo:<name>          Filter by repository (default: all)\n"
            "  -mypath:<path>        Root directory (default: current)\n"
            "  -all                  Allow null edits\n"
            "  -track                Add tracking comment to pages"
        )
        pywikibot.bot.suggest_help(
            missing_parameters=missing_params, additional_text=additional_text
        )
        sys.exit(2)

    assert user_prefix is not None
    assert github_user is not None

    return SyncConfig(
        user_prefix=user_prefix,
        github_user=github_user,
        tracking_template=tracking,
        allow_null_edits=allow_null_edits,
        repo_filter=repo_filter,
        root_dir=root_dir or Path.cwd(),
        # TODO: Add git hash/version as in
        # "Sync with https://github.com/FOO/BAR (v9.9.9 or HASH)"
        github_summary_template="Sync with %s",
        uglify_summary_template="minify with UgliPyJS %s",
    )


# ============================================================
# Domain Models
# ============================================================


@dataclass(frozen=True)
class SourceFile:
    path: Path
    repo_name: str
    filename: str
    content: str


@dataclass(frozen=True)
class WikiPage:
    title: str
    content: str
    summary: str


# ============================================================
# Infrastructure Services
# ============================================================


class WikiPublisher:
    def __init__(self, site: pywikibot.BaseSite, allow_null_edits: bool):
        self.site = site
        self.allow_null_edits = allow_null_edits

    def publish(self, page: WikiPage) -> None:
        wiki_page = pywikibot.Page(self.site, page.title)
        wiki_page.text = page.content
        wiki_page.save(page.summary, minor=False, force=self.allow_null_edits)


class FileSystemScanner:
    def __init__(self, config: SyncConfig):
        self.config = config

    def scan(self) -> Iterable[SourceFile]:
        # Assume the structure is <mypath>/<repo>/src/<title.(js|css)>
        for dirpath, _, files in os.walk(self.config.root_dir):
            if not dirpath.endswith("/src"):
                continue

            repo_name = Path(dirpath).parts[-2]

            for name in files:
                if not name.lower().endswith((".js", ".css")):
                    continue

                if self.config.repo_filter and self.config.repo_filter not in name:
                    continue

                filepath = Path(dirpath) / name
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                yield SourceFile(
                    path=filepath,
                    repo_name=repo_name,
                    filename=name,
                    content=content,
                )


# ============================================================
# Services (Ports)
# ============================================================


class JSMinifier:
    def minify(self, code: str) -> tuple[str, str]:
        try:
            minified = uglipyjs.compile(code, {"preserveComments": "some"})
            if isinstance(minified, bytes):
                minified = minified.decode("utf-8")
            version = pkg_resources.get_distribution("uglipyjs").version
            return minified, version
        except execjs.ProgramError:
            return code, ""


class GitHubReference:
    def __init__(self, github_user: str):
        self.github_user = github_user

    def repo_url(self, repo_name: str) -> str:
        return f"https://github.com/{self.github_user}/{repo_name}"


# ============================================================
# Page Processors (Strategy Pattern)
# ============================================================


class PageProcessor(ABC):
    @abstractmethod
    def supports(self, source: SourceFile) -> bool:
        pass

    @abstractmethod
    def process(self, source: SourceFile) -> WikiPage:
        pass


class JavaScriptPageProcessor(PageProcessor):
    def __init__(
        self,
        config: SyncConfig,
        github: GitHubReference,
        minifier: JSMinifier,
    ):
        self.config = config
        self.github = github
        self.minifier = minifier

    def supports(self, source: SourceFile) -> bool:
        return source.filename.lower().endswith(".js")

    def process(self, source: SourceFile) -> WikiPage:
        minified, version = self.minifier.minify(source.content)

        title = self.config.user_prefix + source.filename
        content = self._wrap_code(minified, title)

        summary = self.config.github_summary_template % (
            self.github.repo_url(source.repo_name)
        )

        if version:
            summary += "; " + self.config.uglify_summary_template % version

        return WikiPage(title=title, content=content, summary=summary)

    def _wrap_code(self, code: str, title: str) -> str:
        wrapped = re.sub(
            r"(/\*\*\n \*.+? \*/\n)",
            r"\1// <nowiki>\n",
            code,
            flags=re.DOTALL,
        )
        if wrapped == code:
            wrapped = "// <nowiki>\n" + code
        wrapped += "\n// </nowiki>"

        if self.config.tracking_template:
            wrapped = "// " + (self.config.tracking_template % title) + "\n" + wrapped

        return wrapped


class CssPageProcessor(PageProcessor):
    def __init__(self, config: SyncConfig, github: GitHubReference):
        self.config = config
        self.github = github

    def supports(self, source: SourceFile) -> bool:
        return source.filename.lower().endswith(".css")

    def process(self, source: SourceFile) -> WikiPage:
        title = self.config.user_prefix + source.filename

        content = "/* <nowiki> */\n" + source.content + "\n/* </nowiki> */"
        if self.config.tracking_template:
            content = (
                "/* " + (self.config.tracking_template % title) + " */\n" + content
            )

        summary = self.config.github_summary_template % (
            self.github.repo_url(source.repo_name)
        )

        return WikiPage(title=title, content=content, summary=summary)


class GlobalPageProcessor:
    """
    Special page not based on filesystem input.
    """

    def __init__(self, config: SyncConfig):
        self.config = config

    def build(self) -> WikiPage:

        title = "User:He7d3r/global.js"
        content = (
            "// [[File:User:He7d3r/global.js]] (workaround for"
            " [[phab:T35355]])\n//{ {subst:User:He7d3r/Tools.js}}\n"
            "{{subst:User:He7d3r/Tools.js}}"
        )

        return WikiPage(title=title, content=content, summary="Update")


# ============================================================
# Orchestration
# ============================================================


def main() -> None:
    config = parse_args()

    site = pywikibot.Site()
    publisher = WikiPublisher(site, config.allow_null_edits)

    github = GitHubReference(config.github_user)
    minifier = JSMinifier()

    processors: list[PageProcessor] = [
        JavaScriptPageProcessor(config, github, minifier),
        CssPageProcessor(config, github),
    ]

    scanner = FileSystemScanner(config)

    for source in scanner.scan():
        for processor in processors:
            if processor.supports(source):
                page = processor.process(source)
                publisher.publish(page)
                break

    # Global page
    global_processor = GlobalPageProcessor(config)
    publisher.publish(global_processor.build())


if __name__ == "__main__":
    main()
