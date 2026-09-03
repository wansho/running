# Strava 历史快照与 Garmin 增量同步实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Strava 官网导出快照和 Garmin 每日增量替代 Strava API，同时在 GitHub Actions 中安全持久化可能轮换的 Garmin refresh token。

**Architecture:** 本地导入器把 Strava CSV、GPX 和 FIT 转成稳定快照；每日同步器解密 Garmin tokenstore、拉取边界后的活动、原子更新增量文件，再合并三类来源生成 CSV。Garmin token 只以加密文件入库，刷新后的 access token 与 refresh token 在任务退出前重新加密并单独保障提交。

**Tech Stack:** Python 3.11、pytest、garminconnect 0.3.1、cryptography、fitdecode、标准库 csv/json/gzip/xml、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-09-03-strava-garmin-sync-design.md`

## Global Constraints

- 最终运行环境是 GitHub Actions，计划任务为每天北京时间 08:00。
- 数据源固定为手工 JSON、Strava 官网导出快照、Garmin 增量 JSON。
- 排除所有 Garmin `typeId=2` 或 `parentTypeId=2` 的骑行活动，其他类型保留。
- Strava 截止点为 `2026-09-02 22:14:05 UTC`，对应北京时间 `2026-09-03 06:14:05`。
- Garmin 新活动必须严格晚于 Strava 截止 UTC 时间。
- refresh token 轮换必须与 access token 一起持久化。
- 明文 Garmin token、账号和密码不得写入仓库或日志。
- HTTP 请求只允许 GET 和 POST；本实现不新增其他请求方法。
- 不使用 worktree，不创建名称包含禁用字样的分支或文件。
- 保留工作区中用户已有的 `sync.py`、数据文件和 `vibe.md` 未提交内容；每次只暂存当前任务明确列出的文件。
- 所有提交使用中文说明，每条说明不超过 20 个汉字。

## 文件结构

- Create: `activity_records.py` — 统一记录转换、时间解析、骑行判断、去重与原子 JSON 写入。
- Create: `import_strava_export.py` — 一次性读取 Strava 导出并生成历史快照。
- Create: `garmin_tokens.py` — tokenstore 加解密、变化检测和安全清理。
- Modify: `sync.py` — Garmin 拉取、增量状态更新、三源合并和 CSV 输出入口。
- Create: `tests/test_activity_records.py` — 通用记录与去重测试。
- Create: `tests/test_import_strava_export.py` — 中文 CSV、GPX/FIT 导入测试。
- Create: `tests/test_garmin_tokens.py` — token 加密和 refresh token 轮换测试。
- Create: `tests/test_sync.py` — Garmin 映射、边界、失败保护和幂等测试。
- Create: `tests/fixtures/strava_export/activities.csv` — 最小中文 Strava 导出样本。
- Create: `tests/fixtures/strava_export/activities/sample.gpx` — GPX 起点样本。
- Create: `tests/fixtures/strava_export/activities/sample.fit.gz` — FIT 起点样本。
- Create: `data/running_records_strava_export.json` — 完整 Strava 标准快照。
- Create: `data/running_records_garmin_sync.json` — Garmin 增量状态。
- Create: `data/garmin_tokens.enc` — Garmin tokenstore 密文。
- Modify: `requirements.txt` — 替换 Strava 依赖并加入 Garmin、FIT 和加密依赖。
- Modify: `.github/workflows/sync_render.yml` — 每日同步、并发锁、最小权限与失败后持久化。
- Modify: `README.md` — 本地导入、密钥初始化、Secret 配置和故障恢复说明。
- Modify: `CLAUDE.md` — 更新项目架构与命令说明。

---

### Task 1: 统一活动记录、过滤和去重

**Files:**
- Create: `activity_records.py`
- Create: `tests/test_activity_records.py`

**Interfaces:**
- Produces: `parse_datetime(value: str) -> datetime | None`
- Produces: `calculate_pace(distance_m: float, moving_time_s: float) -> str | None`
- Produces: `is_cycling_type(type_id: int | None, parent_type_id: int | None, type_key: str) -> bool`
- Produces: `activity_fingerprint(record: dict) -> tuple[str, int, int]`
- Produces: `merge_records(manual: list[dict], strava: list[dict], garmin: list[dict], cutoff_utc: datetime) -> list[dict]`
- Produces: `write_json_atomic(path: Path, payload: dict) -> None`

- [ ] **Step 1: 写失败测试，锁定过滤与来源优先级**

```python
from datetime import datetime

