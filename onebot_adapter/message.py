"""Extract replyable text from OneBot array-form messages."""

from onebot_adapter.event import GroupMessageEvent, PrivateMessageEvent


def text_for_reply(event: PrivateMessageEvent | GroupMessageEvent) -> str | None:
    """Return private text or text following the bot mention in a group."""
    start = 0
    if isinstance(event, GroupMessageEvent):
        for index, segment in enumerate(event.message):
            data = segment.get("data")
            if (
                segment.get("type") == "at"
                and isinstance(data, dict)
                and str(data.get("qq")) == str(event.self_id)
            ):
                start = index + 1
                break
        else:
            return None
    parts: list[str] = []
    for segment in event.message[start:]:
        data = segment.get("data")
        if segment.get("type") == "text" and isinstance(data, dict):
            value = data.get("text")
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts).strip() or None
