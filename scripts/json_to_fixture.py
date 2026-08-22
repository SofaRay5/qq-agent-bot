"""把一段示例 JSON（比如从真实 NapCat 抓包拿到的原始事件）转成 tests/fixtures/ 下的
一个格式化好的 fixture 文件，供测试用例通过 conftest.py 的 load_fixture() 加载。

用法：
    uv run python scripts/json_to_fixture.py <输入JSON文件路径> <fixture名字，不带扩展名>

例：
    uv run python scripts/json_to_fixture.py raw_capture.json group_message_with_at

会写入 tests/fixtures/group_message_with_at.json（校验过是合法 JSON、按 2 空格缩进格式化）。
"""

import json
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    src_path = Path(sys.argv[1])
    fixture_name = sys.argv[2]

    raw_text = src_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"输入文件不是合法 JSON: {e}")
        sys.exit(1)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = FIXTURES_DIR / f"{fixture_name}.json"
    dest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已写入 {dest_path.relative_to(FIXTURES_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