from activity_records import is_cycling_type, merge_records


def test_cycling_parent_and_root_are_excluded():
    assert is_cycling_type(2, 17, "cycling") is True
    assert is_cycling_type(10, 2, "road_biking") is True
    assert is_cycling_type(1, 17, "running") is False


def test_merge_uses_strava_at_cutoff_and_garmin_after_cutoff():
    cutoff = datetime.fromisoformat("2026-09-02 22:14:05")
    strava = [{
        "run_id": 20012158657,
        "start_date": "2026-09-02 22:14:05",
        "start_date_local": "2026-09-03 06:14:05",
        "distance": 705.0,
        "moving_time": 536.0,
        "source": "strava",
    }]
    garmin = [
        {**strava[0], "run_id": 24216312645, "source": "garmin"},
        {
            "run_id": 24220000000,
            "start_date": "2026-09-03 22:00:00",
            "start_date_local": "2026-09-04 06:00:00",
            "distance": 1000.0,
            "moving_time": 600.0,
            "source": "garmin",
        },
    ]

    result = merge_records([], strava, garmin, cutoff)

    assert [row["run_id"] for row in result] == [20012158657, 24220000000]
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `pytest tests/test_activity_records.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'activity_records'`。

- [ ] **Step 3: 实现最小公共逻辑**

```python
def is_cycling_type(type_id, parent_type_id, type_key):
    return type_id == 2 or parent_type_id == 2 or type_key in {"Ride", "骑行"}


def activity_fingerprint(record):
    start = record.get("start_date", "")
    distance = round(float(record.get("distance") or 0))
    duration = round(float(record.get("moving_time") or record.get("elapsed_time") or 0))
    return start, distance, duration
```

实现 `merge_records` 时先按来源边界过滤，再按来源 ID 和活动指纹去重。实现 `write_json_atomic` 时在目标目录创建临时文件，完成 `json.dump` 和 `flush` 后用 `Path.replace` 原子替换。

- [ ] **Step 4: 增加配速、时间容错和原子写入测试**

```python
def test_pace_rounds_to_minutes_and_seconds():
    assert calculate_pace(1000.0, 359.6) == "6:00"


def test_atomic_write_keeps_valid_json(tmp_path):
    target = tmp_path / "records.json"
    write_json_atomic(target, {"records": [{"run_id": 1}]})
    assert json.loads(target.read_text())["records"][0]["run_id"] == 1
```

- [ ] **Step 5: 运行公共逻辑测试**

Run: `pytest tests/test_activity_records.py -v`

Expected: PASS。

- [ ] **Step 6: 提交公共逻辑**

```bash
git add activity_records.py tests/test_activity_records.py
git commit -m "feat: 增加活动合并规则" -m "- 统一时间与配速\n- 排除全部骑行类型\n- 增加跨来源去重"
```

### Task 2: 实现 Strava 官网导出器

**Files:**
- Create: `import_strava_export.py`
- Create: `tests/test_import_strava_export.py`
- Create: `tests/fixtures/strava_export/activities.csv`
- Create: `tests/fixtures/strava_export/activities/sample.gpx`
- Create: `tests/fixtures/strava_export/activities/sample.fit.gz`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `calculate_pace`、`is_cycling_type`、`write_json_atomic`
- Produces: `parse_strava_csv(export_dir: Path) -> list[dict]`
- Produces: `extract_track_metadata(path: Path) -> dict[str, object]`
- Produces: `build_strava_snapshot(export_dir: Path) -> dict`
- Produces CLI: `python import_strava_export.py EXPORT_DIR [--output PATH]`

