"""``tools/scal_pr.py``: agent scala PR tylko przy zielonym CI na HEAD, werdykcie PASS dla HEAD, opisie z sekcjami wzoru
skilla ``pr`` i scaleniu z bieżącą bazą, które przechodzi ruff i mypy.

Testy biegną na prawdziwym Gicie z repozytorium bare jako ``origin`` (z ``refs/pull/N/head`` jak na GitHubie)
i na prawdziwym ``tools/ci_lokalnie.py --tylko ruff,mypy`` na małym kodzie. Atrapa ``gh`` podaje stan PR i zapisuje
wywołania ``gh pr merge`` zamiast scalać.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.fixtures import opisy_pr
from tests.fixtures.git_repo import commit, git, repository

import scal_pr

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Atrapa gh to skrypt sh.")

TOOLS = Path(__file__).resolve().parents[1] / "tools"
TEMPLATE = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "pr" / "SKILL.md"
BODY = opisy_pr.wzor("Cel.")
SUM = "def suma(a: int, b: int) -> int:\n    return a + b\n"
PYPROJECT = '[tool.ruff]\ninclude = ["kod/**/*.py"]\n\n[tool.mypy]\nstrict = true\nfiles = ["kod"]\n'
CLEANUP = 'import pathlib\n\npathlib.Path("posprzatane").write_text("tak")\nprint("SPRZĄTANIE OK | 0 usuniętych")\n'
FAKE_GH = """\
import json, os, pathlib, subprocess, sys, time

here = pathlib.Path(sys.argv[0]).parent
arguments = sys.argv[1:]
pulls = json.loads((here / "pulls.json").read_text())
issues = json.loads((here / "issues.json").read_text())
repo_view = (here / "repo_view").read_text()
markdown = json.loads((here / "markdown.json").read_text())


def git(*command):
    identity = {f"GIT_{role}_{key}": value for role in ("AUTHOR", "COMMITTER") for key, value in (("NAME", "gh"), ("EMAIL", "gh@example.com"))}
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", *command], cwd=here.parent / "origin.git", env={**os.environ, **identity}, capture_output=True, text=True, check=True)
    return done.stdout.strip()


REPO = "maximiseartai/MAXIMISEART-Dad"


def merge(pull):
    base = git("rev-parse", "refs/heads/main")
    tree = git("merge-tree", "--write-tree", base, pull["headRefOid"])
    merge = git("commit-tree", tree, "-p", base, "-p", pull["headRefOid"], "-m", "Merge")
    git("update-ref", "refs/heads/main", merge)
    pull.update(state="MERGED", mergeCommit=None if pull.get("poMergeu") else {"oid": merge})


def log(name, entry):
    with (here / name).open("a") as file:
        file.write(json.dumps(entry) + "\\n")


if arguments[:2] == ["api", "graphql"]:
    fields = dict(argument.split("=", 1) for argument in arguments[3::2])
    if "enqueuePullRequest" in fields["query"]:
        pull = next(pull for pull in pulls.values() if f"PR_{pull['number']}" == fields["id"])
        if fields["head"] != pull["headRefOid"]:
            sys.exit("gh: Expected head commit to match")
        pull["kolejka"]["wpis"] = {"state": "AWAITING_CHECKS", "position": 1}
        log("enqueues.jsonl", fields["head"])
    else:
        log("queue_queries.jsonl", fields["number"])
        pull = pulls[fields["number"]]
        queue = pull.get("kolejka") or {"wlaczona": False, "wpis": None, "usuniecia": 0}
        if queue["wpis"] and queue.get("potem") == "scala":
            merge(pull)
            queue["wpis"] = None
        elif queue["wpis"] and queue.get("potem") == "usuwa":
            queue.update(wpis=None, usuniecia=queue["usuniecia"] + 1)
        removed = [{"reason": "Required status check failed"}] if queue["usuniecia"] else []
        answer = {
            "id": f"PR_{pull['number']}",
            "state": pull["state"],
            "isMergeQueueEnabled": queue["wlaczona"],
            "mergeCommit": pull["mergeCommit"],
            "mergeQueueEntry": queue["wpis"],
            "timelineItems": {"filteredCount": queue["usuniecia"], "nodes": removed},
        }
        print(json.dumps({"data": {"repository": {"pullRequest": answer}}}))
    (here / "pulls.json").write_text(json.dumps(pulls))
elif arguments[:2] == ["pr", "view"]:
    pull = pulls[arguments[2]]
    if pull.get("poMergeu") == "błąd" and pull["state"] == "MERGED":
        sys.exit("gh: HTTP 502")
    print(json.dumps({field: pull[field] for field in arguments[arguments.index("--json") + 1].split(",")}))
elif arguments[:2] == ["pr", "merge"]:
    pull = pulls[arguments[2]]
    if arguments[arguments.index("--match-head-commit") + 1] != pull["headRefOid"]:
        sys.exit("HEAD PR zmienił się")
    merge(pull)
    (here / "pulls.json").write_text(json.dumps(pulls))
    log("merges.jsonl", arguments)
elif arguments == ["api", "markdown", "--input", "-"]:
    request = json.loads(sys.stdin.read())
    log("renders.jsonl", request)
    if request.keys() != {"text", "mode", "context"} or request["mode"] != "gfm" or request["context"].casefold() != REPO.casefold():
        sys.exit(f"atrapa gh nie zna renderowania: {request}")
    html = markdown.get(request["text"], "gh: atrapa gh nie zna opisu")
    if html == "zawiesza":
        time.sleep(60)
    elif html.startswith("gh: "):
        sys.exit(html)
    print(html, end="")
elif arguments[0] == "api" and arguments[1].startswith(f"repos/{REPO}/issues/"):
    number = arguments[1].rpartition("/")[2]
    if issues.get(number) == "zawiesza":
        time.sleep(60)
    elif number in issues:
        print(issues[number])
    else:
        sys.exit("gh: Not Found (HTTP 404)")
