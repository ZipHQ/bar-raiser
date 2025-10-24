from __future__ import annotations

import os
from datetime import datetime
from enum import StrEnum
from logging import INFO, basicConfig, getLogger
from os import chdir, environ
from pathlib import Path
from subprocess import check_output
from sys import stdout
from typing import TYPE_CHECKING, Literal, TypedDict
from zoneinfo import ZoneInfo

from git.repo import Repo
from github import Github, GithubIntegration, InputGitTreeElement
from github.CheckRun import CheckRun

if TYPE_CHECKING:
    from github.PullRequest import PullRequest
    from github.Repository import Repository

ANNOTATION_PAGE_SIZE = 50

logger = getLogger(__name__)


def get_github() -> Github:
    integration = GithubIntegration(environ["APP_ID"], environ["PRIVATE_KEY"])
    owner = environ["GITHUB_REPOSITORY_OWNER"]
    short_repo = environ["GITHUB_REPOSITORY"][len(owner) + 1 :]
    install = integration.get_installation(owner, short_repo)
    token = integration.get_access_token(install.id).token
    return Github(token)


def get_github_repo() -> Repository:
    github = get_github()
    logger.info(github.get_rate_limit())
    repo_name = environ["GITHUB_REPOSITORY"]
    return github.get_repo(repo_name)


def get_pull_request() -> PullRequest | None:
    try:
        return get_github_repo().get_pull(int(environ["PULL_NUMBER"]))
    except Exception:
        return None


def get_head_sha() -> str:
    if get_pull_request():  # pull requests have a virtual merge commit
        return get_git_repo().head.commit.parents[-1].hexsha
    return get_git_repo().head.commit.hexsha


def has_previous_issue_comment(pull: PullRequest, author: str, body: str) -> bool:
    for comment in pull.get_issue_comments():
        if comment.user.login == author and body in comment.body:
            return True
    return False


def get_git_repo() -> Repo:
    return Repo(".", search_parent_directories=True)


class Annotation(TypedDict):
    path: str
    start_line: int
    end_line: int
    annotation_level: str
    message: str


class Action(TypedDict):
    label: str
    description: str
    identifier: str


def create_check_run(
    *,
    repo: Repository,
    name: str,
    head_sha: str,
    conclusion: Literal["action_required", "success", "failure"],
    title: str,
    summary: str,
    annotations: list[Annotation],
    actions: list[Action],
) -> list[CheckRun]:
    checks = list[CheckRun]()
    while True:
        batch, annotations = (
            annotations[:ANNOTATION_PAGE_SIZE],
            annotations[ANNOTATION_PAGE_SIZE:],
        )
        check = repo.create_check_run(
            name=name,
            head_sha=head_sha,
            conclusion=conclusion,
            output={  # pyright: ignore[reportArgumentType]
                "title": title,
                "summary": summary,
                "annotations": batch,
            },
            actions=actions,  # pyright: ignore[reportArgumentType]
        )
        logger.info(check.html_url)
        checks.append(check)
        if len(annotations) == 0:
            break
    return checks


def commit_changes(
    repo: Repository, branch: str, sha: str, paths: list[str], commit_message: str
) -> None:
    batch_size = 200
    num_batches = len(paths) // batch_size + 1
    count = 0
    cwd = os.getcwd()
    while paths:
        elements: list[InputGitTreeElement] = []
        for path in paths[:batch_size]:
            content = open(path, encoding="utf-8").read() if Path(path).exists() else ""
            blob = repo.create_git_blob(content, "utf-8")
            elements.append(InputGitTreeElement(path, "100644", "blob", sha=blob.sha))
        existing_tree = repo.get_git_tree(sha)
        existing_commit = repo.get_git_commit(sha)
        new_tree = repo.create_git_tree(elements, existing_tree)
        message = (
            f"{commit_message} ({count + 1}/{num_batches})"
            if num_batches > 1
            else commit_message
        )
        new_commit = repo.create_git_commit(message, new_tree, [existing_commit])
        repo.get_git_ref(f"heads/{branch}").edit(new_commit.sha)
        sha = new_commit.sha
        paths = paths[batch_size:]
        count += 1


def get_updated_paths(pull: PullRequest) -> list[str]:
    return [
        file.filename
        for file in pull.get_files()
        if file.status != "removed" and file.filename.endswith(".py")
    ]


def run_codemod_and_commit_changes(
    github_repo: Repository,
    pull_number: int,
    commands: list[list[str]],
    commit_message: str,
    run_on_updated_paths: bool,
) -> None:
    pull = github_repo.get_pull(pull_number)
    if run_on_updated_paths:
        pull_updated_paths = get_updated_paths(pull)
        commands = [command + pull_updated_paths for command in commands]

    for command in commands:
        check_output(command)

    git_repo = get_git_repo()
    updated_paths: list[str] = [
        i.b_path  # pyright: ignore[reportUnknownMemberType]
        for i in git_repo.index.diff(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            None
        )
    ]
    if run_on_updated_paths:
        updated_paths = [path for path in updated_paths if path in updated_paths]

    logger.info(f"Updated paths: {updated_paths}")
    if len(updated_paths) == 0:
        msg = "No updated paths to commit."
        pull.create_issue_comment(msg)
        logger.info(msg)
    else:
        commit_changes(
            repo=github_repo,
            branch=pull.head.ref,
            sha=pull.head.sha,
            paths=updated_paths,
            commit_message=commit_message,
        )
        logger.info(f"Changes committed to {pull.html_url}.")


def create_a_pull_request(
    github_repo: Repository,
    codemod: str,
    actor: str,
    extra_body: str = "",
) -> None:
    git_repo = get_git_repo()
    codemod_name = (
        codemod.strip().split("codemod ")[1].split(" ")[0]
        if "codemod " in codemod
        else codemod.replace(" ", "-")
    )
    updated_paths: list[str] = [
        i.b_path  # pyright: ignore[reportUnknownMemberType]
        for i in git_repo.index.diff(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            None
        )
    ]
    if len(updated_paths) == 0:
        msg = "No updated paths to commit."
        logger.info(msg)
    else:
        logger.info(f"Updated paths: {updated_paths}")
        commit = github_repo.get_commit("master")
        time = datetime.now(ZoneInfo("US/Pacific")).strftime("%Y%m%d-%H-%M-%S")
        branch = f"codemod-{codemod_name}-{actor}-{time}"
        ref = f"refs/heads/{branch}"
        github_repo.create_git_ref(ref, commit.sha)
        title = f"Codemod {codemod_name} by {actor} at {time}"
        commit_changes(
            repo=github_repo,
            branch=branch,
            sha=commit.sha,
            paths=updated_paths,
            commit_message=title,
        )
        body = f"Codemod Command: `{codemod}`\nCreated from {environ['GITHUB_SERVER_URL']}/{environ['GITHUB_REPOSITORY']}/actions/runs/{environ['GITHUB_RUN_ID']} by {actor}"
        if extra_body:
            body += f"\n\n{extra_body}"
        pull = github_repo.create_pull(title=title, body=body, base="master", head=ref)
        pull.add_to_assignees(actor)
        pull.enable_automerge(merge_method="SQUASH")
        logger.info(f"Changes committed to {pull.html_url}")


def initialize_logging() -> None:
    basicConfig(
        stream=stdout,
        level=INFO,
        format="%(asctime)s %(levelname)s %(module)s - %(funcName)s: %(message)s",
    )


class Autofixes(StrEnum):
    RUFF = "autofix-ruff"
    PYRIGHT_IGNORES = "pyright-ignores"
