"""Unit tests for the runtime settings store (encryption, key resolution, toggles)."""
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from src import settings_store


@pytest.fixture
def store_engine(monkeypatch):
    import src.database as _db

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(_db, "engine", eng)
    return eng


# ── LLM keys ──────────────────────────────────────────────────────────────────

def test_llm_key_roundtrip(store_engine):
    settings_store.set_llm_key("openai", "sk-secret-value-1234")
    assert settings_store.get_llm_key("openai", "OPENAI_API_KEY") == "sk-secret-value-1234"


def test_llm_key_encrypted_at_rest(store_engine):
    settings_store.set_llm_key("openai", "sk-secret-value-1234")
    stored = settings_store.get_setting("llm_key:openai")
    assert stored is not None
    assert "sk-secret-value-1234" not in stored  # ciphertext, not plaintext


def test_db_key_overrides_env(store_engine, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    settings_store.set_llm_key("openai", "db-key")
    assert settings_store.get_llm_key("openai", "OPENAI_API_KEY") == "db-key"


def test_env_fallback_when_no_db_key(store_engine, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert settings_store.get_llm_key("openai", "OPENAI_API_KEY") == "env-key"


def test_clear_reverts_to_env(store_engine, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    settings_store.set_llm_key("openai", "db-key")
    settings_store.clear_llm_key("openai")
    assert settings_store.get_llm_key("openai", "OPENAI_API_KEY") == "env-key"


def test_key_status_masks(store_engine):
    settings_store.set_llm_key("openai", "sk-abcdefghijklmnop")
    status = settings_store.llm_key_status("openai", "OPENAI_API_KEY")
    assert status["configured"] is True
    assert status["source"] == "db"
    assert "sk-abcdefghijklmnop" not in status["masked"]
    assert "…" in status["masked"]


# ── Enabled automations ───────────────────────────────────────────────────────

def test_enabled_defaults_to_all(store_engine):
    assert settings_store.get_enabled_automations() == settings_store.ALL_AUTOMATIONS


def test_set_enabled_filters_unknown(store_engine):
    settings_store.set_enabled_automations(["web_scraper", "bogus_type"])
    assert settings_store.get_enabled_automations() == ["web_scraper"]


def test_is_automation_enabled(store_engine):
    settings_store.set_enabled_automations(["web_scraper"])
    assert settings_store.is_automation_enabled("web_scraper")
    assert not settings_store.is_automation_enabled("email_sender")


# ── Evaluation judge ──────────────────────────────────────────────────────────

def test_eval_judge_defaults_unset(store_engine):
    assert settings_store.get_eval_judge() == (None, None)


def test_set_and_get_eval_judge(store_engine):
    settings_store.set_eval_judge("gemini", "gemini/gemini-2.5-flash")
    assert settings_store.get_eval_judge() == ("gemini", "gemini/gemini-2.5-flash")


def test_set_eval_judge_provider_only(store_engine):
    settings_store.set_eval_judge("gemini", None)
    assert settings_store.get_eval_judge() == ("gemini", None)


def test_clear_eval_judge_reverts_to_unset(store_engine):
    settings_store.set_eval_judge("gemini", "gemini/gemini-2.5-flash")
    settings_store.set_eval_judge(None, None)  # falsy provider clears
    assert settings_store.get_eval_judge() == (None, None)
