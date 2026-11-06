"""Sync playlist maps between local YAML files and a Buildin database.

Buildin is the source of truth when ``import`` is used: the dedicated
``Music Library`` page holds a ``Playlists`` database where every record is one
playlist (platform, external id, artists). ``export`` seeds/updates that
database from the local files, which is needed to bootstrap the page.

Records are matched by ``(Platform, Title)``. Buildin has no record-deletion
MCP tool, so playlists removed locally stay in Buildin (export reports them as
orphaned) and are re-created on the next import until they are deleted in the
Buildin UI.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from . import paths
from .buildin import BuildinClient

PAGE_TITLE = "Music Library"
DATABASE_TITLE = "Playlists"
PLATFORM_YOUTUBE = "YouTube"
PLATFORM_YANDEX = "Yandex"
PROP_PLATFORM = "Platform"
PROP_EXTERNAL_ID = "External ID"
PROP_ARTISTS = "Artists"
BATCH_SIZE = 50
PAGE_MARKDOWN = (
    "Playlist maps mirrored from the Music CLI.\n\n"
    "Every record in the **Playlists** database below is one playlist. "
    "Platform is `YouTube` or `Yandex`, External ID is the YouTube playlist id "
    "or the Yandex playlist kind, and Artists is one artist name per line.\n\n"
    "Edit a record here, then run *Import playlist maps from Buildin* in the "
    "Music CLI to regenerate `data/playlists_map.yaml` and `data/yamusic.yaml`."
)


class MapSyncError(RuntimeError):
    """Raised when a Buildin playlist-map operation fails."""


# ===== Public API =====


def export_maps(client: BuildinClient) -> Dict[str, Any]:
    """Create/update the Buildin database from the local YAML maps."""
    youtube, yandex = load_local_maps()
    state = ensure_resources(client)
    records = query_all(client, state["database_id"])

    existing: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for record in records:
        platform, title = _record_key(record)
        existing[(platform, title)] = record

    desired = _desired_records(youtube, yandex)
    creates: List[Dict[str, Any]] = []
    updates: List[Dict[str, Any]] = []
    unchanged = 0

    for item in desired:
        record = existing.get((item["platform"], item["title"]))
        if record is None:
            creates.append({"title": item["title"], "properties": _record_properties(item)})
            continue
        if _record_signature(record) == (item["external"], item["artists"]):
            unchanged += 1
        else:
            updates.append(
                {"record_id": _record_id(record), "properties": _record_properties(item)}
            )

    for start in range(0, max(len(creates), len(updates), 1), BATCH_SIZE):
        body: Dict[str, Any] = {}
        create_batch = creates[start:start + BATCH_SIZE]
        update_batch = updates[start:start + BATCH_SIZE]
        if create_batch:
            body["create_records"] = create_batch
        if update_batch:
            body["update_records"] = update_batch
        if not body:
            continue
        _call(
            client,
            "buildin_mutate_database",
            {
                "database_id": state["database_id"],
                "body": body,
                "idempotency_key": _batch_key(state["database_id"], body),
            },
        )

    wanted = {(item["platform"], item["title"]) for item in desired}
    orphaned = sorted(set(existing) - wanted)
    return {
        "page_id": state["page_id"],
        "database_id": state["database_id"],
        "created": len(creates),
        "updated": len(updates),
        "unchanged": unchanged,
        "total": len(desired),
        "orphaned": orphaned,
    }


def import_maps(client: BuildinClient) -> Dict[str, Any]:
    """Read the Buildin database and return the two playlist maps (no writes)."""
    state = ensure_resources(client)
    records = query_all(client, state["database_id"])
    if not records:
        raise MapSyncError(
            f"The Buildin database '{DATABASE_TITLE}' is empty; run "
            "'Export playlist maps to Buildin' first or add records in Buildin."
        )

    youtube, yandex = _records_to_maps(records)
    local_youtube, local_yandex = load_local_maps()

    return {
        "page_id": state["page_id"],
        "database_id": state["database_id"],
        "records": len(records),
        "youtube": youtube,
        "yandex": yandex,
        "youtube_diff": _diff(local_youtube, youtube),
        "yandex_diff": _diff(local_yandex, yandex),
    }


def write_imported_maps(result: Dict[str, Any]) -> List[str]:
    """Write the imported maps, keeping a platform file when Buildin has no rows for it."""
    written = []
    if result["youtube"]:
        _write_yaml(paths.PLAYLISTS_MAP_FILE, result["youtube"])
        written.append(str(paths.PLAYLISTS_MAP_FILE))
    if result["yandex"]:
        _write_yaml(paths.YAMUSIC_MAP_FILE, result["yandex"])
        written.append(str(paths.YAMUSIC_MAP_FILE))
    return written


def load_local_maps() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return (
        _load_yaml(paths.PLAYLISTS_MAP_FILE),
        _load_yaml(paths.YAMUSIC_MAP_FILE),
    )


def ensure_resources(client: BuildinClient) -> Dict[str, str]:
    """Find or create the dedicated page and database; IDs are cached locally."""
    state = _load_state()
    page_id = state.get("page_id")
    if not page_id or not _page_exists(client, page_id):
        page_id = _find_page(client) or _create_page(client)
        state = {"page_id": page_id}
        _save_state(state)

    database_id = state.get("database_id")
    if not database_id or not _database_exists(client, database_id):
        database_id = _find_database(client, page_id) or _create_database(client, page_id)
        state["database_id"] = database_id
        _save_state(state)

    return state


def query_all(client: BuildinClient, database_id: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        arguments: Dict[str, Any] = {"database_id": database_id, "page_size": 100}
        if cursor:
            arguments["start_cursor"] = cursor
        data = _call(client, "buildin_query_database", arguments)
        records.extend(data.get("results") or [])
        cursor = data.get("next_cursor")
        if not cursor:
            return records


# ===== Record conversion =====


def _desired_records(
    youtube: Dict[str, Any], yandex: Dict[str, Any]
) -> List[Dict[str, Any]]:
    desired = []
    for title, info in youtube.items():
        desired.append(
            {
                "platform": PLATFORM_YOUTUBE,
                "title": str(title),
                "external": str(info.get("id", "")).strip(),
                "artists": _clean_artists(info.get("artists") or []),
            }
        )
    for title, info in yandex.items():
        desired.append(
            {
                "platform": PLATFORM_YANDEX,
                "title": str(title),
                "external": str(info.get("kind", "")).strip(),
                "artists": _clean_artists(info.get("artists") or []),
            }
        )
    for item in desired:
        if not item["external"]:
            raise MapSyncError(
                f"Playlist '{item['title']}' has no "
                f"{'id' if item['platform'] == PLATFORM_YOUTUBE else 'kind'}."
            )
    return desired


def _record_properties(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        PROP_PLATFORM: {"type": "select", "select": {"name": item["platform"]}},
        PROP_EXTERNAL_ID: _rich_text_property(item["external"]),
        PROP_ARTISTS: _rich_text_property("\n".join(item["artists"])),
    }


def _records_to_maps(
    records: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    youtube: Dict[str, Any] = {}
    yandex: Dict[str, Any] = {}

    for record in records:
        properties = record.get("properties") or {}
        title = _title_plain(properties).replace(":", " -").strip()
        if not title:
            raise MapSyncError(f"Buildin record {_record_id(record)} has no title.")

        platform = (_select_name(properties) or "").strip()
        external = _text_property(properties, PROP_EXTERNAL_ID).strip()
        artists = _parse_artists(_text_property(properties, PROP_ARTISTS))
        if not external:
            raise MapSyncError(f"Playlist '{title}' has no {PROP_EXTERNAL_ID}.")

        if platform.lower() == PLATFORM_YOUTUBE.lower():
            if title in youtube:
                raise MapSyncError(f"Duplicate YouTube playlist title: {title}")
            youtube[title] = {"id": external, "artists": artists}
        elif platform.lower() == PLATFORM_YANDEX.lower():
            try:
                kind = int(external)
            except ValueError as e:
                raise MapSyncError(
                    f"Yandex playlist '{title}' has a non-numeric {PROP_EXTERNAL_ID}: {external}"
                ) from e
            if title in yandex:
                raise MapSyncError(f"Duplicate Yandex playlist title: {title}")
            yandex[title] = {"kind": kind, "artists": artists}
        else:
            raise MapSyncError(
                f"Playlist '{title}' has unknown {PROP_PLATFORM}: {platform!r} "
                f"(expected {PLATFORM_YOUTUBE} or {PLATFORM_YANDEX})."
            )

    return youtube, yandex


def _record_key(record: Dict[str, Any]) -> Tuple[str, str]:
    properties = record.get("properties") or {}
    platform = (_select_name(properties) or "").strip()
    title = _title_plain(properties).replace(":", " -").strip()
    return platform, title


def _record_signature(record: Dict[str, Any]) -> Tuple[str, List[str]]:
    properties = record.get("properties") or {}
    external = _text_property(properties, PROP_EXTERNAL_ID).strip()
    artists = _parse_artists(_text_property(properties, PROP_ARTISTS))
    return external, artists


def _record_id(record: Dict[str, Any]) -> str:
    record_id = record.get("id") or record.get("page_id")
    if not record_id:
        raise MapSyncError(f"Buildin record without an id: {record}")
    return str(record_id)


def _title_plain(properties: Dict[str, Any]) -> str:
    value = None
    for candidate in properties.values():
        if isinstance(candidate, dict) and candidate.get("type") == "title":
            value = candidate
            break
    if value is None:
        return ""
    return "".join(
        item.get("plain_text") or (item.get("text") or {}).get("content") or ""
        for item in value.get("title") or []
        if isinstance(item, dict)
    )


def _select_name(properties: Dict[str, Any]) -> Optional[str]:
    value = properties.get(PROP_PLATFORM)
    if not isinstance(value, dict):
        value = next(
            (
                candidate
                for candidate in properties.values()
                if isinstance(candidate, dict) and candidate.get("type") in ("select", "multi_select")
            ),
            None,
        )
    if not isinstance(value, dict):
        return None
    if value.get("type") == "multi_select":
        options = value.get("multi_select") or []
        if options and isinstance(options[0], dict):
            return options[0].get("name")
        return None
    select = value.get("select")
    if isinstance(select, dict):
        return select.get("name")
    return None


def _text_property(properties: Dict[str, Any], name: str) -> str:
    value = properties.get(name)
    if not isinstance(value, dict):
        raise MapSyncError(
            f"Buildin database is missing the '{name}' property (or it was renamed)."
        )
    value_type = value.get("type")
    if value_type == "rich_text":
        return "".join(
            item.get("plain_text") or (item.get("text") or {}).get("content") or ""
            for item in value.get("rich_text") or []
            if isinstance(item, dict)
        )
    if value_type == "title":
        return "".join(
            item.get("plain_text") or (item.get("text") or {}).get("content") or ""
            for item in value.get("title") or []
            if isinstance(item, dict)
        )
    if value_type == "number":
        return "" if value.get("number") is None else str(value["number"])
    if value_type == "url":
        return value.get("url") or ""
    raise MapSyncError(
        f"Buildin property '{name}' has unsupported type {value_type!r} "
        "(expected rich_text)."
    )


def _parse_artists(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return _clean_artists(parsed)
    return _clean_artists(re.split(r"[\r\n;]+", raw))


def _clean_artists(values: Any) -> List[str]:
    artists = []
    for value in values:
        name = str(value).strip()
        if name and name not in artists:
            artists.append(name)
    return artists


def _rich_text_item(content: str) -> Dict[str, Any]:
    return {
        "type": "text",
        "text": {"content": content, "link": None},
        "plain_text": content,
        "href": None,
        "annotations": {
            "bold": False,
            "italic": False,
            "strikethrough": False,
            "underline": False,
            "code": False,
            "text_color": "default",
            "background_color": "default",
        },
    }


def _rich_text_property(content: str) -> Dict[str, Any]:
    return {"type": "rich_text", "rich_text": [_rich_text_item(content)]}


# ===== Buildin resources =====


def _find_page(client: BuildinClient) -> Optional[str]:
    directory = _call(client, "buildin_list_workspace_directory", {"page_size": 100})
    for section in ("favorites", "team", "shared", "private"):
        section_data = directory.get(section) or {}
        for node in section_data.get("results") or []:
            if node.get("object") == "page" and node.get("title") == PAGE_TITLE:
                return node.get("id")

    search = _call(client, "buildin_search_text", {"query": PAGE_TITLE, "page_size": 50})
    for node in search.get("results") or []:
        if node.get("title") == PAGE_TITLE and node.get("object") == "page":
            return node.get("id")
    return None


def _create_page(client: BuildinClient) -> str:
    body = {
        "properties": {"title": {"type": "title", "title": [_rich_text_item(PAGE_TITLE)]}},
        "markdown": PAGE_MARKDOWN,
    }
    data = _call(
        client,
        "buildin_create_page",
        {"body": body, "idempotency_key": "music-cli-library-page"},
    )
    page_id = data.get("id")
    if not page_id:
        raise MapSyncError(f"Could not read the new Buildin page id: {data}")
    return str(page_id)


def _find_database(client: BuildinClient, page_id: str) -> Optional[str]:
    try:
        children = _call(client, "buildin_list_pages", {"parent_id": page_id, "page_size": 100})
    except MapSyncError:
        children = {}
    for node in children.get("results") or []:
        if node.get("object") == "database" and node.get("title") == DATABASE_TITLE:
            return node.get("id")

    search = _call(client, "buildin_search_text", {"query": DATABASE_TITLE, "page_size": 50})
    for node in search.get("results") or []:
        parent = node.get("parent") or {}
        if (
            node.get("object") == "database"
            and node.get("title") == DATABASE_TITLE
            and (not parent or parent.get("page_id") == page_id)
        ):
            return node.get("id")
    return None


def _create_database(client: BuildinClient, page_id: str) -> str:
    body = {
        "parent": {"page_id": page_id},
        "title": [_rich_text_item(DATABASE_TITLE)],
        "properties": {
            "Title": {"type": "title"},
            PROP_PLATFORM: {
                "type": "select",
                "select": {
                    "options": [
                        {"name": PLATFORM_YOUTUBE},
                        {"name": PLATFORM_YANDEX},
                    ]
                },
            },
            PROP_EXTERNAL_ID: {"type": "rich_text"},
            PROP_ARTISTS: {"type": "rich_text"},
        },
    }
    data = _call(client, "buildin_create_database", {"body": body})
    database_id = data.get("id")
    if not database_id:
        raise MapSyncError(f"Could not read the new Buildin database id: {data}")
    return str(database_id)


def _page_exists(client: BuildinClient, page_id: str) -> bool:
    return _exists(lambda: _call(client, "buildin_get_page", {"page_id": page_id}))


def _database_exists(client: BuildinClient, database_id: str) -> bool:
    return _exists(lambda: _call(client, "buildin_get_database", {"database_id": database_id}))


def _exists(call) -> bool:
    try:
        call()
        return True
    except MapSyncError as e:
        message = str(e).lower()
        if "not found" in message or "404" in message:
            return False
        raise


# ===== Local files =====


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError as e:
        raise MapSyncError(f"Local map file not found: {path}") from e
    except yaml.YAMLError as e:
        raise MapSyncError(f"Could not parse {path}: {e}") from e


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    temp.replace(path)


def _diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    old_keys = set(old)
    new_keys = set(new)
    return {
        "added": sorted(new_keys - old_keys),
        "removed": sorted(old_keys - new_keys),
        "changed": sorted(key for key in old_keys & new_keys if old[key] != new[key]),
    }


# ===== State and helpers =====


def _load_state() -> Dict[str, str]:
    path = paths.BUILDIN_STATE_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: Dict[str, str]) -> None:
    path = paths.BUILDIN_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(path)


def _batch_key(database_id: str, body: Dict[str, Any]) -> str:
    digest = hashlib.sha256(
        (database_id + json.dumps(body, sort_keys=True)).encode("utf-8")
    ).hexdigest()
    return f"music-maps-{digest[:32]}"


def _call(client: BuildinClient, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    result = client.call_tool(tool, arguments)
    text = ""
    for item in result.get("content") or []:
        if item.get("type") == "text":
            text = item.get("text") or ""
            break

    if result.get("isError"):
        detail = text
        try:
            parsed = json.loads(text)
            detail = parsed.get("message") or parsed.get("error") or text
        except (json.JSONDecodeError, AttributeError):
            pass
        raise MapSyncError(f"{tool}: {str(detail)[:500]}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise MapSyncError(f"{tool}: expected JSON, got: {text[:200]}") from e
    if not isinstance(data, dict):
        raise MapSyncError(f"{tool}: expected a JSON object, got: {type(data).__name__}")
    return data