- [ ] **Step 1: 创建最小中文 CSV 与 GPX fixture**

CSV 至少包含一条跑步、一条骑行和一条缺失轨迹的健走记录，字段使用真实中文表头：`活动 ID`、`活动日期`、`活动名称`、`活动类型`、`全程耗时`、`移动时间`、`距离`、`平均速度`、`平均心率`、`文件名`。

GPX fixture 使用以下最小轨迹点：

```xml
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg><trkpt lat="31.86246" lon="118.83694">
    <time>2026-09-02T22:14:05Z</time>
  </trkpt></trkseg></trk>
</gpx>
```

- [ ] **Step 2: 写失败测试，验证中文字段、骑行过滤与坐标降级**

```python
def test_build_snapshot_filters_ride_and_keeps_missing_track(tmp_path):
    snapshot = build_strava_snapshot(FIXTURE_DIR)

    assert [r["type"] for r in snapshot["records"]] == ["Run", "Walk"]
    assert snapshot["records"][0]["start_lat"] == 31.86246
    assert snapshot["records"][1].get("start_lat") is None
    assert snapshot["last_activity_start_utc"] == "2026-09-02 22:14:05"
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `pytest tests/test_import_strava_export.py -v`

Expected: FAIL because `build_strava_snapshot` does not exist。

- [ ] **Step 4: 实现 CSV 与 GPX 解析**

使用 `csv.DictReader(..., encoding="utf-8-sig")`。Strava `活动日期` 按 `%Y年%m月%d日 %H:%M:%S` 解析为 UTC；中文类型映射至少包含 `跑步 -> Run`、`健走 -> Walk`、`远足 -> Hike`，未知类型保留原值。GPX 使用标准库 `xml.etree.ElementTree` 获取第一个有效轨迹点。

- [ ] **Step 5: 增加 FIT 与压缩 FIT 测试后实现解析**

```python
def test_extracts_first_fit_position_and_local_timestamp():
    result = extract_track_metadata(FIXTURE_DIR / "activities/sample.fit.gz")
    assert result["start_lat"] == pytest.approx(31.86246, abs=0.0001)
    assert result["start_lng"] == pytest.approx(118.83694, abs=0.0001)
    assert result["start_date_local"] == "2026-09-03 06:14:05"
```

用 `fitdecode` 读取 `session` 或首个含 `position_lat`、`position_long` 的 `record`。FIT semicircle 坐标乘以 `180 / 2**31`。`.fit.gz` 先通过 `gzip.open` 解压到内存或临时文件，临时文件在 `finally` 删除。

- [ ] **Step 6: 实现 CLI 和原子输出**

CLI 默认输出 `data/running_records_strava_export.json`，完成后记录数量、类型分布、坐标覆盖数、最早时间和截止时间；日志不得包含导出目录中的其他隐私文件内容。

- [ ] **Step 7: 运行导入器测试与静态检查**

Run: `pytest tests/test_import_strava_export.py tests/test_activity_records.py -v`

Expected: PASS。

Run: `python -m py_compile import_strava_export.py activity_records.py`

Expected: exit 0。

- [ ] **Step 8: 提交 Strava 导入器**

```bash
git add import_strava_export.py activity_records.py tests/test_import_strava_export.py tests/fixtures/strava_export requirements.txt
git commit -m "feat: 导入官网历史活动" -m "- 解析中文活动汇总\n- 提取轨迹起点坐标\n- 记录数据截止时间"
```

### Task 3: 实现 Garmin token 加密与轮换持久化

**Files:**
- Create: `garmin_tokens.py`
- Create: `tests/test_garmin_tokens.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `decrypt_tokenstore(encrypted_path: Path, output_dir: Path, key: str) -> Path`
- Produces: `persist_tokenstore_if_changed(token_path: Path, original_json: str, encrypted_path: Path, key: str) -> bool`
- Produces: `remove_plaintext_token(path: Path) -> None`
- Produces CLI: `python garmin_tokens.py encrypt --input PATH --output PATH`
- Produces CLI: `python garmin_tokens.py decrypt --input PATH --output-dir PATH`

