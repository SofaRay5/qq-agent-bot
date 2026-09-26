"""Local authenticated aiohttp dashboard."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Literal, cast

from aiohttp import web
from pydantic import ValidationError

from config.models import (
    ExampleDialogue,
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
from core.budget import DailyBudget
from dashboard.auth import AuthStore, LoginThrottle, Session, SessionStore
from dashboard.runtime import BotManager
from dashboard.views import (
    checkbox_field,
    form_fragment,
    form_page,
    input_field,
    navigation,
    page,
    password_fields,
    secret_field,
    select_field,
    textarea_field,
)

COOKIE = "dashboard_session"
LOGGER = logging.getLogger("dashboard")


@dataclass
class DashboardState:
    root: Path
    manager: BotManager
    auth: AuthStore
    sessions: SessionStore
    throttle: LoginThrottle
    authenticated_session_id: str | None = None

    def new_session(self, authenticated: bool = False) -> Session:
        session = self.sessions.create()
        self.authenticated_session_id = session.session_id if authenticated else None
        return session


STATE: web.AppKey[DashboardState] = web.AppKey("dashboard_state", DashboardState)


def _state(request: web.Request) -> DashboardState:
    return cast(DashboardState, request.app[STATE])


def _cookie(response: web.StreamResponse, session: Session) -> None:
    response.set_cookie(COOKIE, session.session_id, httponly=True, samesite="Strict", path="/")


def _session(request: web.Request) -> Session | None:
    session_id = cast(str | None, request.cookies.get(COOKIE))
    return _state(request).sessions.get(session_id)


def _anonymous_session(request: web.Request, state: DashboardState) -> Session:
    return _session(request) or state.new_session()


def _authenticated(request: web.Request) -> bool:
    session = _session(request)
    state = _state(request)
    return session is not None and session.session_id == state.authenticated_session_id


def _redirect(location: str) -> web.HTTPFound:
    return web.HTTPFound(location)


@web.middleware  # type: ignore[misc]
async def _errors(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as exc:
        LOGGER.error("dashboard request failed: %s", type(exc).__name__)
        return web.Response(
            status=500,
            text=page("请求失败", "<h1>请求失败</h1><p>请稍后重试。</p>"),
            content_type="text/html",
        )


@web.middleware  # type: ignore[misc]
async def _security(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    state = _state(request)
    if request.method == "POST":
        form = await request.post()
        csrf_value = form.get("csrf_token")
        csrf_token = csrf_value if isinstance(csrf_value, str) else None
        if not state.sessions.verify_csrf(request.cookies.get(COOKIE), csrf_token):
            raise web.HTTPForbidden()
    if request.path not in {"/setup", "/login"}:
        if state.auth.needs_setup():
            raise _redirect("/setup")
        if not _authenticated(request):
            raise _redirect("/login")
    return await handler(request)


async def _setup_get(request: web.Request) -> web.Response:
    state = _state(request)
    if not state.auth.needs_setup():
        raise _redirect("/login")
    session = _anonymous_session(request, state)
    response = web.Response(
        text=form_page("创建管理密码", "/setup", session.csrf_token, password_fields()),
        content_type="text/html",
    )
    _cookie(response, session)
    return response


async def _setup_post(request: web.Request) -> web.Response:
    state = _state(request)
    if not state.auth.needs_setup():
        raise _redirect("/login")
    form = await request.post()
    try:
        state.auth.create_password(str(form.get("password", "")))
    except ValueError as exc:
        session = _session(request)
        assert session is not None
        return web.Response(
            status=400,
            text=form_page(
                "创建管理密码", "/setup", session.csrf_token, password_fields(), str(exc)
            ),
            content_type="text/html",
        )
    session = state.new_session(authenticated=True)
    response = web.Response(status=302, headers={"Location": "/"})
    _cookie(response, session)
    return response


async def _login_get(request: web.Request) -> web.Response:
    state = _state(request)
    if state.auth.needs_setup():
        raise _redirect("/setup")
    session = _anonymous_session(request, state)
    response = web.Response(
        text=form_page("登录", "/login", session.csrf_token, password_fields()),
        content_type="text/html",
    )
    _cookie(response, session)
    return response


async def _login_post(request: web.Request) -> web.Response:
    state = _state(request)
    form = await request.post()
    if not state.auth.verify_password(str(form.get("password", ""))):
        await asyncio.sleep(state.throttle.record_failure())
        session = _session(request)
        assert session is not None
        return web.Response(
            status=401,
            text=form_page("登录", "/login", session.csrf_token, password_fields(), "密码错误"),
            content_type="text/html",
        )
    state.throttle.reset()
    session = state.new_session(authenticated=True)
    response = web.Response(status=302, headers={"Location": "/"})
    _cookie(response, session)
    return response


async def _logout(request: web.Request) -> web.Response:
    state = _state(request)
    state.sessions.delete(request.cookies.get(COOKIE))
    state.authenticated_session_id = None
    response = web.Response(status=302, headers={"Location": "/login"})
    response.del_cookie(COOKIE, path="/")
    return response


async def _status(request: web.Request) -> web.Response:
    return await _status_response(request)


async def _status_response(
    request: web.Request, *, status: int = 200, notice: str = ""
) -> web.Response:
    session = _session(request)
    assert session is not None
    state = _state(request)
    error = ""
    private: PrivateSettings | None = None
    settings: Settings | None = None
    try:
        private = load_private_settings(state.root)
        settings = load_settings(state.root)
        load_persona(state.root)
        private.validate_for_start()
    except (ValueError, OSError):
        error = "配置无效，请先检查行为、模型与人格设置。"

    if settings is None:
        usage_text = "调用额度暂不可用"
    else:
        usage = await DailyBudget(settings, state.root / "data" / "model_usage.db").usage()
        usage_text = (
            f"总调用：{usage.total} / {settings.daily_model_calls}，剩余 "
            f"{max(0, settings.daily_model_calls - usage.total)}；"
            f"主动：{usage.proactive} / {settings.daily_proactive_calls}，剩余 "
            f"{max(0, settings.daily_proactive_calls - usage.proactive)}；"
            f"识图：{usage.vision} / {settings.daily_vision_calls}，剩余 "
            f"{max(0, settings.daily_vision_calls - usage.vision)}"
        )
    disabled = " disabled" if error or state.manager.state != "stopped" else ""
    errors = (
        "".join(
            f"<li>{escape(item.time)} {escape(item.category)}</li>" for item in state.manager.errors
        )
        or "<li>无</li>"
    )
    body = (
        navigation(session.csrf_token)
        + "<h1>状态</h1>"
        + (f'<p class="notice">{escape(notice)}</p>' if notice else "")
        + (f'<p class="error">{escape(error)}</p>' if error else "")
        + f"<p>机器人：{escape(state.manager.state)}</p><p>{usage_text}</p>"
        + '<form method="post" action="/bot/start">'
        + f'<input type="hidden" name="csrf_token" value="{escape(session.csrf_token)}">'
        + f"<button type=submit{disabled}>启动机器人</button></form>"
        + '<form method="post" action="/bot/stop">'
        + f'<input type="hidden" name="csrf_token" value="{escape(session.csrf_token)}">'
        + "<button type=submit>停止机器人</button></form>"
        + f"<h2>最近错误</h2><ul>{errors}</ul>"
    )
    return web.Response(status=status, text=page("状态", body), content_type="text/html")


async def _start(request: web.Request) -> web.Response:
    state = _state(request)
    try:
        private = load_private_settings(state.root)
        settings = load_settings(state.root)
        persona = load_persona(state.root)
        private.validate_for_start()
        await state.manager.start(private, settings, persona)
    except (ValueError, OSError):
        return await _status_response(request, status=400, notice="无法启动：配置无效。")
    return await _status_response(request, notice="启动请求已处理。")


async def _stop(request: web.Request) -> web.Response:
    await _state(request).manager.stop()
    return await _status_response(request, notice="停止请求已处理。")


def _form_response(
    request: web.Request, title: str, action: str, fields: str, error: str = ""
) -> web.Response:
    session = _session(request)
    assert session is not None
    return web.Response(
        text=page(
            title,
            navigation(session.csrf_token)
            + form_fragment(title, action, session.csrf_token, fields, error),
        ),
        status=400 if error else 200,
        content_type="text/html",
    )


def _settings_fields(value: Settings) -> str:
    fields = select_field(
        "主动模式", "proactive_mode", value.proactive_mode, ("off", "random", "topic", "both")
    )
    for name, label in (
        ("proactive_probability", "主动回复概率"),
        ("continuous_window_seconds", "持续对话窗口（秒）"),
        ("window_max_attempts", "窗口最大尝试"),
        ("window_max_replies", "窗口最大回复"),
        ("minimum_reply_interval_seconds", "最短回复间隔（秒）"),
        ("send_delay_seconds", "发送延迟（秒）"),
        ("context_max_messages", "上下文消息数"),
        ("context_max_characters", "上下文字符数"),
        ("daily_model_calls", "每日总调用"),
        ("daily_proactive_calls", "每日主动调用"),
        ("daily_vision_calls", "每日识图调用"),
    ):
        fields += input_field(label, name, getattr(value, name), "number")
    return fields


def _settings_fields_from_form(form: Mapping[str, object]) -> str:
    fields = select_field(
        "主动模式",
        "proactive_mode",
        str(form.get("proactive_mode", "off")),
        ("off", "random", "topic", "both"),
    )
    for name, label in (
        ("proactive_probability", "主动回复概率"),
        ("continuous_window_seconds", "持续对话窗口（秒）"),
        ("window_max_attempts", "窗口最大尝试"),
        ("window_max_replies", "窗口最大回复"),
        ("minimum_reply_interval_seconds", "最短回复间隔（秒）"),
        ("send_delay_seconds", "发送延迟（秒）"),
        ("context_max_messages", "上下文消息数"),
        ("context_max_characters", "上下文字符数"),
        ("daily_model_calls", "每日总调用"),
        ("daily_proactive_calls", "每日主动调用"),
        ("daily_vision_calls", "每日识图调用"),
    ):
        fields += input_field(label, name, form.get(name, ""), "number")
    return fields


def _settings_from_form(form: Mapping[str, object]) -> Settings:
    return Settings(
        continuous_window_seconds=int(str(form.get("continuous_window_seconds", ""))),
        window_max_attempts=int(str(form.get("window_max_attempts", ""))),
        window_max_replies=int(str(form.get("window_max_replies", ""))),
        daily_model_calls=int(str(form.get("daily_model_calls", ""))),
        daily_proactive_calls=int(str(form.get("daily_proactive_calls", ""))),
        daily_vision_calls=int(str(form.get("daily_vision_calls", ""))),
        proactive_mode=str(form.get("proactive_mode", "")),  # type: ignore[arg-type]
        proactive_probability=float(str(form.get("proactive_probability", ""))),
        minimum_reply_interval_seconds=float(str(form.get("minimum_reply_interval_seconds", ""))),
        send_delay_seconds=float(str(form.get("send_delay_seconds", ""))),
        context_max_messages=int(str(form.get("context_max_messages", ""))),
        context_max_characters=int(str(form.get("context_max_characters", ""))),
    )


async def _settings_get(request: web.Request) -> web.Response:
    fields = _settings_fields(load_settings(_state(request).root))
    return _form_response(request, "行为设置", "/settings", fields)


async def _settings_post(request: web.Request) -> web.Response:
    form = await request.post()
    try:
        value = _settings_from_form(form)
        state = _state(request)
        save_settings(state.root, value)
        state.manager.update_runtime(
            load_private_settings(state.root), value, load_persona(state.root)
        )
    except (ValueError, OSError, ValidationError):
        return _form_response(
            request,
            "行为设置",
            "/settings",
            _settings_fields_from_form(form),
            "设置无效，请检查字段",
        )
    return _form_response(request, "行为设置", "/settings", _settings_fields(value))


def _models_fields(value: PrivateSettings) -> str:
    return (
        input_field("NapCat WebSocket 地址", "napcat_ws_url", value.napcat_ws_url)
        + secret_field("NapCat Token", "napcat_access_token", bool(value.napcat_access_token))
        + "<h2>聊天模型</h2>"
        + select_field(
            "服务", "chat_provider", value.chat.provider, ("deepseek", "openai_compatible")
        )
        + input_field("API 地址", "chat_base_url", value.chat.base_url)
        + input_field("模型名", "chat_model", value.chat.model)
        + secret_field("API Key", "chat_api_key", bool(value.chat.api_key))
        + "<h2>识图模型</h2>"
        + checkbox_field("启用识图", "vision_enabled", value.vision_enabled)
        + select_field(
            "服务",
            "vision_provider",
            value.vision.provider,
            ("deepseek", "openai_compatible"),
        )
        + input_field("API 地址", "vision_base_url", value.vision.base_url)
        + input_field("模型名", "vision_model", value.vision.model)
        + secret_field("API Key", "vision_api_key", bool(value.vision.api_key))
    )


def _models_fields_from_form(form: Mapping[str, object], current: PrivateSettings) -> str:
    def value(name: str, fallback: str) -> str:
        return str(form.get(name, fallback))

    return (
        input_field("NapCat WebSocket 地址", "napcat_ws_url", value("napcat_ws_url", ""))
        + secret_field("NapCat Token", "napcat_access_token", bool(current.napcat_access_token))
        + "<h2>聊天模型</h2>"
        + select_field(
            "服务",
            "chat_provider",
            value("chat_provider", current.chat.provider),
            ("deepseek", "openai_compatible"),
        )
        + input_field("API 地址", "chat_base_url", value("chat_base_url", ""))
        + input_field("模型名", "chat_model", value("chat_model", ""))
        + secret_field("API Key", "chat_api_key", bool(current.chat.api_key))
        + "<h2>识图模型</h2>"
        + checkbox_field("启用识图", "vision_enabled", form.get("vision_enabled") == "on")
        + select_field(
            "服务",
            "vision_provider",
            value("vision_provider", current.vision.provider),
            ("deepseek", "openai_compatible"),
        )
        + input_field("API 地址", "vision_base_url", value("vision_base_url", ""))
        + input_field("模型名", "vision_model", value("vision_model", ""))
        + secret_field("API Key", "vision_api_key", bool(current.vision.api_key))
    )


def _secret(form: Mapping[str, object], name: str, current: str) -> str:
    if form.get(f"clear_{name}") == "on":
        return ""
    entered = str(form.get(name, ""))
    return entered or current


def _provider(
    form: Mapping[str, object], prefix: str, current: ProviderSettings
) -> ProviderSettings:
    provider = str(form.get(f"{prefix}_provider", ""))
    if provider not in {"deepseek", "openai_compatible"}:
        raise ValueError("Invalid provider")
    provider_name = cast(Literal["deepseek", "openai_compatible"], provider)
    base_url = str(form.get(f"{prefix}_base_url", ""))
    model = str(form.get(f"{prefix}_model", ""))
    if provider == "deepseek":
        base_url = base_url or "https://api.deepseek.com"
        model = model or "deepseek-chat"
    return ProviderSettings(
        provider=provider_name,
        base_url=base_url,
        model=model,
        api_key=_secret(form, f"{prefix}_api_key", current.api_key),
    )


async def _models_get(request: web.Request) -> web.Response:
    value = load_private_settings(_state(request).root)
    return _form_response(request, "模型与连接", "/models", _models_fields(value))


async def _models_post(request: web.Request) -> web.Response:
    state = _state(request)
    form = await request.post()
    current: PrivateSettings | None = None
    try:
        current = load_private_settings(state.root)
        value = PrivateSettings(
            napcat_ws_url=str(form.get("napcat_ws_url", "")),
            napcat_access_token=_secret(form, "napcat_access_token", current.napcat_access_token),
            chat=_provider(form, "chat", current.chat),
            vision_enabled=form.get("vision_enabled") == "on",
            vision=_provider(form, "vision", current.vision),
        )
        restart = (value.napcat_ws_url, value.napcat_access_token) != (
            current.napcat_ws_url,
            current.napcat_access_token,
        )
        save_private_settings(state.root, value)
        state.manager.update_runtime(value, load_settings(state.root), load_persona(state.root))
    except OSError:
        fields = _models_fields(current) if current is not None else ""
        response = _form_response(request, "模型与连接", "/models", fields, "保存失败，请稍后重试")
        response.set_status(500)
        return response
    except (ValueError, ValidationError):
        fields = _models_fields_from_form(form, current) if current is not None else ""
        return _form_response(request, "模型与连接", "/models", fields, "设置无效，请检查字段")
    notice = "<p class=notice>NapCat 设置已变更，请重启机器人。</p>" if restart else ""
    return _form_response(request, "模型与连接", "/models", notice + _models_fields(value))


def _persona_fields(value: Persona) -> str:
    fields = input_field("名字", "name", value.name)
    for name, label in (
        ("description", "描述"),
        ("personality", "性格"),
        ("scenario", "场景"),
        ("speech_style", "说话风格"),
        ("identity_response", "身份回答"),
    ):
        fields += textarea_field(label, name, getattr(value, name))
    for index in range(3):
        dialogue = value.example_dialogues[index] if index < len(value.example_dialogues) else None
        fields += input_field(
            f"示例 {index + 1} 用户", f"example_user_{index + 1}", dialogue.user if dialogue else ""
        )
        fields += input_field(
            f"示例 {index + 1} 回复",
            f"example_assistant_{index + 1}",
            dialogue.assistant if dialogue else "",
        )
    return fields


def _persona_fields_from_form(form: Mapping[str, object]) -> str:
    fields = input_field("名字", "name", form.get("name", ""))
    for name, label in (
        ("description", "描述"),
        ("personality", "性格"),
        ("scenario", "场景"),
        ("speech_style", "说话风格"),
        ("identity_response", "身份回答"),
    ):
        fields += textarea_field(label, name, str(form.get(name, "")))
    for index in range(1, 4):
        fields += input_field(
            f"示例 {index} 用户", f"example_user_{index}", form.get(f"example_user_{index}", "")
        )
        fields += input_field(
            f"示例 {index} 回复",
            f"example_assistant_{index}",
            form.get(f"example_assistant_{index}", ""),
        )
    return fields


def _persona_from_form(form: Mapping[str, object]) -> Persona:
    dialogues = []
    for index in range(1, 4):
        user = str(form.get(f"example_user_{index}", "")).strip()
        assistant = str(form.get(f"example_assistant_{index}", "")).strip()
        if user or assistant:
            dialogues.append(ExampleDialogue(user=user, assistant=assistant))
    return Persona(
        name=str(form.get("name", "")),
        description=str(form.get("description", "")),
        personality=str(form.get("personality", "")),
        scenario=str(form.get("scenario", "")),
        speech_style=str(form.get("speech_style", "")),
        identity_response=str(form.get("identity_response", "")),
        example_dialogues=dialogues,
    )


async def _persona_get(request: web.Request) -> web.Response:
    value = load_persona(_state(request).root)
    return _form_response(request, "人格", "/persona", _persona_fields(value))


async def _persona_post(request: web.Request) -> web.Response:
    state = _state(request)
    form = await request.post()
    try:
        value = _persona_from_form(form)
        save_persona(state.root, value)
        state.manager.update_runtime(
            load_private_settings(state.root), load_settings(state.root), value
        )
    except (ValueError, OSError, ValidationError):
        return _form_response(
            request,
            "人格",
            "/persona",
            _persona_fields_from_form(form),
            "设置无效，请检查字段",
        )
    return _form_response(request, "人格", "/persona", _persona_fields(value))


def create_app(root: Path, manager: BotManager) -> web.Application:
    app = web.Application(client_max_size=65_536, middlewares=[_errors, _security])
    app[STATE] = DashboardState(root, manager, AuthStore(root), SessionStore(), LoginThrottle())
    app.router.add_get("/", _status)
    app.router.add_get("/setup", _setup_get)
    app.router.add_post("/setup", _setup_post)
    app.router.add_get("/login", _login_get)
    app.router.add_post("/login", _login_post)
    app.router.add_post("/logout", _logout)
    app.router.add_post("/bot/start", _start)
    app.router.add_post("/bot/stop", _stop)
    app.router.add_get("/settings", _settings_get)
    app.router.add_post("/settings", _settings_post)
    app.router.add_get("/models", _models_get)
    app.router.add_post("/models", _models_post)
    app.router.add_get("/persona", _persona_get)
    app.router.add_post("/persona", _persona_post)
    return app
