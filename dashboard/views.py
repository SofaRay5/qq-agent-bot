"""Small escaped HTML views for the local dashboard."""

from collections.abc import Iterable
from html import escape


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escape(title)}</title><style>
body{{font:16px system-ui;max-width:820px;margin:2rem auto;padding:0 1rem;color:#222}}
nav a{{margin-right:1rem}}label{{display:block;margin:.8rem 0}}
input,select,textarea{{width:100%;padding:.45rem;box-sizing:border-box}}
button{{padding:.5rem 1rem}}.error{{color:#b00020}}.notice{{color:#075}}fieldset{{margin:1rem 0}}
</style></head><body>{body}</body></html>"""


def form_page(title: str, action: str, csrf_token: str, fields: str, error: str = "") -> str:
    return page(title, form_fragment(title, action, csrf_token, fields, error))


def form_fragment(title: str, action: str, csrf_token: str, fields: str, error: str = "") -> str:
    message = f'<p class="error">{escape(error)}</p>' if error else ""
    return (
        f"<h1>{escape(title)}</h1>{message}<form method=post action=\"{escape(action)}\">"
        f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'
        f"{fields}<button type=submit>保存</button></form>"
    )


def password_fields(label: str = "管理密码") -> str:
    return f'<label>{escape(label)}<input type="password" name="password" required></label>'


def navigation(csrf_token: str) -> str:
    return (
        '<nav><a href="/">状态</a><a href="/settings">行为</a>'
        '<a href="/models">模型与连接</a><a href="/persona">人格</a></nav>'
        f'<form method="post" action="/logout"><input type="hidden" name="csrf_token" '
        f'value="{escape(csrf_token)}"><button type="submit">退出</button></form>'
    )


def input_field(label: str, name: str, value: object, input_type: str = "text") -> str:
    step = ' step="any"' if input_type == "number" else ""
    return (
        f'<label>{escape(label)}<input type="{escape(input_type)}" name="{escape(name)}" '
        f'value="{escape(str(value))}"{step}></label>'
    )


def textarea_field(label: str, name: str, value: str) -> str:
    return (
        f'<label>{escape(label)}<textarea name="{escape(name)}" rows="4">'
        f"{escape(value)}</textarea></label>"
    )


def select_field(label: str, name: str, value: str, options: Iterable[str]) -> str:
    choices = "".join(
        f'<option value="{escape(option)}"{" selected" if option == value else ""}>'
        f"{escape(option)}</option>"
        for option in options
    )
    return f'<label>{escape(label)}<select name="{escape(name)}">{choices}</select></label>'


def checkbox_field(label: str, name: str, checked: bool) -> str:
    flag = " checked" if checked else ""
    return (
        f'<label><input style="width:auto" type="checkbox" name="{escape(name)}"{flag}>'
        f"{escape(label)}</label>"
    )


def secret_field(label: str, name: str, configured: bool) -> str:
    state = "已配置；留空保持原值" if configured else "未配置"
    return (
        f'<fieldset><legend>{escape(label)}（{state}）</legend>'
        f'<input type="password" name="{escape(name)}" value="">'
        f'<label><input style="width:auto" type="checkbox" name="clear_{escape(name)}">'
        "清除现有值</label></fieldset>"
    )
