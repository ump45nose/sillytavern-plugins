"""Read-only GitHub projection: GET REST and fixed GraphQL queries only."""
import asyncio
import json
import re
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit

from .base import Adapter
from .personal import local_time

COMMON = "id number title url state updatedAt author { login } repository { nameWithOwner } comments(last:1) { nodes { author { login } bodyText createdAt } }"
PR_DETAIL = "reviewRequests(first:100) { nodes { requestedReviewer { ... on User { login } ... on Team { slug } } } } reviews(last:1) { nodes { author { login } bodyText submittedAt comments(last:1) { nodes { author { login } bodyText createdAt } } } }"
DETAIL = "... on Issue {" + COMMON + "} ... on PullRequest {" + COMMON + PR_DETAIL + "}"
OVERVIEW = '''query HubOverview($day:DateTime!, $month:DateTime!, $year:DateTime!, $now:DateTime!) {
 viewer {
  login
  today:contributionsCollection(from:$day,to:$now) { totalCommitContributions }
  month:contributionsCollection(from:$month,to:$now) { totalCommitContributions totalRepositoriesWithContributedCommits }
  year:contributionsCollection(from:$year,to:$now) {
   totalRepositoriesWithContributedCommits
   commitContributionsByRepository(maxRepositories:25) {
    contributions(first:40,orderBy:{field:OCCURRED_AT,direction:DESC}) {
     pageInfo { hasNextPage } nodes { occurredAt commitCount }
    }
   }
  }
  pullRequests(first:20,states:OPEN,orderBy:{field:UPDATED_AT,direction:DESC}) {
   pageInfo { hasNextPage }
   nodes {
    id number title url createdAt updatedAt isDraft mergeable reviewDecision repository { nameWithOwner }
    latestReviews(first:20) { nodes { state submittedAt } }
    reviews(first:1) { totalCount }
    commits(last:1) { nodes { commit { statusCheckRollup {
     state contexts(first:20) { nodes {
      ... on CheckRun { name conclusion completedAt }
      ... on StatusContext { context state createdAt }
     } }
    } } } }
   }
  }
 }
}'''
# Separate expensive connections so GitHub can execute them within the source deadline.
TOTALS = "query HubOverviewTotals($day:DateTime!,$month:DateTime!,$now:DateTime!){viewer{login today:contributionsCollection(from:$day,to:$now){totalCommitContributions} month:contributionsCollection(from:$month,to:$now){totalCommitContributions totalRepositoriesWithContributedCommits}}}"
YEAR = "query HubOverviewYear($year:DateTime!,$now:DateTime!){viewer{" + OVERVIEW[OVERVIEW.index("  year:"):OVERVIEW.index("  pullRequests(")] + "}}"
PRS = "query HubOverviewPRs {viewer{" + OVERVIEW[OVERVIEW.index("  pullRequests("):OVERVIEW.rindex("\n }")] + "}}"



