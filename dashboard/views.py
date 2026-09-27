"""Small escaped HTML views for the local dashboard."""

# ruff: noqa: E501 -- keeping the embedded CSS readable as CSS.

from collections.abc import Iterable
from html import escape


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escape(title)}</title><style>
:root{{--bg:#f4f6fb;--card:#fff;--text:#1e293b;--muted:#64748b;--line:#dbe2ea;--brand:#4f46e5;--danger:#b42318;--ok:#067647}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}}
body>main{{max-width:960px;margin:auto;padding:1.25rem}}nav{{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:1rem}}
nav a{{color:var(--muted);padding:.5rem .75rem;border-radius:.6rem;text-decoration:none}}nav a[aria-current=page]{{background:var(--brand);color:white}}
h1{{font-size:1.7rem}}h2{{font-size:1.15rem}}form,.card{{background:var(--card);border:1px solid var(--line);border-radius:.8rem;padding:1rem;margin:1rem 0}}
nav+form{{background:none;border:0;padding:0;margin:-3.65rem 0 1rem auto;width:max-content}}label{{display:block;margin:.8rem 0;font-weight:600}}
input,select,textarea{{display:block;width:100%;margin-top:.25rem;padding:.65rem;border:1px solid var(--line);border-radius:.5rem;background:white;color:inherit;font:inherit}}
input[type=checkbox]{{display:inline;width:auto;margin:0 .45rem 0 0}}button{{padding:.65rem 1rem;border:0;border-radius:.5rem;background:var(--brand);color:white;font-weight:650;cursor:pointer}}
fieldset{{border:0;padding:0;margin:0}}details{{margin:1rem 0}}summary{{cursor:pointer;font-weight:700;padding:.25rem 0}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 1rem}}.error{{color:var(--danger)}}.notice{{color:var(--ok)}}.hint{{color:var(--muted);font-size:.9rem}}
@media(max-width:640px){{body>main{{padding:.8rem}}.grid{{grid-template-columns:1fr}}nav+form{{margin:0 0 1rem}}}}
</style></head><body><main>{body}</main><script>
document.querySelectorAll('[data-toggle]').forEach(c=>{{let f=document.getElementById(c.dataset.toggle);let sync=()=>{{f.disabled=c.dataset.invert?c.checked:!c.checked}};c.addEventListener('change',sync);sync()}})
</script></body></html>"""


def form_page(title: str, action: str, csrf_token: str, fields: str, error: str = "") -> str:
    return page(title, form_fragment(title, action, csrf_token, fields, error))


def form_fragment(
    title: str, action: str, csrf_token: str, fields: str, error: str = "", notice: str = ""
) -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    notice_html = f'<p class="notice" role="status">{escape(notice)}</p>' if notice else ""
    return (
        f'<h1>{escape(title)}</h1>{error_html}{notice_html}<form method="post" action="{escape(action)}">'
        f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'
        f'{fields}<button type="submit">保存</button></form>'
    )


def password_fields(label: str = "管理密码") -> str:
    return input_field(label, "password", "", "password", required=True)


def navigation(csrf_token: str, current: str = "") -> str:
    links = (
        ("/", "状态"),
        ("/settings", "行为"),
        ("/models", "模型与连接"),
        ("/persona", "人格"),
    )
    items = "".join(
        f'<a href="{path}"{" aria-current=" + chr(34) + "page" + chr(34) if path == current else ""}>{label}</a>'
        for path, label in links
    )
    return (
        f"<nav>{items}</nav>"
        f'<form method="post" action="/logout"><input type="hidden" name="csrf_token" '
        f'value="{escape(csrf_token)}"><button type="submit">退出</button></form>'
    )


def input_field(
    label: str, name: str, value: object, input_type: str = "text", *, required: bool = False
) -> str:
    step = ' step="any"' if input_type == "number" else ""
    required_html = " required" if required else ""
    escaped_name = escape(name)
    return (
        f'<label for="{escaped_name}">{escape(label)}</label><input id="{escaped_name}" '
        f'type="{escape(input_type)}" name="{escaped_name}" value="{escape(str(value))}"'
        f"{step}{required_html}>"
    )


def textarea_field(label: str, name: str, value: str) -> str:
    escaped_name = escape(name)
    return (
        f'<label for="{escaped_name}">{escape(label)}</label><textarea id="{escaped_name}" '
        f'name="{escaped_name}" rows="4">{escape(value)}</textarea>'
    )


def select_field(label: str, name: str, value: str, options: Iterable[str]) -> str:
    choices = "".join(
        f'<option value="{escape(option)}"{" selected" if option == value else ""}>'
        f"{escape(option)}</option>"
        for option in options
    )
    escaped_name = escape(name)
    return (
        f'<label for="{escaped_name}">{escape(label)}</label><select id="{escaped_name}" '
        f'name="{escaped_name}">{choices}</select>'
    )


def checkbox_field(
    label: str, name: str, checked: bool, *, toggle: str = "", invert: bool = False
) -> str:
    flag = " checked" if checked else ""
    toggle_html = f' data-toggle="{escape(toggle)}"' if toggle else ""
    invert_html = ' data-invert="true"' if invert else ""
    return (
        f'<label><input type="checkbox" name="{escape(name)}"{flag}{toggle_html}{invert_html}>'
        f"{escape(label)}</label>"
    )


def secret_field(label: str, name: str, configured: bool) -> str:
    state = "已配置；留空保持原值" if configured else "未配置"
    escaped_name = escape(name)
    return (
        f"<fieldset><legend>{escape(label)}（{state}）</legend>"
        f'<label class="hint" for="{escaped_name}">输入新值</label>'
        f'<input id="{escaped_name}" type="password" name="{escaped_name}" value="" '
        f'autocomplete="new-password"><label><input type="checkbox" '
        f'name="clear_{escaped_name}">清除现有值</label></fieldset>'
    )
