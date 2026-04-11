"""Multi-modal data ingestion pipelines for Jenkins, GitHub, Jira, Slack."""

from tracebow.ingestion.base import BaseIngester
from tracebow.ingestion.github import GitHubIngester
from tracebow.ingestion.jenkins import JenkinsIngester
from tracebow.ingestion.jira import JiraIngester
from tracebow.ingestion.slack import SlackIngester

__all__ = [
    "BaseIngester",
    "GitHubIngester",
    "JenkinsIngester",
    "JiraIngester",
    "SlackIngester",
]