- [ ] **Step 1: 写 refresh token 轮换失败测试**

```python
def test_persists_rotated_refresh_token(tmp_path, fernet_key):
    token_path = tmp_path / "plain" / "garmin_tokens.json"
    token_path.parent.mkdir()
    before = json.dumps({"di_token": "old-a", "di_refresh_token": "old-r", "di_client_id": "c"})
    after = json.dumps({"di_token": "new-a", "di_refresh_token": "new-r", "di_client_id": "c"})
    token_path.write_text(after)
    encrypted = tmp_path / "garmin_tokens.enc"

    changed = persist_tokenstore_if_changed(token_path, before, encrypted, fernet_key)
    restored = decrypt_tokenstore(encrypted, tmp_path / "restored", fernet_key)

    assert changed is True
    assert json.loads(restored.read_text())["di_refresh_token"] == "new-r"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/test_garmin_tokens.py::test_persists_rotated_refresh_token -v`

Expected: FAIL because `garmin_tokens` does not exist。

- [ ] **Step 3: 用 Fernet 实现认证加密和原子替换**

```python
def persist_tokenstore_if_changed(token_path, original_json, encrypted_path, key):
    current = token_path.read_text(encoding="utf-8")
    validate_token_json(current)
    if json.loads(current) == json.loads(original_json):
        return False
    ciphertext = Fernet(key.encode()).encrypt(current.encode())
    write_bytes_atomic(encrypted_path, ciphertext)
    return True
```

`validate_token_json` 必须要求 `di_token`、`di_refresh_token`、`di_client_id` 都是非空字符串。任何异常只输出文件路径和错误类型，不输出明文。

- [ ] **Step 4: 增加不变、坏密钥、缺字段和清理测试**

```python
def test_unchanged_plaintext_does_not_replace_ciphertext(tmp_path, fernet_key):
    token_path = tmp_path / "garmin_tokens.json"
    content = json.dumps({"di_token": "a", "di_refresh_token": "r", "di_client_id": "c"})
    token_path.write_text(content)
    encrypted = tmp_path / "garmin_tokens.enc"
    encrypted.write_bytes(b"existing")
    assert persist_tokenstore_if_changed(token_path, content, encrypted, fernet_key) is False
    assert encrypted.read_bytes() == b"existing"


def test_wrong_key_fails_without_plaintext_output(tmp_path, fernet_key):
    encrypted = tmp_path / "garmin_tokens.enc"
    encrypted.write_bytes(Fernet(fernet_key.encode()).encrypt(VALID_TOKEN.encode()))
    output_dir = tmp_path / "plain"
    with pytest.raises(InvalidToken):
        decrypt_tokenstore(encrypted, output_dir, Fernet.generate_key().decode())
    assert not (output_dir / "garmin_tokens.json").exists()


def test_missing_refresh_token_is_rejected(tmp_path, fernet_key):
    token_path = tmp_path / "garmin_tokens.json"
    token_path.write_text(json.dumps({"di_token": "a", "di_client_id": "c"}))
    with pytest.raises(ValueError, match="di_refresh_token"):
        persist_tokenstore_if_changed(token_path, VALID_TOKEN, tmp_path / "out.enc", fernet_key)


def test_remove_plaintext_is_idempotent(tmp_path):
    token_path = tmp_path / "garmin_tokens.json"
    token_path.write_text("secret")
    remove_plaintext_token(token_path)
    remove_plaintext_token(token_path)
    assert not token_path.exists()
```

- [ ] **Step 5: 实现 CLI 并验证往返**

