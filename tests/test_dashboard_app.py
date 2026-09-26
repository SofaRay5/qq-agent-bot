import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from config.models import (
    Persona,
    PrivateSettings,
    ProviderSettings,
    Settings,
    load_persona,
    load_settings,
)
from config.storage import (
    load_private_settings,
    save_persona,
    save_private_settings,
    save_settings,
)
from dashboard.app import create_app
from dashboard.auth import AuthStore
from dashboard.runtime import BotManager, SafeError


class FakeManager:
    state = "stopped"
    errors: tuple[object, ...] = ()

    def __init__(self) -> None:
        self.updated = 0

    async def start(self, *_args: object) -> None:
        self.state = "starting"

    async def stop(self) -> None:
        self.state = "stopped"

    def update_runtime(self, *_args: object) -> None:
        self.updated += 1


def csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


@pytest.fixture
async def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path, cast(BotManager, FakeManager()))
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as value:
        yield value


async def test_first_run_setup_login_rotation_and_auth_guards(
    client: TestClient,
) -> None:
    response = await client.get("/", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"] == "/setup"

    setup = await client.get("/setup")
    old_cookie = client.session.cookie_jar.filter_cookies(client.make_url("/"))[
        "dashboard_session"
    ].value
    response = await client.post(
        "/setup",
        data={"password": "correct horse battery staple", "csrf_token": csrf(await setup.text())},
        allow_redirects=False,
    )
    assert response.status == 302
    assert response.headers["Location"] == "/"
    setup_cookie = response.headers.getall("Set-Cookie")[0]
    assert "HttpOnly" in setup_cookie
    assert "SameSite=Strict" in setup_cookie
    assert (
        client.session.cookie_jar.filter_cookies(client.make_url("/"))["dashboard_session"].value
        != old_cookie
    )

    response = await client.post("/logout", data={}, allow_redirects=False)
    assert response.status == 403

    status = await client.get("/")
    token = csrf(await status.text())
    response = await client.post("/logout", data={"csrf_token": token}, allow_redirects=False)
    assert response.status == 302

    response = await client.get("/settings", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"] == "/login"

    login = await client.get("/login")
    anonymous_cookie = client.session.cookie_jar.filter_cookies(client.make_url("/"))[
        "dashboard_session"
    ].value
    response = await client.post(
        "/login",
        data={"password": "correct horse battery staple", "csrf_token": csrf(await login.text())},
        allow_redirects=False,
    )
    assert response.status == 302
    assert (
        client.session.cookie_jar.filter_cookies(client.make_url("/"))["dashboard_session"].value
        != anonymous_cookie
    )


async def test_post_requires_csrf_and_request_size_is_limited(client: TestClient) -> None:
    setup = await client.get("/setup")
    token = csrf(await setup.text())

    assert (await client.post("/setup", data={"password": "long-enough-password"})).status == 403
    oversized = "x" * 70_000
    response = await client.post("/setup", data={"password": oversized, "csrf_token": token})
    assert response.status == 413


async def test_reloading_setup_keeps_the_form_csrf_session(client: TestClient) -> None:
    first = await client.get("/setup")
    token = csrf(await first.text())
    await client.get("/setup")

    response = await client.post(
        "/setup",
        data={"password": "correct horse battery staple", "csrf_token": token},
        allow_redirects=False,
    )

    assert response.status == 302
    assert response.headers["Location"] == "/"


def valid_settings() -> Settings:
    return Settings(
        continuous_window_seconds=600,
        window_max_attempts=5,
        window_max_replies=4,
        daily_model_calls=50,
        daily_proactive_calls=5,
        daily_vision_calls=5,
        proactive_mode="both",
        proactive_probability=0.1,
        minimum_reply_interval_seconds=1,
        send_delay_seconds=0.5,
        context_max_messages=20,
        context_max_characters=6000,
    )


def valid_persona() -> Persona:
    return Persona(
        name="<script>小薯</script>",
        description="一个群友",
        personality="认真",
        scenario="QQ群",
        speech_style="简短",
        identity_response="不知道",
        example_dialogues=[],
    )


def valid_private() -> PrivateSettings:
    return PrivateSettings(
        napcat_ws_url="ws://127.0.0.1:3001/",
        napcat_access_token="nap-secret-value",
        chat=ProviderSettings(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            api_key="chat-secret-value",
        ),
        vision_enabled=True,
        vision=ProviderSettings(
            provider="openai_compatible",
            base_url="https://vision.example.com/v1",
            model="vision-model",
            api_key="vision-secret-value",
        ),
    )


@pytest.fixture
async def authenticated(
    tmp_path: Path,
) -> AsyncIterator[tuple[TestClient, FakeManager, Path]]:
    save_settings(tmp_path, valid_settings())
    save_persona(tmp_path, valid_persona())
    save_private_settings(tmp_path, valid_private())
    AuthStore(tmp_path).create_password("correct horse battery staple")
    manager = FakeManager()
    app = create_app(tmp_path, cast(BotManager, manager))
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as value:
        login = await value.get("/login")
        response = await value.post(
            "/login",
            data={
                "password": "correct horse battery staple",
                "csrf_token": csrf(await login.text()),
            },
            allow_redirects=False,
        )
        assert response.status == 302
        yield value, manager, tmp_path


async def test_four_pages_escape_persona_and_never_render_secrets_or_chat(
    authenticated: tuple[TestClient, FakeManager, Path],
) -> None:
    client, _, _ = authenticated
    expected_fields = {
        "/settings": {
            "continuous_window_seconds",
            "window_max_attempts",
            "window_max_replies",
            "daily_model_calls",
            "daily_proactive_calls",
            "daily_vision_calls",
            "proactive_mode",
            "proactive_probability",
            "minimum_reply_interval_seconds",
            "send_delay_seconds",
            "context_max_messages",
            "context_max_characters",
        },
        "/models": {
            "napcat_ws_url",
            "napcat_access_token",
            "chat_provider",
            "chat_base_url",
            "chat_model",
            "chat_api_key",
            "vision_enabled",
            "vision_provider",
            "vision_base_url",
            "vision_model",
            "vision_api_key",
        },
        "/persona": {
            "name",
            "description",
            "personality",
            "scenario",
            "speech_style",
            "identity_response",
            "example_user_1",
            "example_assistant_1",
        },
    }
    for route in ("/", "/settings", "/models", "/persona"):
        response = await client.get(route)
        assert response.status == 200
        text = await response.text()
        assert "nap-secret-value" not in text
        assert "chat-secret-value" not in text
        assert "vision-secret-value" not in text
        assert "private message contents" not in text
        for field in expected_fields.get(route, set()):
            assert f'name="{field}"' in text

    persona = await (await client.get("/persona")).text()
    assert "&lt;script&gt;小薯&lt;/script&gt;" in persona
    assert "<script>小薯</script>" not in persona
    models = await (await client.get("/models")).text()
    assert models.count("已配置") >= 3


def model_form(token: str, **changes: str) -> dict[str, str]:
    fields = {
        "csrf_token": token,
        "napcat_ws_url": "ws://127.0.0.1:3001/",
        "napcat_access_token": "",
        "chat_provider": "deepseek",
        "chat_base_url": "https://api.deepseek.com",
        "chat_model": "deepseek-chat",
        "chat_api_key": "",
        "vision_enabled": "on",
        "vision_provider": "openai_compatible",
        "vision_base_url": "https://vision.example.com/v1",
        "vision_model": "vision-model",
        "vision_api_key": "",
    }
    fields.update(changes)
    return fields


async def test_blank_secret_preserves_and_explicit_clear_removes_value(
    authenticated: tuple[TestClient, FakeManager, Path],
) -> None:
    client, manager, root = authenticated
    models = await client.get("/models")
    token = csrf(await models.text())

    response = await client.post("/models", data=model_form(token))
    assert response.status == 200
    private = load_private_settings(root)
    assert private.napcat_access_token == "nap-secret-value"
    assert private.chat.api_key == "chat-secret-value"
    assert private.vision.api_key == "vision-secret-value"
    assert manager.updated == 1

    response = await client.post(
        "/models",
        data=model_form(token, clear_chat_api_key="on"),
    )
    assert response.status == 200
    assert load_private_settings(root).chat.api_key == ""
    assert manager.updated == 2


async def test_invalid_form_keeps_nonsecret_input_and_hides_sensitive_data(
    authenticated: tuple[TestClient, FakeManager, Path],
) -> None:
    client, manager, _ = authenticated
    models = await client.get("/models")
    token = csrf(await models.text())

    response = await client.post(
        "/models",
        data=model_form(
            token,
            chat_provider="openai_compatible",
            chat_base_url="http://invalid.example/v1",
            chat_model="entered-model",
        ),
    )
    text = await response.text()

    assert response.status == 400
    assert "http://invalid.example/v1" in text
    assert "entered-model" in text
    assert "nap-secret-value" not in text
    assert "chat-secret-value" not in text
    assert manager.updated == 0


async def test_corrupt_private_config_keeps_status_safe_and_disables_start(
    tmp_path: Path,
) -> None:
    save_settings(tmp_path, valid_settings())
    save_persona(tmp_path, valid_persona())
    private_path = tmp_path / "config" / "private.json"
    private_path.parent.mkdir(exist_ok=True)
    private_path.write_text('{"leaked-marker":"secret-content"', encoding="utf-8")
    AuthStore(tmp_path).create_password("correct horse battery staple")
    app = create_app(tmp_path, cast(BotManager, FakeManager()))
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        login = await client.get("/login")
        await client.post(
            "/login",
            data={
                "password": "correct horse battery staple",
                "csrf_token": csrf(await login.text()),
            },
        )
        response = await client.get("/")
        text = await response.text()

    assert response.status == 200
    assert "配置无效" in text
    assert "disabled" in text
    assert "leaked-marker" not in text
    assert "secret-content" not in text
    assert str(tmp_path) not in text


async def test_failed_atomic_save_keeps_secret_and_runtime_snapshot(
    authenticated: tuple[TestClient, FakeManager, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager, root = authenticated
    models = await client.get("/models")
    token = csrf(await models.text())

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("private path and secret must stay server-side")

    monkeypatch.setattr("config.storage.os.replace", fail_replace)
    response = await client.post("/models", data=model_form(token, chat_api_key="new-secret-value"))
    text = await response.text()

    assert response.status == 500
    assert load_private_settings(root).chat.api_key == "chat-secret-value"
    assert manager.updated == 0
    assert "new-secret-value" not in text
    assert "private path" not in text


async def test_status_reports_budget_errors_and_start_stop_state(
    authenticated: tuple[TestClient, FakeManager, Path],
) -> None:
    client, manager, _ = authenticated
    manager.errors = (SafeError("2026-09-25T12:00:00-05:00", "model_timeout"),)

    status = await client.get("/")
    text = await status.text()
    token = csrf(text)
    assert "stopped" in text
    assert "0 / 50" in text
    assert "model_timeout" in text

    response = await client.post("/bot/start", data={"csrf_token": token})
    assert response.status == 200
    assert "starting" in await response.text()

    response = await client.post("/bot/stop", data={"csrf_token": token})
    assert response.status == 200
    assert "stopped" in await response.text()


def settings_form(token: str, **changes: str) -> dict[str, str]:
    fields = {
        "csrf_token": token,
        "continuous_window_seconds": "600",
        "window_max_attempts": "5",
        "window_max_replies": "4",
        "daily_model_calls": "50",
        "daily_proactive_calls": "5",
        "daily_vision_calls": "5",
        "proactive_mode": "both",
        "proactive_probability": "0.1",
        "minimum_reply_interval_seconds": "1",
        "send_delay_seconds": "0.5",
        "context_max_messages": "20",
        "context_max_characters": "6000",
    }
    fields.update(changes)
    return fields


def persona_form(token: str, **changes: str) -> dict[str, str]:
    fields = {
        "csrf_token": token,
        "name": "小薯",
        "description": "群友",
        "personality": "认真",
        "scenario": "QQ群",
        "speech_style": "简短",
        "identity_response": "不知道",
        "example_user_1": "你好",
        "example_assistant_1": "你好呀",
        "example_user_2": "",
        "example_assistant_2": "",
        "example_user_3": "",
        "example_assistant_3": "",
    }
    fields.update(changes)
    return fields


async def test_behavior_and_persona_forms_validate_save_and_keep_entered_values(
    authenticated: tuple[TestClient, FakeManager, Path],
) -> None:
    client, manager, root = authenticated
    settings_page = await client.get("/settings")
    settings_token = csrf(await settings_page.text())

    response = await client.post(
        "/settings", data=settings_form(settings_token, send_delay_seconds="2.5")
    )
    assert response.status == 200
    assert load_settings(root).send_delay_seconds == 2.5
    assert manager.updated == 1

    response = await client.post(
        "/settings", data=settings_form(settings_token, continuous_window_seconds="bad-value")
    )
    assert response.status == 400
    assert "bad-value" in await response.text()
    assert manager.updated == 1

    persona_page = await client.get("/persona")
    persona_token = csrf(await persona_page.text())
    response = await client.post("/persona", data=persona_form(persona_token, name="<b>新名字</b>"))
    assert response.status == 200
    assert load_persona(root).name == "<b>新名字</b>"
    assert "&lt;b&gt;新名字&lt;/b&gt;" in await response.text()
    assert manager.updated == 2

    response = await client.post(
        "/persona", data=persona_form(persona_token, name="", description="保留这段输入")
    )
    assert response.status == 400
    assert "保留这段输入" in await response.text()
    assert manager.updated == 2
