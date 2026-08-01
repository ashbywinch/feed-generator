"""Discovery: Exa search + registry pollers, per-topic attribution, caps."""

import requests

from signalflow.config import Config
from signalflow.discovery import Discovery


def _resp(status: int, body):
    class R:
        status_code = status

        def raise_for_status(self) -> None:
            if status >= 400:
                raise requests.HTTPError(f"HTTP {status}")

        def json(self):
            return body

    return R()


def _cfg(cfg, **over):
    return Config(
        llm_key=cfg.llm_key,
        llm_base=cfg.llm_base,
        llm_model=cfg.llm_model,
        embed_model=cfg.embed_model,
        google_key=cfg.google_key,
        exa_key=cfg.exa_key,
        **over,
    )


def test_exa_and_registries_per_topic_strategy(cfg, monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _resp(200, {"results": [{"title": "S1", "url": "https://exa.example/1", "text": "body text"}]})

    def fake_get(url, headers=None, params=None, timeout=None):
        if "gtr.ukri" in url:
            ukri_body = {
                "projectOverview": {
                    "project": [
                        {
                            "title": "Proj",
                            "grantReference": "G1",
                            "status": "Active",
                            "grantCategory": "RC",
                            "fund": {"valuePounds": 99},
                        }
                    ]
                }
            }
            return _resp(200, ukri_body)
        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT1", "briefTitle": "Trial"},
                "statusModule": {"overallStatus": "RECRUITING"},
                "conditionsModule": {"conditions": ["c"]},
            }
        }
        return _resp(200, {"studies": [study]})

    monkeypatch.setattr("signalflow.discovery.requests.post", fake_post)
    monkeypatch.setattr("signalflow.discovery.requests.get", fake_get)

    topics = [
        {"name": "Energy", "strategy": {"queries": ["grid storage"], "registries": ["UKRI GtR", "ClinicalTrials.gov"]}}
    ]
    cands = Discovery(cfg).discover(topics)
    assert {c.source_tier for c in cands} == {"search", "registry"}
    assert all(c.topic == "Energy" for c in cands)
    assert any("gtr.ukri.org" in c.url for c in cands)
    assert any("clinicaltrials.gov" in c.url for c in cands)


def test_registry_only_when_strategy_says_so(cfg, monkeypatch):
    calls = {"post": 0, "get": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["post"] += 1
        return _resp(200, {"results": []})

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["get"] += 1
        return _resp(200, {"studies": []})

    monkeypatch.setattr("signalflow.discovery.requests.post", fake_post)
    monkeypatch.setattr("signalflow.discovery.requests.get", fake_get)

    topics = [{"name": "T", "strategy": {"queries": ["q1"], "registries": []}}]  # no registries relevant
    Discovery(cfg).discover(topics)
    assert calls["post"] == 1  # search only
    assert calls["get"] == 0  # no registry polling


def test_per_topic_cap_and_url_dedupe(cfg, monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        results = [{"title": f"S{i}", "url": f"https://exa.example/{i}", "text": "b"} for i in range(10)]
        return _resp(200, {"results": results * 2})  # duplicated results

    def fake_get(url, headers=None, params=None, timeout=None):
        return _resp(200, {"studies": []})

    monkeypatch.setattr("signalflow.discovery.requests.post", fake_post)
    monkeypatch.setattr("signalflow.discovery.requests.get", fake_get)

    topics = [{"name": "T", "strategy": {"queries": ["q1"], "registries": []}}]
    cands = Discovery(_cfg(cfg, max_candidates_per_topic=5)).discover(topics)
    urls = [c.url for c in cands]
    assert len(cands) == 5
    assert len(set(urls)) == len(urls)