Run: `pytest tests/test_garmin_tokens.py -v`

Expected: PASS。

Run: `python -m py_compile garmin_tokens.py`

Expected: exit 0。

- [ ] **Step 6: 提交 token 持久化模块**

```bash
git add garmin_tokens.py tests/test_garmin_tokens.py requirements.txt
git commit -m "feat: 加密持久化佳明令牌" -m "- 支持刷新令牌轮换\n- 仅在变化时更新密文\n- 校验并清理明文"
```

### Task 4: 用 Garmin 增量同步替换 Strava API

**Files:**
- Modify: `sync.py`
- Create: `tests/test_sync.py`

**Interfaces:**
- Consumes: `merge_records`、`write_json_atomic`
- Consumes: `decrypt_tokenstore`、`persist_tokenstore_if_changed`、`remove_plaintext_token`
- Produces: `parse_garmin_activity(activity: dict) -> dict`
- Produces: `fetch_garmin_activities(client, start_date: date, end_date: date) -> list[dict]`
- Produces: `update_garmin_records(existing: list[dict], fetched: list[dict], cutoff_utc: datetime) -> list[dict]`
- Produces: `run_sync(paths: SyncPaths, token_key: str, client_factory=Garmin) -> list[dict]`

- [ ] **Step 1: 写真实字段映射和骑行父类型测试**

```python
GARMIN_RUN = {
    "activityId": 24216312645,
    "activityName": "跑步",
    "activityType": {"typeId": 1, "typeKey": "running", "parentTypeId": 17},
    "startTimeGMT": "2026-09-02 22:14:05",
    "startTimeLocal": "2026-09-03 06:14:05",
    "distance": 705.030029296875,
    "duration": 543.4320068359375,
    "movingDuration": 536.0,
    "elapsedDuration": 543.4320068359375,
    "averageSpeed": 1.2970000505447388,
    "averageHR": 98.0,
    "startLatitude": 31.862460281699896,
    "startLongitude": 118.8369410019368,
}


def test_parse_garmin_activity_maps_existing_schema():
    row = parse_garmin_activity(GARMIN_RUN)
    assert row["run_id"] == 24216312645
    assert row["type"] == "running"
    assert row["pace"] == "12:40"
    assert row["source"] == "garmin"


def test_fetch_excludes_activity_with_cycling_parent(fake_client):
    fake_client.activities.append({
        **GARMIN_RUN,
        "activityId": 99,
        "activityType": {"typeId": 10, "typeKey": "road_biking", "parentTypeId": 2},
    })
    assert [r["run_id"] for r in fetch_garmin_activities(fake_client, START, END)] == [24216312645]
```

- [ ] **Step 2: 运行测试并确认旧同步器无法满足接口**

Run: `pytest tests/test_sync.py -v`

Expected: FAIL because Garmin functions do not exist and old module imports `stravalib`。

- [ ] **Step 3: 移除 Strava API 并实现 Garmin 映射**

删除 `CLIENT_ID`、`CLIENT_SECRET`、`REFRESH_TOKEN`、`strava_client`、`check_access`、`fetch_strava_activities`。不得在日志或异常中输出 Garmin 原始响应。

- [ ] **Step 4: 写边界回看与幂等测试**

```python
def test_update_rejects_cutoff_and_accepts_later_activity():
    fetched = [AT_CUTOFF, AFTER_CUTOFF]
    result = update_garmin_records([], fetched, CUTOFF)
    assert [r["run_id"] for r in result] == [AFTER_CUTOFF["run_id"]]


def test_update_replaces_same_garmin_id_without_duplicate():
    old = [{**AFTER_CUTOFF, "distance": 999.0}]
    result = update_garmin_records(old, [AFTER_CUTOFF], CUTOFF)
    assert len(result) == 1
    assert result[0]["distance"] == AFTER_CUTOFF["distance"]
```

- [ ] **Step 5: 实现查询日期与增量更新**

