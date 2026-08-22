from typing import Any

import pytest
from pydantic import ValidationError

from onebot_adapter.event import (
    GroupMessageEvent,
    HeartbeatEvent,
    PrivateMessageEvent,
    UnknownEvent,
    parse_event,
)

# private_message_json / group_message_json / heartbeat_json 三个 fixture 定义在
# conftest.py 里，从 tests/fixtures/*.json 读取，不在这里重复写。


class TestPrivateMessageEvent:
    def test_parses_valid_private_message(self, private_message_json: dict[str, Any]) -> None:
        event = parse_event(private_message_json)
        assert isinstance(event, PrivateMessageEvent)
        assert event.user_id == 111
        assert event.sender.nickname == "小明"

    def test_missing_required_field_raises(self, private_message_json: dict[str, Any]) -> None:
        del private_message_json["user_id"]
        with pytest.raises(ValidationError):
            parse_event(private_message_json)

    def test_private_message_has_no_group_id_field(self) -> None:
        assert not hasattr(PrivateMessageEvent, "group_id")


class TestGroupMessageEvent:
    def test_parses_valid_group_message(self, group_message_json: dict[str, Any]) -> None:
        event = parse_event(group_message_json)
        assert isinstance(event, GroupMessageEvent)
        assert event.group_id == 999

    def test_missing_group_id_raises(self, group_message_json: dict[str, Any]) -> None:
        del group_message_json["group_id"]
        with pytest.raises(ValidationError):
            parse_event(group_message_json)

    def test_missing_required_field_raises(self, group_message_json: dict[str, Any]) -> None:
        del group_message_json["message_id"]
        with pytest.raises(ValidationError):
            parse_event(group_message_json)


class TestHeartbeatEvent:
    def test_parses_valid_heartbeat(self, heartbeat_json: dict[str, Any]) -> None:
        event = parse_event(heartbeat_json)
        assert isinstance(event, HeartbeatEvent)
        assert event.interval == 15000

    def test_missing_interval_raises(self, heartbeat_json: dict[str, Any]) -> None:
        del heartbeat_json["interval"]
        with pytest.raises(ValidationError):
            parse_event(heartbeat_json)


class TestUnknownEventTolerance:
    def test_unknown_post_type_does_not_raise(self) -> None:
        data = {
            "time": 1700000000,
            "self_id": 123456,
            "post_type": "notice",
            "notice_type": "group_upload",
        }
        event = parse_event(data)
        assert isinstance(event, UnknownEvent)
        assert event.raw == data

    def test_unknown_message_type_does_not_raise(
        self, private_message_json: dict[str, Any]
    ) -> None:
        private_message_json["message_type"] = "channel"
        event = parse_event(private_message_json)
        assert isinstance(event, UnknownEvent)

    def test_unknown_meta_event_type_does_not_raise(self, heartbeat_json: dict[str, Any]) -> None:
        heartbeat_json["meta_event_type"] = "lifecycle"
        event = parse_event(heartbeat_json)
        assert isinstance(event, UnknownEvent)