elif arguments[:2] == ["repo", "view"]:
    log("repo_views.jsonl", arguments)
    if repo_view.startswith("gh: "):
        sys.exit(repo_view)
    print(repo_view)
elif arguments[:2] == ["issue", "close"]:
    issues[arguments[2]] = json.dumps({"state": "closed"})
    (here / "issues.json").write_text(json.dumps(issues))
    log("closed.jsonl", arguments)
else:
    sys.exit(f"atrapa gh nie zna: {arguments}")
"""


URL = "https://github.com/o/r/actions/runs/4077/job/1"


def _check_run(status: str, conclusion: str | None, *, workflow: str = "CI", name: str = "Required CI status") -> dict[str, str | None]:
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion, "workflowName": workflow, "detailsUrl": URL}


GREEN = [
    {"__typename": "CheckRun", "name": "Ruff", "status": "COMPLETED", "conclusion": "SUCCESS", "workflowName": "CI"},
    _check_run("COMPLETED", "SUCCESS"),
]
COMMIT_STATUS = {"__typename": "StatusContext", "context": "Required CI status", "state": "SUCCESS"}
NOT_ACTIONS = "CI: brak „Required CI status” z GitHub Actions na HEAD"
NO_PASS = "werdykt: brak komentarza ani recenzji „WERDYKT: PASS {head}”"
OBJECTION = "werdykt: FAIL dla {short} bez nowszego „WERDYKT: PASS {head}”"


class FakeGitHub:
    def __init__(self, tmp_path: Path, files: dict[str, str]) -> None:
        origin = tmp_path / "origin.git"
        git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(origin))
        self.origin = origin
        self.checkout = repository(
            tmp_path / "checkout",
            {
                ".gitignore": ".mypy_cache/\n.ruff_cache/\n__pycache__/\nposprzatane\n",
                "pyproject.toml": PYPROJECT,
                ".agents/skills/pr/SKILL.md": TEMPLATE.read_text(encoding="utf-8"),
                **files,
            },
        )
        for tool in ("scal_pr.py", "scalenia_pr.py"):
            shutil.copy2(TOOLS / tool, self.checkout / "tools" / tool)
        git(self.checkout, "checkout", "--quiet", "-b", "main")
        self.start = commit(self.checkout, "start")
        git(self.checkout, "remote", "add", "origin", str(origin))
        git(self.checkout, "push", "--quiet", "origin", "main")
        self.bin = _fake_gh(tmp_path)
        self.pulls: dict[str, dict[str, object]] = {}
        self.issues: dict[str, str] = {}
        self.repo_view = _repo_view("main")  # zaczęte od „gh: ” to błąd ``gh repo view``
        self.markdown = opisy_pr.rendered()  # HTML opisu, a jak w ``answer_issue`` błąd albo ``zawiesza``
        self.written = 0

    def open_pull(self, number: int, files: dict[str, str], *, parent: str = "") -> str:
        """HEAD nowego PR z zielonym CI i bez werdyktu: commit ``files`` na ``parent`` (domyślnie commit ``start``)."""

        head = self.commit_on(parent or self.start, files, f"PR {number}")
        git(self.checkout, "push", "--quiet", "origin", f"{head}:refs/pull/{number}/head")
        self.pulls[str(number)] = {
            "number": number,
            "title": f"PR {number}",
            "body": BODY,
            "state": "OPEN",
            "isDraft": False,
            "isCrossRepository": False,
            "baseRefName": "main",
            "headRefOid": head,
            "statusCheckRollup": GREEN,
            "comments": [],
            "reviews": [],
            "mergeCommit": None,
            "url": f"https://github.com/{opisy_pr.REPO}/pull/{number}",
            "closingIssuesReferences": [],
        }
        self._save()
        return head

    def commit_on(self, parent: str, files: dict[str, str], subject: str) -> str:
        git(self.checkout, "checkout", "--quiet", "--detach", parent)
        for name, text in files.items():
            (self.checkout / name).parent.mkdir(parents=True, exist_ok=True)
            (self.checkout / name).write_text(text, encoding="utf-8")
        made = commit(self.checkout, subject)
        git(self.checkout, "checkout", "--quiet", "main")
        return made

    def update(self, number: int, **fields: object) -> None:
        self.pulls[str(number)].update(fields)
        self._save()

    def comment(self, number: int, body: str, association: str = "OWNER") -> None:
        self._write(number, "comments", {"body": body, "authorAssociation": association, "createdAt": self._now()})

    def review(self, number: int, body: str, association: str = "OWNER", *, state: str = "COMMENTED") -> None:
        self._write(number, "reviews", {"body": body, "authorAssociation": association, "state": state, "submittedAt": self._now()})

    def _now(self) -> str:
        self.written += 1
        return f"2026-10-24T03:{self.written // 60:02d}:{self.written % 60:02d}Z"

    def _write(self, number: int, kind: str, verdict: dict[str, str]) -> None:
        verdicts = self.pulls[str(number)][kind]
        assert isinstance(verdicts, list)
        verdicts.append({**verdict, "author": {"login": "recenzent"}})
        self._save()

    def push_main(self, files: dict[str, str]) -> str:
        for name, text in files.items():
            (self.checkout / name).write_text(text, encoding="utf-8")
        head = commit(self.checkout, "main idzie dalej")
        git(self.checkout, "push", "--quiet", "origin", "main")
        return head

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.checkout / "tools" / "scal_pr.py"), *arguments],
            cwd=self.checkout,
            env={**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            check=False,
        )

    def open_issues(self, *numbers: int, state: str = "open") -> None:
        self.answer_issue(*numbers, answer=json.dumps({"state": state}))

    def answer_issue(self, *numbers: int, answer: str) -> None:
        """``gh api`` issue ``numbers`` drukuje ``answer``, a ``zawiesza`` każe mu czekać minutę."""

        self.issues.update(dict.fromkeys(map(str, numbers), answer))
        self._save()

    def merges(self) -> list[list[str]]:
        return self._log("merges.jsonl")

    def queue(self, number: int, then: str) -> None:
        """Baza PR ma kolejkę scaleń, która po wstawieniu PR go scala (``scala``), usuwa (``usuwa``) albo trzyma (``czeka``)."""

        self.update(number, kolejka={"wlaczona": True, "wpis": None, "usuniecia": 0, "potem": then})

    def enqueues(self) -> list[str]:
        """``expectedHeadOid`` każdego wstawienia PR do kolejki scaleń."""

        return [str(head) for head in self._log("enqueues.jsonl")]

    def queue_queries(self) -> int:
        """Ile razy narzędzie pytało GitHuba o stan kolejki scaleń."""

        return len(self._log("queue_queries.jsonl"))

    def closed(self) -> list[list[str]]:
        return self._log("closed.jsonl")

    def repo_views(self) -> list[list[str]]:
        return self._log("repo_views.jsonl")

    def renders(self) -> list[list[str]]:
        return self._log("renders.jsonl")

    def _log(self, name: str) -> list[list[str]]:
        log = self.bin / name
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def _save(self) -> None:
        (self.bin / "pulls.json").write_text(json.dumps(self.pulls), encoding="utf-8")
        (self.bin / "issues.json").write_text(json.dumps(self.issues), encoding="utf-8")
        (self.bin / "repo_view").write_text(self.repo_view, encoding="utf-8")
        (self.bin / "markdown.json").write_text(json.dumps(self.markdown), encoding="utf-8")


def _fake_gh(tmp_path: Path) -> Path:
    """Katalog atrapy ``gh`` bez PR-ów i issues, która renderuje opisy z ``tests/fixtures/opisy_pr.json``."""

    directory = tmp_path / "bin"
    directory.mkdir()
    (directory / "gh.py").write_text(FAKE_GH, encoding="utf-8")
    gh = directory / "gh"
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{directory / "gh.py"}" "$@"\n', encoding="utf-8")
    gh.chmod(0o755)
    for name, empty in (("pulls.json", "{}"), ("issues.json", "{}"), ("repo_view", ""), ("markdown.json", json.dumps(opisy_pr.rendered()))):
        (directory / name).write_text(empty, encoding="utf-8")
    return directory


def _short_github_timeout(github: FakeGitHub) -> str:
    """Commit na ``main`` z ``scalenia_pr.GITHUB_TIMEOUT_S`` równym 3 s, żeby ``gh``, które zawiesza, kończyło się szybko."""

    scalenia = github.checkout / "tools" / "scalenia_pr.py"
    scalenia.write_text(scalenia.read_text(encoding="utf-8").replace("GITHUB_TIMEOUT_S = 60", "GITHUB_TIMEOUT_S = 3"), encoding="utf-8")
    git(github.checkout, "commit", "--quiet", "--all", "--message", "gh po 3 s")
    git(github.checkout, "push", "--quiet", "origin", "main")
    return git(github.checkout, "rev-parse", "HEAD")


def _repo_view(default_branch: str) -> str:
    return json.dumps({"defaultBranchRef": {"name": default_branch}})


def _last_line(answered: subprocess.CompletedProcess[str]) -> str:
    return answered.stdout.rstrip().rpartition("\n")[2]


def test_gotowy_pr_jest_scalany_z_jego_head_a_po_merge_biegnie_sprzatanie(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": CLEANUP})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    main = github.push_main({"kod/nazwa.py": 'NAZWA = "z main"\n'})
    github.comment(1, f"WERDYKT: FAIL {head}\n- krytyczne: brak testu")
    github.comment(1, f"Poprawione w {head[:7]}.")
    github.comment(1, f"WERDYKT: PASS {head}\n- drobne: nazwa")

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a z main {main[:7]}")
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert _last_line(merged) == (
        f"SCAL OK | #1 {head[:7]} | scalony do main jako {merge_commit[:7]} (baza {main[:7]}) | sprzątanie: SPRZĄTANIE OK | 0 usuniętych"
    )
    assert git(github.origin, "rev-list", "--parents", "-n", "1", merge_commit).split()[1:] == [main, head]
    assert github.merges() == [["pr", "merge", "1", "--merge", "--match-head-commit", head]]
    assert (github.checkout / "posprzatane").exists()


@pytest.mark.parametrize(
    ("ci", "comments", "reason"),
    [
        (
            [_check_run("COMPLETED", "FAILURE")],
            [("WERDYKT: PASS {head}", "OWNER")],
            "CI: „Required CI status” FAILURE",
        ),
        (
            [_check_run("IN_PROGRESS", None)],
            [("WERDYKT: PASS {head}", "OWNER")],
            "CI: „Required CI status” IN_PROGRESS",
        ),
        (
            [_check_run("COMPLETED", "FAILURE"), _check_run("COMPLETED", "SUCCESS")],
            [("WERDYKT: PASS {head}", "OWNER")],
            "CI: „Required CI status” FAILURE",
        ),
        (GREEN[:1], [("WERDYKT: PASS {head}", "OWNER")], NOT_ACTIONS),
        ([COMMIT_STATUS], [("WERDYKT: PASS {head}", "OWNER")], NOT_ACTIONS),
        ([_check_run("COMPLETED", "SUCCESS", workflow="")], [("WERDYKT: PASS {head}", "OWNER")], NOT_ACTIONS),
        (GREEN, [], NO_PASS),
        (GREEN, [("WERDYKT: PASS {old}", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "NONE")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "CONTRIBUTOR")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "CONTRIBUTOR", "COMMENTED")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "OWNER", "PENDING")], NO_PASS),
        (GREEN, [("Recenzja: WERDYKT: PASS {head}", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head} — bez uwag", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head7}", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {upper}", "OWNER")], NO_PASS),
        (GREEN, [("**WERDYKT: PASS {head}**", "OWNER")], NO_PASS),
        (GREEN, [("## Werdykt niezależny: PASS", "OWNER")], NO_PASS),
        (GREEN, [("Wygląda dobrze.", "OWNER", "APPROVED")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head}", "OWNER"), ("WERDYKT: FAIL {head}", "MEMBER")], OBJECTION),
        ([_check_run("COMPLETED", "FAILURE")], [], f"CI: „Required CI status” FAILURE; {NO_PASS}"),
    ],
    ids=[
        "ci-czerwone",
        "ci-trwa",
        "ci-czerwone-w-jednym-z-dwoch-przebiegow",
        "ci-bez-wymaganego-checku",
        "ci-tylko-status-commitu",
        "ci-check-spoza-github-actions",
        "bez-werdyktu",
        "pass-dla-starszego-commitu",
        "pass-konta-bez-prawa-zapisu",
        "pass-kontrybutora",
        "pass-w-recenzji-kontrybutora",
        "pass-w-nieopublikowanej-recenzji",
        "pass-nie-w-pierwszej-linii",
        "pass-z-dopiskiem-w-pierwszej-linii",
        "pass-z-7-znakami-sha",
        "pass-z-sha-wielkimi-literami",
        "pass-w-markdownie",
        "pass-w-naglowku",
        "zatwierdzona-recenzja-bez-linii-werdyktu",
        "fail-po-pass",
        "wszystkie-przyczyny-naraz",
    ],
)
def test_bez_zielonego_ci_albo_werdyktu_pass_dla_head_pr_nie_jest_scalany(
    tmp_path: Path, ci: list[dict[str, str | None]], comments: list[tuple[str, ...]], reason: str
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head, statusCheckRollup=ci)
    for body, association, *state in comments:
        text = body.format(head=head, old=old, head7=head[:7], upper=head.upper())
        github.review(1, text, association, state=state[0]) if state else github.comment(1, text, association)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason.format(short=head[:7], head=head)}"
    assert github.merges() == []


@pytest.mark.parametrize(
    ("kind", "objection"),
    [
        ("comment", "WERDYKT: FAIL {head}"),
        ("comment", "WERDYKT: FAIL {head}\n- krytyczne: brak testu"),
        ("comment", "\n\n  WERDYKT: FAIL {head}  \r\n"),
        ("COMMENTED", "WERDYKT: FAIL {head}"),
        ("CHANGES_REQUESTED", "Popraw nazwę funkcji."),
        ("CHANGES_REQUESTED", ""),
    ],
    ids=["komentarz", "komentarz-ze-znaleziskami", "puste-linie-i-odstepy", "recenzja", "prosba-o-zmiany", "prosba-o-zmiany-bez-tresci"],
)
def test_sprzeciw_zaufanego_konta_dla_head_po_pass_blokuje_merge(tmp_path: Path, kind: str, objection: str) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)
    github.comment(1, f"WERDYKT: PASS {head}")
    body = objection.format(head=head)
    github.comment(1, body) if kind == "comment" else github.review(1, body, state=kind)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {OBJECTION.format(short=head[:7], head=head)}"
    assert github.merges() == []


def _merge_into(github: FakeGitHub, first: str, second: str, files: dict[str, str] | None = None) -> str:
    """Commit scalenia ``second`` do ``first`` z konfliktami rozwiązanymi na korzyść ``first`` i ``files`` dopisanymi przed commitem."""

    git(github.checkout, "checkout", "--quiet", "--detach", first)
    git(github.checkout, "merge", "--quiet", "--no-ff", "--no-commit", "-X", "ours", second)
    for name, text in (files or {}).items():
        (github.checkout / name).write_text(text, encoding="utf-8")
    made = commit(github.checkout, f"Merge {second[:7]}")
    git(github.checkout, "checkout", "--quiet", "main")
    return made


def _clean_merge(github: FakeGitHub, reviewed: str) -> str:
    return _merge_into(github, reviewed, github.push_main({"kod/nowe.py": "NOWE: int = 1\n"}))


def _two_clean_merges(github: FakeGitHub, reviewed: str) -> str:
    first = _clean_merge(github, reviewed)
    return _merge_into(github, first, github.push_main({"kod/nowe.py": "NOWE: int = 2\n"}))


def _merge_with_own_change(github: FakeGitHub, reviewed: str) -> str:
    return _merge_into(github, reviewed, github.push_main({"kod/nowe.py": "NOWE: int = 1\n"}), {"kod/inne.py": "INNE: int = 3\n"})


def _conflict_resolved_by_hand(github: FakeGitHub, reviewed: str) -> str:
    return _merge_into(github, reviewed, github.push_main({"kod/inne.py": "INNE: int = 9\n"}))


def _merge_of_other_branch(github: FakeGitHub, reviewed: str) -> str:
    return _merge_into(github, reviewed, github.commit_on(github.start, {"kod/obok.py": "OBOK: int = 1\n"}, "gałąź obok"))


def _rebase_on_main(github: FakeGitHub, reviewed: str) -> str:
    return github.commit_on(github.push_main({"kod/nowe.py": "NOWE: int = 1\n"}), {"kod/inne.py": "INNE: int = 1\n"}, "PR 1 po rebase")


def _content_change(github: FakeGitHub, reviewed: str) -> str:
    return github.commit_on(reviewed, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")


@pytest.mark.parametrize(
    ("make_head", "valid"),
    [
        (_clean_merge, True),
        (_two_clean_merges, True),
        (_merge_with_own_change, False),
        (_conflict_resolved_by_hand, False),
        (_merge_of_other_branch, False),
        (_rebase_on_main, False),
        (_content_change, False),
    ],
    ids=["czyste-scalenie-main", "dwa-czyste-scalenia-main", "scalenie-z-wlasna-zmiana", "konflikt-rozwiazany-recznie", "scalenie-innej-galezi", "rebase-na-main", "zmiana-tresci"],
)
def test_werdykt_przechodzi_na_head_tylko_po_samych_czystych_scaleniach_main(
    tmp_path: Path, make_head: Callable[[FakeGitHub, str], str], valid: bool
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    reviewed = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, f"WERDYKT: PASS {reviewed}")
    head = make_head(github, reviewed)
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)

    answered = github.run("1", "--bez-merge")

    expected = f"SCAL OK | #1 {head[:7]} | gotowy do merge'a z main" if valid else f"SCAL ODMOWA | #1 {head[:7]} | {NO_PASS.format(head=head)}"
    assert _last_line(answered).startswith(expected), answered.stdout + answered.stderr


@pytest.mark.parametrize("fail_on", ["head", "reviewed"], ids=["fail-dla-scalenia-po-pass-recenzowanego", "fail-recenzowanego-po-pass-scalenia"])
def test_najnowszy_werdykt_rozstrzyga_takze_miedzy_recenzowanym_commitem_a_jego_czystym_scaleniem(tmp_path: Path, fail_on: str) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    reviewed = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = _clean_merge(github, reviewed)
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)
    github.comment(1, f"WERDYKT: PASS {head if fail_on == 'reviewed' else reviewed}")
    github.comment(1, f"WERDYKT: FAIL {reviewed if fail_on == 'reviewed' else head}")

    answered = github.run("1", "--bez-merge")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {OBJECTION.format(short=head[:7], head=head)}"


@pytest.mark.parametrize(
    "verdicts",
    [
        [("comment", "WERDYKT: PASS {head}"), ("comment", "WERDYKT: FAIL {old}")],
        [("comment", "WERDYKT: FAIL {head}"), ("comment", "WERDYKT: PASS {head}")],
        [("COMMENTED", "WERDYKT: FAIL {head}"), ("comment", "WERDYKT: PASS {head}")],
        [("comment", "WERDYKT: FAIL {head}"), ("COMMENTED", "WERDYKT: PASS {head}")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "WERDYKT: FAIL {head}", "CONTRIBUTOR")],
        [("comment", "WERDYKT: PASS {head}"), ("COMMENTED", "")],
        [("comment", "WERDYKT: PASS {head}\r\n\r\n- drobne: nazwa")],
        [("comment", "  WERDYKT: PASS {head}  ")],
        [("CHANGES_REQUESTED", "Popraw nazwę funkcji."), ("comment", "WERDYKT: PASS {head}")],
        [("comment", "WERDYKT: PASS {head}"), ("CHANGES_REQUESTED", "Popraw nazwę funkcji.", "CONTRIBUTOR")],
        [("comment", "WERDYKT: PASS {head}"), ("PENDING", "WERDYKT: FAIL {head}")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "WERDYKT: FAIL {head7}")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "WERDYKT: FAIL {head} — brak testu")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "Werdykt: FAIL {head}")],
        [("comment", "WERDYKT: PASS {head}"), ("comment", "## Przegląd\n\nWERDYKT: FAIL {head}")],
    ],
    ids=[
        "fail-dla-starszego-commitu",
        "pass-po-fail",
        "pass-po-starszej-recenzji-z-fail",
        "pass-w-recenzji-po-fail",
        "fail-kontrybutora",
        "recenzja-bez-tresci",
        "pass-z-crlf",
        "pass-z-odstepami",
        "pass-po-prosbie-o-zmiany",
        "prosba-o-zmiany-kontrybutora",
        "nieopublikowana-recenzja-z-fail",
        "fail-ze-skroconym-sha-to-nie-werdykt",
        "fail-z-dopiskiem-to-nie-werdykt",
        "fail-z-malymi-literami-to-nie-werdykt",
        "fail-nie-w-pierwszej-linii-to-nie-werdykt",
    ],
)
def test_sprzeciw_dla_innego_commitu_starszy_niz_pass_bez_prawa_zapisu_albo_poza_kontraktem_nie_blokuje(
    tmp_path: Path, verdicts: list[tuple[str, ...]]
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)
    for kind, body, *association in verdicts:
        text = body.format(head=head, head7=head[:7], old=old)
        github.comment(1, text, *association) if kind == "comment" else github.review(1, text, *association, state=kind)

    answered = github.run("1", "--bez-merge")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a")


@pytest.mark.parametrize(
    ("state", "draft", "fork", "reason"),
    [
        ("MERGED", False, False, "PR nie jest otwarty: MERGED"),
        ("OPEN", True, False, "PR jest szkicem"),
        ("OPEN", False, True, "PR z forka"),
    ],
)
def test_pr_zamkniety_szkic_albo_z_forka_nie_jest_scalany(
    tmp_path: Path, state: str, draft: bool, fork: bool, reason: str
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, state=state, isDraft=draft, isCrossRepository=fork)
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1")

    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason}"
    assert github.merges() == []


ALL_SECTIONS = "„## Why”, „## Summary”, „## Evidence”, „## Merge Danger”"


@pytest.mark.parametrize(
    ("body", "missing"),
    [
        ("", ALL_SECTIONS),
        ("## Why\n\nCel.\n\n## Co\n\n- zmiana\n", "„## Summary”, „## Evidence”, „## Merge Danger”"),
        (
            "## Why\n\n## What changed\n\n## Scope\n\n## Tradeoffs\n\n## Blast Radius\n\n## Verification\n",
            "„## Summary”, „## Evidence”, „## Merge Danger”",
        ),
        (BODY.replace("## Why", "## Dlaczego"), "„## Why”"),
        ("## Summary\n\n" + BODY.replace("## Summary\n\n", ""), "„## Summary”"),
        (BODY.replace("## Evidence", "### Evidence"), "„## Evidence”"),
        (BODY.replace("## Evidence", "Dowody są w sekcji ## Evidence"), "„## Evidence”"),
        ("\r\n".join(f"  {line}  " for line in BODY.splitlines()), ""),
    ],
    ids=["pusty", "wlasne-sekcje", "sekcje-innego-wzoru", "przetlumaczony-naglowek", "zla-kolejnosc", "naglowek-3-stopnia", "naglowek-w-zdaniu", "odstepy-i-crlf"],
)
def test_pr_bez_naglowka_wzoru_skilla_pr_w_jego_kolejnosci_nie_jest_scalany(tmp_path: Path, body: str, missing: str) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body=body)
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1", "--bez-merge")

    if missing:
        assert answered.returncode == 1, answered.stdout + answered.stderr
        assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | opis: brak {missing} w kolejności wzoru .agents/skills/pr/SKILL.md"
    else:
        assert answered.returncode == 0, answered.stdout + answered.stderr


def test_brak_naglowka_wzoru_jest_w_jednej_odmowie_z_czerwonym_ci_i_brakiem_werdyktu(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body="", statusCheckRollup=[_check_run("COMPLETED", "FAILURE")])

    answered = github.run("1", "--bez-merge")

    assert _last_line(answered) == (
        f"SCAL ODMOWA | #1 {head[:7]} | CI: „Required CI status” FAILURE; "
        f"opis: brak {ALL_SECTIONS} w kolejności wzoru .agents/skills/pr/SKILL.md; {NO_PASS.format(head=head)}"
    )


def test_naglowek_dopisany_do_wzoru_skilla_pr_od_razu_obowiazuje(tmp_path: Path) -> None:
    template = TEMPLATE.read_text(encoding="utf-8").replace("## Merge Danger\n", "## Merge Danger\n\n## Rollback\n", 1)
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, ".agents/skills/pr/SKILL.md": template})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, f"WERDYKT: PASS {head}")

    refused = github.run("1", "--bez-merge")
    github.update(1, body=f"{BODY}\n## Rollback\n\nRevert.\n")
    accepted = github.run("1", "--bez-merge")

    assert _last_line(refused) == f"SCAL ODMOWA | #1 {head[:7]} | opis: brak „## Rollback” w kolejności wzoru .agents/skills/pr/SKILL.md"
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


@pytest.mark.parametrize(
    ("main_files", "pull_files", "reason"),
    [
        ({"kod/nazwa.py": 'NAZWA = "z main"\n'}, {"kod/nazwa.py": 'NAZWA = "z PR"\n'}, "Konflikt z main {main}: kod/nazwa.py"),
        (
            {"pyproject.toml": PYPROJECT.replace("[tool.mypy]", '[tool.ruff.lint]\nextend-select = ["B905"]\n\n[tool.mypy]')},
            {"kod/pary.py": "PARY = list(zip([1], [2]))\n"},
            "Na scaleniu z main {main} pada: ruff",
        ),
    ],
    ids=["konflikt", "regula-ruff-wlaczona-na-main-po-ci-pr"],
)
def test_pr_ktory_nie_scala_sie_czysto_z_biezacym_main_nie_jest_scalany(
    tmp_path: Path, main_files: dict[str, str], pull_files: dict[str, str], reason: str
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "kod/nazwa.py": 'NAZWA = "pierwsza"\n'})
    head = github.open_pull(1, pull_files)
    github.comment(1, f"WERDYKT: PASS {head}")
    main = github.push_main(main_files)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason.format(main=main[:7])}"
    assert github.merges() == []


def test_main_przesuniety_w_trakcie_sprawdzania_zatrzymuje_merge(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    moved = github.commit_on(github.start, {"kod/nowe.py": "NOWE: int = 1\n"}, "main w trakcie")
    pushes_main = (
        "import subprocess\n\n"
        f"subprocess.run(['git', '-C', {str(github.checkout)!r}, 'push', '--quiet', 'origin', '{moved}:refs/heads/main'], check=True)\n"
        "print('CI LOKALNIE OK')\n"
    )
    head = github.open_pull(1, {"tools/ci_lokalnie.py": pushes_main})
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | main zmienił się w trakcie sprawdzania, uruchom ponownie"
    assert github.merges() == []


def test_baza_przesunieta_z_innego_klonu_przed_sprawdzeniem_jest_baza_scalenia(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, f"WERDYKT: PASS {head}")
    other = tmp_path / "inny-klon"
    git(tmp_path, "clone", "--quiet", str(tmp_path / "origin.git"), str(other))
    (other / "kod" / "nowe.py").write_text("NOWE: int = 1\n", encoding="utf-8")
    moved = commit(other, "main z innego klonu")
    git(other, "push", "--quiet", "origin", "HEAD:main")

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert f"| scalony do main jako {git(github.origin, 'rev-parse', 'refs/heads/main')[:7]} (baza {moved[:7]}) |" in _last_line(answered)
    assert len(github.merges()) == 1


def test_baza_z_kolejka_scalen_dostaje_gotowy_pr_w_kolejce_z_jego_head_a_po_scaleniu_przez_nia_biegnie_sprzatanie(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": CLEANUP})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.queue(1, "scala")
    github.comment(1, f"WERDYKT: PASS {head}")

    checked = github.run("1", "--bez-merge")
    enqueued_before_merge = github.enqueues()
    merged = github.run("1", "--czekaj", "5")

    assert _last_line(checked).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a z main {github.start[:7]}")
    assert enqueued_before_merge == []
    assert github.queue_queries() == 3, "po scaleniu przez kolejkę narzędzie przestaje o nią pytać"
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert _last_line(merged) == (
        f"SCAL OK | #1 {head[:7]} | scalony do main przez kolejkę jako {merge_commit[:7]} (baza {github.start[:7]})"
        " | sprzątanie: SPRZĄTANIE OK | 0 usuniętych"
    )
    assert github.enqueues() == [head]
    assert github.merges() == []


def test_kolejka_scalen_nie_odmawia_przy_bazie_przesunietej_w_trakcie_sprawdzania_bo_sama_sprawdza_scalenie(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    moved = github.commit_on(github.start, {"kod/nowe.py": "NOWE: int = 1\n"}, "main w trakcie")
    pushes_main = (
        "import subprocess\n\n"
        f"subprocess.run(['git', '-C', {str(github.checkout)!r}, 'push', '--quiet', 'origin', '{moved}:refs/heads/main'], check=True)\n"
        "print('CI LOKALNIE OK')\n"
    )
    head = github.open_pull(1, {"tools/ci_lokalnie.py": pushes_main})
    github.queue(1, "scala")
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert github.enqueues() == [head]


def test_pr_usuniety_z_kolejki_scalen_jest_odmowa_z_powodem_od_githuba(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.queue(1, "usuwa")
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1", "--czekaj", "5")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | kolejka scaleń usunęła PR: Required status check failed"
    assert git(github.origin, "rev-parse", "refs/heads/main") == github.start
    assert github.queue_queries() == 2, "po usunięciu z kolejki narzędzie przestaje o nią pytać"


def test_pr_czekajacy_w_kolejce_po_czasie_zostaje_w_niej_a_ponowne_uruchomienie_konczy_po_scaleniu_bez_sprawdzania_od_nowa(
    tmp_path: Path,
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": CLEANUP})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.queue(1, "czeka")
    github.comment(1, f"WERDYKT: PASS {head}")

    waiting = github.run("1", "--czekaj", "0")
    checked_in_queue = github.run("1", "--bez-merge", "--czekaj", "0")
    pulls = json.loads((github.bin / "pulls.json").read_text(encoding="utf-8"))
    pulls["1"].update(comments=[], statusCheckRollup=[_check_run("COMPLETED", "FAILURE")])
    pulls["1"]["kolejka"]["potem"] = "scala"
    (github.bin / "pulls.json").write_text(json.dumps(pulls), encoding="utf-8")
    finished = github.run("1", "--czekaj", "0")

    assert waiting.returncode == scal_pr.IN_QUEUE, waiting.stdout + waiting.stderr
    assert _last_line(waiting) == (
        f"SCAL KOLEJKA | #1 {head[:7]} | w kolejce do main: AWAITING_CHECKS, pozycja 1 po 0 s czekania, "
        "uruchom ponownie tools/scal_pr.py 1, żeby czekać dalej"
    )
    assert _last_line(checked_in_queue).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a z main")
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert _last_line(finished) == f"SCAL OK | #1 {head[:7]} | scalony do main przez kolejkę jako {merge_commit[:7]} | sprzątanie: SPRZĄTANIE OK | 0 usuniętych"
    assert github.enqueues() == [head]


def test_po_merge_zamyka_otwarte_issues_z_naprawia_z_komentarzem_a_bez_merge_tylko_je_podaje(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": CLEANUP})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_issues(3, 4, 6, 7)
    github.open_issues(5, state="closed")
    seven = {"number": 7, "repository": {"name": "maximiseart-dad", "owner": {"login": "MAXIMISEARTAI"}}}
    four_elsewhere = {"number": 4, "repository": {"name": "repo", "owner": {"login": "inny"}}}
    github.update(1, body=opisy_pr.SCALENIE["zamyka"], closingIssuesReferences=[seven, four_elsewhere])
    github.comment(1, f"WERDYKT: PASS {head}")

    checked = github.run("1", "--bez-merge")
    closed_before_merge = github.closed()
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).endswith("bez merge'a (--bez-merge) | po merge'u zamknie: #3, #4")
    assert closed_before_merge == []
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert _last_line(merged).endswith(f"jako {merge_commit[:7]} (baza {github.start[:7]}) | zamknięte: #3, #4 | sprzątanie: SPRZĄTANIE OK | 0 usuniętych")
    comment = f"Naprawione przez #1, scalone jako {merge_commit}."
    assert github.closed() == [["issue", "close", str(n), "--repo", opisy_pr.REPO, "--comment", comment] for n in (3, 4)]


def test_merge_do_galezi_innej_niz_domyslna_niczego_nie_zamyka_ani_nie_renderuje_opisu(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.repo_view = _repo_view("trunk")
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_issues(3, 4)
    github.update(1, body=opisy_pr.SCALENIE["dwa"])
    github.comment(1, f"WERDYKT: PASS {head}")

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert _last_line(checked).endswith("bez merge'a (--bez-merge) | bez zamykania „Naprawia”: baza main to nie trunk")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert " | bez zamykania „Naprawia”: baza main to nie trunk | " in _last_line(merged)
    assert len(github.merges()) == 1
    assert github.closed() == []
    assert github.renders() == []


@pytest.mark.parametrize("body", [opisy_pr.wzor("Closes #3"), opisy_pr.wzor("Ten PR\nnaprawia #3")], ids=["closes", "naprawia-mala-litera"])
def test_pr_bez_slowa_naprawia_nie_pyta_o_domyslna_galaz_ani_nie_renderuje_opisu(tmp_path: Path, body: str) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.repo_view = _repo_view("trunk")
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body=body)
    github.comment(1, f"WERDYKT: PASS {head}")

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert _last_line(checked).endswith("bez merge'a (--bez-merge)")
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert f"jako {merge_commit[:7]} (baza {github.start[:7]}) | sprzątanie pominięte" in _last_line(merged)
    assert github.repo_views() == []
    assert github.renders() == []


@pytest.mark.parametrize("answer", ["gh: HTTP 502", "", "{}"], ids=["blad-http", "pusta-odpowiedz", "bez-defaultBranchRef"])
def test_bez_domyslnej_galezi_od_githuba_merge_sie_odbywa_a_issues_zostaja_otwarte_z_ostrzezeniem(
    tmp_path: Path, answer: str
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.repo_view = answer
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_issues(3)
    github.update(1, body=opisy_pr.SCALENIE["jedno"])
    github.comment(1, f"WERDYKT: PASS {head}")

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).endswith("(--bez-merge) | UWAGA: GitHub nie podał domyślnej gałęzi, nie sprawdzono „Naprawia”")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    warning = "UWAGA: GitHub nie podał domyślnej gałęzi, nie zamknięto issues z „Naprawia”, zamknij je ręcznie"
    assert f" | {warning} | " in _last_line(merged)
    assert "Traceback" not in merged.stderr
    assert len(github.merges()) == 1
    assert github.closed() == []


@pytest.mark.parametrize("answer", ["gh: HTTP 502", "\n", "zawiesza"], ids=["blad-http", "pusta-odpowiedz", "gh-po-czasie"])
def test_bez_html_opisu_od_githuba_merge_sie_odbywa_a_issues_zostaja_otwarte_z_ostrzezeniem(tmp_path: Path, answer: str) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"}, parent=_short_github_timeout(github))
    github.open_issues(3)
    github.markdown[opisy_pr.SCALENIE["jedno"]] = answer
    github.update(1, body=opisy_pr.SCALENIE["jedno"])
    github.comment(1, f"WERDYKT: PASS {head}")

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).endswith("(--bez-merge) | UWAGA: GitHub nie wyrenderował opisu PR, nie sprawdzono „Naprawia”")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    warning = "UWAGA: GitHub nie wyrenderował opisu PR, nie zamknięto issues z „Naprawia”, zamknij je ręcznie"
    assert f" | {warning} | " in _last_line(merged)
    assert "Traceback" not in merged.stderr
    assert len(github.merges()) == 1
    assert github.closed() == []


def test_porazka_zamykania_issue_nie_odwoluje_scalenia(tmp_path: Path) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"}, parent=_short_github_timeout(github))
    github.open_issues(3)
    github.answer_issue(10, answer="")
    github.answer_issue(11, answer="{}")
    github.answer_issue(12, answer="[]")
    github.answer_issue(13, answer="zawiesza")
    github.update(1, body=opisy_pr.SCALENIE["porazki"])
    github.comment(1, f"WERDYKT: PASS {head}")

    checked = github.run("1", "--bez-merge")
    answered = github.run("1")

    failed = "#14, #10, #11, #12, #13"
    assert _last_line(checked).endswith(f" | po merge'u zamknie: #3 | UWAGA: nie sprawdzono {failed}")
    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert f" | zamknięte: #3 | UWAGA: nie zamknięto {failed}, zamknij ręcznie | " in _last_line(answered)
    assert len(github.merges()) == 1


@pytest.mark.parametrize("after_merge", ["brak", "błąd"], ids=["github-bez-commitu-merge", "gh-pr-view-z-bledem"])
def test_bez_commitu_merge_od_githuba_issues_zostaja_otwarte_z_ostrzezeniem(tmp_path: Path, after_merge: str) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_issues(3)
    github.open_issues(5, state="closed")
    github.update(1, body=opisy_pr.SCALENIE["bez-commitu-merge"], poMergeu=after_merge)
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    warning = "UWAGA: GitHub nie podał commitu merge'a, nie zamknięto #3, #15, zamknij ręcznie"
    assert f"| scalony do main jako ? (baza {github.start[:7]}) | {warning} | " in _last_line(answered)
    assert len(github.merges()) == 1
    assert github.closed() == []


@pytest.mark.parametrize(("body", "fixes"), [case[1:] for case in opisy_pr.PRZYPADKI], ids=[case[0] for case in opisy_pr.PRZYPADKI])
def test_naprawia_wskazuje_issues_tego_repo_tylko_na_poczatku_linii_tekstu_ktory_github_pokazuje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, fixes: tuple[int, ...]
) -> None:
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    assert scal_pr.fixed_issues(body, opisy_pr.REPO) == fixes


def test_naprawia_wskazuje_issues_tego_repo_bez_wzgledu_na_wielkosc_liter_jego_nazwy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    assert scal_pr.fixed_issues(opisy_pr.SCALENIE["dwa"], opisy_pr.REPO.swapcase()) == (3, 4)


@pytest.mark.parametrize(("number", "fixes"), opisy_pr.PRAWDZIWE.items(), ids=[f"pr-{number}" for number in opisy_pr.PRAWDZIWE])
def test_opisy_scalonych_pr_wskazuja_issues_ktore_github_zostawil_otwarte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, number: int, fixes: tuple[int, ...]
) -> None:
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    assert scal_pr.fixed_issues(opisy_pr.real_body(number), opisy_pr.REPO) == fixes


def test_kazdy_opis_testow_ma_html_z_renderera_githuba() -> None:
    assert sorted(opisy_pr.rendered()) == sorted(set(opisy_pr.bodies())), "odśwież: .venv/bin/python tests/fixtures/opisy_pr.py"


def test_sprzatanie_po_czasie_nie_odwoluje_scalenia(tmp_path: Path) -> None:
    hangs = "import time\n\ntime.sleep(600)\n"
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": hangs})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    tool = github.checkout / "tools" / "scal_pr.py"
    tool.write_text(tool.read_text(encoding="utf-8").replace("CLEANUP_TIMEOUT_S = 300", "CLEANUP_TIMEOUT_S = 1"), encoding="utf-8")
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).endswith("| UWAGA: sprzątanie przerwane po 1 s, uruchom je ponownie")
    assert len(github.merges()) == 1



@pytest.mark.parametrize(
    "mutations",
    [
        [],
        [_check_run("IN_PROGRESS", None, name="Change mutations (1/3)")],
        [_check_run("COMPLETED", "FAILURE", name="Change mutations (1/3)")],
    ],
    ids=["bez-checku", "w-toku", "przezyte"],
)
def test_gotowy_pr_nie_czeka_na_mutacje_zmiany_ani_linie_mutacja_bo_mutacje_biegna_noca_na_main(
    tmp_path: Path, mutations: list[dict[str, str | None]]
) -> None:
    github = FakeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, statusCheckRollup=[*GREEN, *mutations])
    github.comment(1, f"WERDYKT: PASS {head}")

    answered = github.run("1", "--bez-merge")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a")