首次起点取 Strava 截止本地日期减一天；后续起点取 Garmin 最新本地日期减一天；终点取当前本地日期。调用 `get_activities_by_date(start, end, sortorder="asc")`，不传单一活动类型，以便保留除骑行外的全部活动。

- [ ] **Step 6: 写接口失败不清空旧数据测试**

```python
def test_fetch_failure_keeps_existing_garmin_file(tmp_paths, failing_client):
    original = tmp_paths.garmin.read_text()
    with pytest.raises(GarminConnectConnectionError):
        run_sync(tmp_paths, KEY, client_factory=lambda: failing_client)
    assert tmp_paths.garmin.read_text() == original
```

- [ ] **Step 7: 实现同步编排与 token 的 finally 持久化**

`run_sync` 必须先成功解密并登录，再拉取和解析全部页面；只有成功完成后才原子替换 Garmin JSON、combined JSON 和 CSV。外层 `finally` 始终调用 token 变化检测、重新加密和明文清理。若 token 持久化失败，保留原异常作为上下文并让进程非零退出。

- [ ] **Step 8: 运行同步测试**

Run: `pytest tests/test_sync.py tests/test_activity_records.py tests/test_garmin_tokens.py -v`

Expected: PASS。

- [ ] **Step 9: 提交 Garmin 同步器**

```bash
git add sync.py tests/test_sync.py
git commit -m "feat: 切换佳明增量同步" -m "- 映射真实活动字段\n- 实现边界回看更新\n- 失败时保护旧数据"
```

### Task 5: 生成并核验真实历史快照

**Files:**
- Create: `data/running_records_strava_export.json`
- Create: `data/running_records_garmin_sync.json`
- Modify: `data/running_records_combined.json`
- Modify: `data/running.csv`

**Interfaces:**
- Consumes CLI: `python import_strava_export.py EXPORT_DIR --output PATH`
- Consumes CLI: `python sync.py`
- Produces: 可提交的三源数据基线。

- [ ] **Step 1: 备份当前未提交数据差异用于核对**

Run: `git diff -- data/running_records_strava_sync.json data/running_records_combined.json data/running.csv > /tmp/running-pre-migration.diff`

Expected: 命令成功，且不修改工作区。

- [ ] **Step 2: 对完整 Strava 导出运行导入器**

Run: `python import_strava_export.py /Users/wanshuo/Downloads/export_71335350`

Expected: 输出快照，日志显示原始 726 条活动、排除 20 条骑行，并报告最终非骑行记录数；单个坏轨迹只产生警告。

- [ ] **Step 3: 核对截止时间和类型分布**

Run:

```bash
python - <<'PY'
import json
from collections import Counter
p = json.load(open("data/running_records_strava_export.json"))
print(len(p["records"]))
print(Counter(r["type"] for r in p["records"]))
print(p["last_activity_start_utc"])
print(p["last_activity_start_local"])
PY
```

Expected:

```text
706
Counter({'Run': 699, 'Walk': 6, 'Hike': 1})
2026-09-02 22:14:05
2026-09-03 06:14:05
```

- [ ] **Step 4: 初始化空 Garmin 增量状态并执行首次真实同步**

使用临时 tokenstore 和本地环境中的加密密钥运行 `python sync.py`。当前日期若仍为 `2026-09-03`，边界后可能没有新活动；这是合法结果。日志必须显示查询区间、过滤数量和最终记录数量，不显示 token。

- [ ] **Step 5: 连续运行两次验证幂等**

Run: `shasum data/running_records_garmin_sync.json data/running_records_combined.json data/running.csv`

再次运行同步后重复 `shasum`。Expected: 没有新 Garmin 活动时三份数据摘要不变；有新活动时只新增或覆盖对应活动，记录 ID 不重复。

- [ ] **Step 6: 提交迁移后的数据基线**

