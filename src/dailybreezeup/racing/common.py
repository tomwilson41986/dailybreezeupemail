import requests
from tenacity import retry, stop_after_attempt, wait_exponential

USER_AGENT = "dailybreezeup/0.1 (+https://github.com/tomwilson41986/dailybreezeupemail)"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/html"})
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def get_json(session: requests.Session, url: str, **kwargs: object) -> dict:
    r = session.get(url, timeout=30, **kwargs)
    r.raise_for_status()
    return r.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def get_text(session: requests.Session, url: str, **kwargs: object) -> str:
    r = session.get(url, timeout=30, **kwargs)
    r.raise_for_status()
    return r.text
