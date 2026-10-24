import copy
import json

from article_alerts.domain import Article, DeliveryError
from article_alerts.http import Response


def article(number):
    return Article(f"post:{number}", f"新闻 {number}", f"https://www.sinchew.com.my/news/20261024/nation/{number}")


class MemoryStore:
    def __init__(self, state=None):
        self.state = copy.deepcopy(state)
        self.saves = 0

    def load(self):
        return copy.deepcopy(self.state)

    def save(self, state):
        self.state = copy.deepcopy(state)
        self.saves += 1


class FakeSource:
    identity = "source-1"

    def __init__(self, articles=None):
        self.articles = [article(2), article(1)] if articles is None else articles
        self.error = None

    def baseline(self):
        if self.error:
            raise self.error
        return self.articles

    def discover(self, known_ids):
        return self.baseline()


class FakeNotifier:
    def __init__(self, fail_on=None):
        self.messages = []
        self.fail_on = fail_on

    def send(self, message):
        if self.fail_on is not None and len(self.messages) == self.fail_on:
            raise DeliveryError("Synthetic delivery outage.")
        self.messages.append(message)


class ScriptedHttp:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def request(self, method, url, *, headers=None, body=None):
        self.calls.append((method, url, headers, body))
        if not self.results:
            raise AssertionError("Unexpected HTTP call")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def response(value):
    return Response(json.dumps(value).encode())