```bash
git add data/running_records_strava_export.json data/running_records_garmin_sync.json data/running_records_combined.json data/running.csv
git commit -m "data: 建立三源活动基线" -m "- 导入官网历史快照\n- 记录佳明增量状态\n- 重建合并与图表数据"
```

### Task 6: 初始化加密 token 并改造 GitHub Actions

**Files:**
- Create: `data/garmin_tokens.enc`
- Modify: `.github/workflows/sync_render.yml`
- Create: `tests/test_workflow.py`

**Interfaces:**
- Consumes CLI: `python garmin_tokens.py encrypt --input PATH --output PATH`
- Consumes Secret: `GARMIN_TOKEN_KEY`
- Produces: 可每日运行且能提交轮换 token 的工作流。

- [ ] **Step 1: 写工作流结构失败测试**

```python
def test_workflow_has_safe_garmin_token_lifecycle():
    workflow = Path(".github/workflows/sync_render.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "contents: write" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "GARMIN_TOKEN_KEY" in workflow
    assert "if: always()" in workflow
    assert "STRAVA_CLIENT_SECRET" not in workflow
    assert "git commit -a" not in workflow
```

- [ ] **Step 2: 运行测试并确认旧工作流失败**

Run: `pytest tests/test_workflow.py -v`

Expected: FAIL on missing Garmin lifecycle fields。

- [ ] **Step 3: 生成固定 Fernet 密钥并设置仓库 Secret**

在不回显密钥的安全终端变量中生成 Fernet key，通过 `gh secret set GARMIN_TOKEN_KEY` 写入当前 GitHub 仓库。用同一变量加密最新 `/Users/wanshuo/.garminconnect/137852926/garmin_tokens.json` 到 `data/garmin_tokens.enc`。确认 `git diff` 只显示密文文件，且仓库搜索不到 `di_refresh_token`。

- [ ] **Step 4: 改造工作流权限、触发器和并发锁**

工作流顶层加入：

```yaml
on:
  push:
    branches: [main]
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: running-sync-${{ github.ref }}
  cancel-in-progress: false
```

更新 Python 为 3.11 当前稳定补丁版本；安装依赖后执行同步和渲染。同步步骤从 Secret 读取密钥，但不回显。

- [ ] **Step 5: 实现失败后仍提交 token 的窄范围提交步骤**

提交步骤必须使用 `if: always()`，先检查 `data/garmin_tokens.enc` 是否变化；再明确暂存 `data/running_records_garmin_sync.json`、`data/running_records_combined.json`、`data/running.csv`、`running.svg` 和 `data/garmin_tokens.enc`。如果前序同步失败但 token 已轮换，仍提交密文后让任务保持失败状态。

- [ ] **Step 6: 运行工作流与安全测试**

Run: `pytest tests/test_workflow.py tests/test_garmin_tokens.py -v`

Expected: PASS。

Run: `rg -n 'di_refresh_token|di_token|STRAVA_CLIENT_SECRET|STRAVA_REFRESH_TOKEN' --glob '!tests/**' --glob '!docs/**' .`

Expected: 业务代码只出现 token JSON 字段名，不出现任何真实 token 或 Strava Secret 配置。

- [ ] **Step 7: 提交加密状态与工作流**

```bash
git add data/garmin_tokens.enc .github/workflows/sync_render.yml tests/test_workflow.py
git commit -m "ci: 持久化轮换后的令牌" -m "- 增加并发同步保护\n- 限制仓库写入权限\n- 失败时保存最新密文"
```

### Task 7: 更新文档并完成全链路验证

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `running.svg`
- Modify: `.ai-history/2026-09-03_strava-garmin-data-source-design.md`

**Interfaces:**
- Consumes: 所有前序 CLI 和数据文件。
- Produces: 用户可操作的部署说明与最终验证证据。

- [ ] **Step 1: 更新 README 操作手册**

必须包含：三类数据源说明、一次性 Strava 导入命令、`GARMIN_TOKEN_KEY` 初始化、加密 token 重置流程、本地同步与渲染命令、GitHub 手动触发方式、refresh token 轮换说明，以及认证失效时的人工恢复步骤。