class GitHub:
    def __init__(self, client, settings, now):
        self.client, self.settings, self.now = client, settings, now

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.settings.github_token.get_secret_value(),
                "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "personal-hub"}

    async def get(self, path, params=None):
        response = await self.client.get("https://api.github.com" + path, params=params, headers=self.headers)
        response.raise_for_status()
        return response

    async def query(self, query, variables=None):
        # Query text is built here, never supplied by a client or source response.
        assert query.lstrip().startswith("query ")
        response = await self.client.post("https://api.github.com/graphql", headers=self.headers,
                                          json={"query": query, "variables": variables or {}})
        response.raise_for_status()
        data = response.json()
        if data.get("errors") or not isinstance(data.get("data"), dict):
            raise ValueError("GitHub query failed")
        return data["data"]

    def timestamp(self, value):
        return local_time(value, self.now().tzinfo)

    @staticmethod
    def latest(item):
        comments = list(item.get("comments", {}).get("nodes", []))
        for review in item.get("reviews", {}).get("nodes", []):
            comments.append({"author": review.get("author"), "bodyText": review.get("bodyText"), "createdAt": review.get("submittedAt")})
            comments.extend(review.get("comments", {}).get("nodes", []))
        comments = [c for c in comments if c.get("createdAt")]
        return max(comments, key=lambda c: c["createdAt"]) if comments else None

    def waiting_row(self, item, kind, login, since=None):
        if item.get("state") != "OPEN":
            return None
        comment = self.latest(item)
        author = ((comment or {}).get("author") or {}).get("login")
        if kind != "review" and (not comment or (author or "").casefold() == login.casefold()):
            return None
        if kind == "review":
            reviewers = [r.get("requestedReviewer") or {} for r in item.get("reviewRequests", {}).get("nodes", [])]
            if not any(r.get("login", "").casefold() == login.casefold() or r.get("slug") for r in reviewers):
                return None
        return {"id": "git-waiting:" + item["id"] + ":" + kind, "kind": kind,
                "repo": item["repository"]["nameWithOwner"], "number": item["number"], "title": item["title"],
                "who": author or (item.get("author") or {}).get("login"),
                "since": self.timestamp(since or (comment or {}).get("createdAt") or item["updatedAt"]),
                "quote": ((comment or {}).get("bodyText") or "")[:140], "url": item["url"]}

    async def notifications(self):
        return await self.get("/notifications", {"participating": "true", "all": "false", "per_page": 50})

    async def classic_waiting(self, response, login):
        selected, blocks = [], []
        reasons = {"mention": "mention", "team_mention": "mention", "review_requested": "review", "comment": "reply", "author": "reply"}
        for row in response.json():
            if row.get("reason") not in reasons or row.get("subject", {}).get("type") not in ("Issue", "PullRequest"):
                continue
            parsed = urlsplit(row["subject"].get("url") or "")
            match = re.fullmatch(r"/repos/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(?:issues|pulls)/(\d+)", parsed.path)
            if parsed.scheme != "https" or parsed.netloc != "api.github.com" or not match:
                continue
            owner, repo, number = match.groups()
            key = "n" + str(len(selected))
            selected.append((key, reasons[row["reason"]], row["updated_at"]))
            blocks.append(key + ":repository(owner:" + json.dumps(owner) + ",name:" + json.dumps(repo) + "){issueOrPullRequest(number:" + number + "){ ... on Issue {" + DETAIL + "} ... on PullRequest {" + DETAIL + "} }}")
        if not blocks:
            return [], bool(response.links.get("next"))
        data = await self.query("query HubWaiting {" + " ".join(blocks) + "}")
        rows = []
        for key, kind, since in selected:
            item = (data.get(key) or {}).get("issueOrPullRequest")
            if item:
                row = self.waiting_row(item, kind, login, since)
                if row: rows.append(row)
        return rows, bool(response.links.get("next"))

    async def search_waiting(self, login):
        rows, partial = [], False
        # Fine-grained credentials do not support notifications. Explicit approximation.
        kinds = [("review", "review-requested:"), ("mention", "mentions:"), ("reply", "involves:")]
        query = "query HubSearch($q:String!) { search(query:$q,type:ISSUE,first:100) { pageInfo {hasNextPage} nodes { " + DETAIL + " } } }"
        searches = await asyncio.gather(*(self.query(query, {"q": "is:open " + term + login}) for _, term in kinds))
        for (kind, _), result in zip(kinds, searches):
            data = result["search"]
            partial |= data["pageInfo"]["hasNextPage"]
            for item in data["nodes"]:
                row = self.waiting_row(item, kind, login)
                if row and not any(r["id"].split(":")[:2] == row["id"].split(":")[:2] for r in rows): rows.append(row)
        return rows, partial

    def activity(self, viewer):
        today = self.now().date()
        active, coverage_start = set(), today - timedelta(days=364)
        year = viewer["year"]
        for repo in year["commitContributionsByRepository"]:
            connection = repo["contributions"]
            for row in connection["nodes"]:
                if row["commitCount"] > 0:
                    day = datetime.fromisoformat(row["occurredAt"].replace("Z", "+00:00")).astimezone(self.now().tzinfo).date()
                    active.add(day)
            if connection["pageInfo"]["hasNextPage"] and connection["nodes"]:
                # Older hidden contributions cannot affect a streak whose gap is newer.
                last = datetime.fromisoformat(connection["nodes"][-1]["occurredAt"].replace("Z", "+00:00")).astimezone(self.now().tzinfo).date()
                coverage_start = max(coverage_start, last)
        cursor = today if today in active else today - timedelta(days=1)
        streak = 0
        while cursor >= coverage_start and cursor in active:
            streak += 1
            cursor -= timedelta(days=1)
        if cursor < coverage_start or year["totalRepositoriesWithContributedCommits"] > 25:
            streak = None
        return {"commits_today": viewer["today"]["totalCommitContributions"],
                "commits_30d": viewer["month"]["totalCommitContributions"],
                "repos_30d": viewer["month"]["totalRepositoriesWithContributedCommits"], "streak_days": streak}

    def blocked(self, viewer):
        result = []
        for pr in viewer["pullRequests"]["nodes"]:
            reasons = []
            commit = pr["commits"]["nodes"]
            checks = ((commit[-1].get("commit") or {}).get("statusCheckRollup") or {}) if commit else {}
            if checks.get("state") in ("FAILURE", "ERROR"):
                failures = [c for c in checks.get("contexts", {}).get("nodes", []) if c.get("conclusion") in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE") or c.get("state") in ("FAILURE", "ERROR")]
                times = [c.get("completedAt") or c.get("createdAt") for c in failures if c.get("completedAt") or c.get("createdAt")]
                reasons.append(("ci_failed", min(times) if times else None, ", ".join((c.get("name") or c.get("context") or "") for c in failures)))
            if pr.get("reviewDecision") == "CHANGES_REQUESTED":
                times = [r["submittedAt"] for r in pr["latestReviews"]["nodes"] if r["state"] == "CHANGES_REQUESTED" and r.get("submittedAt")]
                reasons.append(("changes_requested", min(times) if times else None, None))
            if pr.get("mergeable") == "CONFLICTING": reasons.append(("conflict", None, None))
            if not pr["isDraft"] and pr["reviews"]["totalCount"] == 0:
                reasons.append(("no_review", pr["createdAt"], None))
            for reason, since, detail in reasons:
                result.append({"id": "pr-blocked:" + pr["id"] + ":" + reason, "repo": pr["repository"]["nameWithOwner"],
                    "number": pr["number"], "title": pr["title"], "reason": reason, "since": self.timestamp(since),
                    "detail": detail, "url": pr["url"]})
        return result

    async def fetch(self):
        now = self.now()
        midnight = datetime.combine(now.date(), time.min, now.tzinfo)
        variables = {"day": midnight.isoformat(), "month": (midnight-timedelta(days=29)).isoformat(),
                     "year": (midnight-timedelta(days=364)).isoformat(), "now": now.isoformat()}
        fine = self.settings.github_token.get_secret_value().startswith("github_pat_")
        async def waiting():
            if fine:
                totals = await self.query(TOTALS, variables)
                rows, partial = await self.search_waiting(totals["viewer"]["login"])
            else:
                totals, notices = await asyncio.gather(self.query(TOTALS, variables), self.notifications())
                rows, partial = await self.classic_waiting(notices, totals["viewer"]["login"])
            return totals["viewer"], rows, partial
        (totals, waiting, partial), year, prs = await asyncio.gather(waiting(), self.query(YEAR, variables), self.query(PRS))
        viewer = {**totals, **year["viewer"], **prs["viewer"]}
        activity = self.activity(viewer)
        return {"waiting": waiting, "blocked": self.blocked(viewer), "activity": activity,
                "_partial": partial or viewer["pullRequests"]["pageInfo"]["hasNextPage"] or activity["streak_days"] is None}

    def adapter(self):
        return Adapter("github", "GitHub", 120, self.fetch if self.settings.github_token else None)
