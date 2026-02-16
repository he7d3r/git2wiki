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
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Iterable

import execjs
import pywikibot
import pywikibot.bot
import pywikibot.site
import uglipyjs
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

# ============================================================
# Configuration Models
# ============================================================


class PathsConfig(BaseModel):
    src_directory_name: str = "src"


class SummaryConfig(BaseModel):
    github: str = "Sync with {repo_url}"
    uglify: str = "minify with UgliPyJS {version}"


class WrappingTemplates(BaseModel):
    header: str
    footer: str


class WrappingConfig(BaseModel):
    javascript: WrappingTemplates
    css: WrappingTemplates


class GlobalPageConfig(BaseModel):
    enabled: bool = False
    title: str
    content: str
    summary: str = "Update"


class SyncConfig(BaseModel):
    github_user: str
    user_prefix: str
    root_dir: Path

    allow_null_edits: bool = False
    repo_filter: str | None = None
    tracking_template: str | None = None

    paths: PathsConfig = Field(default_factory=PathsConfig)
    summaries: SummaryConfig = Field(default_factory=SummaryConfig)
    wrapping: WrappingConfig
    global_page: GlobalPageConfig | None = None

    @field_validator("root_dir", mode="before")
    @classmethod
    def expand_path(cls, v):
        if isinstance(v, str):
            v = os.path.expandvars(v)
            v = os.path.expanduser(v)
        return Path(v)


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
# Infrastructure
# ============================================================


class WikiPublisher:
    def __init__(self, site: pywikibot.site.BaseSite, allow_null_edits: bool):
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
        src_name = self.config.paths.src_directory_name

        for dirpath, _, files in os.walk(self.config.root_dir):
            if not dirpath.endswith(f"/{src_name}"):
                continue

            repo_name = Path(dirpath).parts[-2]

            for name in files:
                if not name.lower().endswith((".js", ".css")):
                    continue

                if self.config.repo_filter and self.config.repo_filter not in name:
                    continue

                filepath = Path(dirpath) / name
                content = filepath.read_text(encoding="utf-8")

                yield SourceFile(
                    path=filepath,
                    repo_name=repo_name,
                    filename=name,
                    content=content,
                )


# ============================================================
# Services
# ============================================================


class JSMinifier:
    def minify(self, code: str) -> tuple[str, str]:
        try:
            minified = uglipyjs.compile(code, {"preserveComments": "some"})
            if isinstance(minified, bytes):
                minified = minified.decode("utf-8")
            try:
                version = metadata.version("uglipyjs")
            except metadata.PackageNotFoundError:
                version = "unknown"
            return minified, version
        except execjs.ProgramError:
            return code, ""


class GitHubReference:
    def __init__(self, github_user: str):
        self.github_user = github_user

    def repo_url(self, repo_name: str) -> str:
        return f"https://github.com/{self.github_user}/{repo_name}"


# ============================================================
# Page Processors
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

        tracking = ""
        if self.config.tracking_template:
            tracking = self.config.tracking_template.format(title=title)

        wrapping = self.config.wrapping.javascript
        content = wrapping.header.format(tracking=tracking) + minified + wrapping.footer

        summary = self.config.summaries.github.format(
            repo_url=self.github.repo_url(source.repo_name)
        )

        if version:
            summary += "; " + self.config.summaries.uglify.format(version=version)

        return WikiPage(title=title, content=content, summary=summary)


class CssPageProcessor(PageProcessor):
    def __init__(self, config: SyncConfig, github: GitHubReference):
        self.config = config
        self.github = github

    def supports(self, source: SourceFile) -> bool:
        return source.filename.lower().endswith(".css")

    def process(self, source: SourceFile) -> WikiPage:
        title = self.config.user_prefix + source.filename

        tracking = ""
        if self.config.tracking_template:
            tracking = self.config.tracking_template.format(title=title)

        wrapping = self.config.wrapping.css
        content = (
            wrapping.header.format(tracking=tracking) + source.content + wrapping.footer
        )

        summary = self.config.summaries.github.format(
            repo_url=self.github.repo_url(source.repo_name)
        )

        return WikiPage(title=title, content=content, summary=summary)


class GlobalPageProcessor:
    def __init__(self, config: SyncConfig):
        self.config = config

    def build(self) -> WikiPage:
        gp = self.config.global_page
        assert gp is not None
        return WikiPage(title=gp.title, content=gp.content, summary=gp.summary)


# ============================================================
# Configuration Loading
# ============================================================


def load_config_from_yaml(path: Path) -> SyncConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SyncConfig.model_validate(raw)


def parse_cli_config_path() -> Path:
    config_path = None

    for arg in pywikibot.handle_args():
        option, _, value = arg.partition(":")
        if option == "-configfile":
            config_path = Path(value)

    if not config_path:
        pywikibot.bot.suggest_help(
            missing_parameters=["-configfile:<path>"],
            additional_text="Usage: git2wiki.py -configfile:/path/config.yaml",
        )
        sys.exit(2)

    return config_path


# ============================================================
# Main
# ============================================================


def main() -> None:
    config_path = parse_cli_config_path()

    try:
        config = load_config_from_yaml(config_path)
    except ValidationError as e:
        print(e)
        sys.exit(1)

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

    if config.global_page and config.global_page.enabled:
        global_processor = GlobalPageProcessor(config)
        publisher.publish(global_processor.build())


if __name__ == "__main__":
    main()