- [ ] **Step 2: 更新项目开发说明**

从 `CLAUDE.md` 删除 Strava API 和三个 Strava Secret，补充 Garmin 增量架构、测试不访问网络、真实同步需要 token 解密密钥，以及不得用空数据覆盖已有状态。

- [ ] **Step 3: 运行完整自动测试**

Run: `pytest -v`

Expected: 全部 PASS，测试期间没有 Garmin 网络请求。

- [ ] **Step 4: 生成并检查最终 SVG**

Run: `python render.py`

Expected: exit 0，`running.svg` 非空，终端报告有效地图点数量。

Run: `python - <<'PY'
from pathlib import Path
p = Path("running.svg")
assert p.stat().st_size > 10_000
assert "<svg" in p.read_text(encoding="utf-8")[:1000]
PY`

Expected: exit 0。

- [ ] **Step 5: 检查敏感信息与工作区边界**

Run: `git diff --check`

Expected: exit 0。

Run: `git status --short`

Expected: 只出现本计划产生的文件以及任务开始前已记录的用户修改；逐一核对，不暂存无关文件。

- [ ] **Step 6: 手动触发 GitHub Actions 验收**

推送实现提交后，从 Actions 页面运行 `workflow_dispatch`。验收日志必须显示 Garmin 登录成功、增量查询完成、三源合并完成、SVG 生成完成，以及在 token 变化时密文提交成功。随后再次手动运行，确认无新活动时不产生重复数据。

- [ ] **Step 7: 归档验证结果并提交文档**

将实际测试数量、Strava 导入数量、Garmin 边界结果和 Action 运行链接追加到 `.ai-history/2026-09-03_strava-garmin-data-source-design.md`。

```bash
git add README.md CLAUDE.md running.svg .ai-history/2026-09-03_strava-garmin-data-source-design.md
git commit -m "docs: 完善同步运维说明" -m "- 记录密钥初始化流程\n- 补充令牌失效恢复\n- 归档全链路验收"
```

### Task 8: 最终回归与交付检查

**Files:**
- Verify only: all files from Tasks 1-7

**Interfaces:**
- Consumes: 完整实现。
- Produces: 可交付结论，不产生额外代码。

- [ ] **Step 1: 运行完整回归**

Run: `pytest -v && python render.py`

Expected: 全部测试通过且 SVG 生成成功。

- [ ] **Step 2: 检查数据不变量**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

strava = json.loads(Path("data/running_records_strava_export.json").read_text())
garmin = json.loads(Path("data/running_records_garmin_sync.json").read_text())
combined = json.loads(Path("data/running_records_combined.json").read_text())

assert strava["last_activity_start_utc"] == "2026-09-02 22:14:05"
assert all(r.get("type") not in {"Ride", "骑行"} for r in combined["records"])
assert len({r["run_id"] for r in garmin["records"]}) == len(garmin["records"])
assert len(combined["records"]) >= len(strava["records"])
print(len(strava["records"]), len(garmin["records"]), len(combined["records"]))
PY
```

Expected: assertions pass，并输出三个来源的最终数量。

- [ ] **Step 3: 检查提交范围和敏感信息**

Run: `git status --short && git log --oneline -8`

Expected: 没有遗漏的实现文件；用户原有未提交修改仍被保留或已在明确核对后迁移。

Run: `git grep -n 'f06514c9a9b0b79bd05f2589bf1ba260b3dcbd82\|82b6034b24ae98ca4b704e6398fe1dcb3ce8579b' -- . ':!docs/**' || true`

Expected: 无输出；旧硬编码 Strava 凭证已从业务代码移除。

- [ ] **Step 4: 处理最终检查结果**

若最终检查发现问题，返回产生该文件的任务，补充对应失败测试、完成修正、重跑该任务验证，并使用该任务列出的明确文件清单提交。若没有问题，不创建空提交。
