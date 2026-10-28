"""Window lookup, focus verification and input helpers for Niri."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Iterable


CONFIG_PATH = Path(
    os.environ.get(
        "SETUP_INSTANCES_CONFIG",
        Path.home() / ".config/setup-instances/instances.json",
    )
)
try:
    CONFIG = json.loads(CONFIG_PATH.read_text())
except (OSError, ValueError) as exc:
    raise RuntimeError(f"invalid local configuration: {CONFIG_PATH}") from exc

TARGETS = {item["title"]: item for item in CONFIG["targets"]}
TITLES = tuple(TARGETS)
GRID_COLUMNS = CONFIG["columns"]
GRID_ORDER = tuple(title for column in GRID_COLUMNS for title in column)
if len(TARGETS) != len(CONFIG["targets"]) or len(GRID_ORDER) != len(TITLES) or set(GRID_ORDER) != set(TITLES):
    raise ValueError("targets and columns must contain each title exactly once")
TITLE_RE = re.compile(r"^(?:" + "|".join(re.escape(title) for title in TITLES) + r")$")
APP_ID = CONFIG["app_id"]

KEY_E = int(CONFIG["keys"]["inspect"])
KEY_ESC = int(CONFIG["keys"]["resume"])
KEY_K = int(CONFIG["keys"]["activate"])
KEY_P = int(CONFIG["keys"]["mode"])
KEY_UP = int(CONFIG["keys"]["recall"])


def target_action(title: str) -> str:
    validate_title(title)
    return str(TARGETS[title]["final"])


class ScriptError(RuntimeError):
    pass


def _run(args: list[str], *, json_output: bool = False) -> Any:
    try:
        result = subprocess.run(
            args,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise ScriptError(f"comando não encontrado: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScriptError(f"timeout executando: {' '.join(args)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "erro desconhecido").strip()
        raise ScriptError(f"falhou: {' '.join(args)}: {detail}") from exc

    if not json_output:
        return result.stdout.strip()
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ScriptError(f"JSON inválido de {' '.join(args)}") from exc


def niri_json(command: str) -> Any:
    return _run(["niri", "msg", "--json", command], json_output=True)


def niri_action(action: str, *args: object) -> None:
    _run(["niri", "msg", "action", action, *(str(arg) for arg in args)])


def validate_title(title: str) -> None:
    if not TITLE_RE.fullmatch(title) or title not in TITLES:
        raise ScriptError(f"título não permitido: {title!r}")


def all_windows() -> list[dict[str, Any]]:
    data = niri_json("windows")
    if not isinstance(data, list):
        raise ScriptError("resposta inesperada de niri msg --json windows")
    return data


def target_windows(windows: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    source = all_windows() if windows is None else windows
    return [
        window
        for window in source
        if window.get("title") in TITLES
        and TITLE_RE.fullmatch(str(window.get("title", "")))
        and window.get("app_id") == APP_ID
    ]


def unit_window(title: str) -> dict[str, Any]:
    validate_title(title)
    title_matches = [window for window in all_windows() if window.get("title") == title]
    if not title_matches:
        raise ScriptError(f"janela {title!r} não encontrada")
    if len(title_matches) != 1:
        raise ScriptError(f"há {len(title_matches)} janelas com o título {title!r}; operação recusada")
    window = title_matches[0]
    if window.get("app_id") != APP_ID:
        raise ScriptError(
            f"app_id inesperado para {title!r}: {window.get('app_id')!r}; operação recusada"
        )
    return window


def unit_window_id(title: str) -> int:
    window_id = unit_window(title).get("id")
    if not isinstance(window_id, int):
        raise ScriptError(f"ID inválido para {title!r}")
    return window_id


def focused_window() -> dict[str, Any] | None:
    data = niri_json("focused-window")
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ScriptError("resposta inesperada de niri msg --json focused-window")
    return data


def assert_focused(title: str, expected_id: int) -> None:
    current = focused_window()
    if not current:
        raise ScriptError("nenhuma janela está focada")
    if (
        current.get("id") != expected_id
        or current.get("title") != title
        or current.get("app_id") != APP_ID
    ):
        raise ScriptError(
            f"foco não confirmado em {title!r} (janela atual: {current.get('title')!r})"
        )
    workspace_id = current.get("workspace_id")
    workspaces = niri_json("workspaces")
    workspace = next((item for item in workspaces if item.get("id") == workspace_id), None)
    if not workspace or not workspace.get("is_focused") or not workspace.get("is_active"):
        raise ScriptError(f"workspace de {title!r} não está visível e focado")
    if workspace.get("active_window_id") != expected_id:
        raise ScriptError(f"{title!r} não é a janela ativa do workspace")


def unit_focus(title: str, timeout: float = 1.0) -> int:
    window = unit_window(title)
    window_id = window.get("id")
    if not isinstance(window_id, int):
        raise ScriptError(f"ID inválido para {title!r}")
    workspace = next(
        (
            item
            for item in niri_json("workspaces")
            if item.get("id") == window.get("workspace_id")
        ),
        None,
    )
    if not workspace:
        raise ScriptError(f"workspace de {title!r} não encontrado")
    workspace_ref = workspace.get("name") or workspace.get("idx")
    if workspace_ref is None:
        raise ScriptError(f"workspace de {title!r} não possui referência utilizável")
    if not workspace.get("is_focused") or not workspace.get("is_active"):
        niri_action("focus-workspace", workspace_ref)
    niri_action("focus-window", "--id", window_id)
    deadline = time.monotonic() + timeout
    while True:
        try:
            assert_focused(title, window_id)
            return window_id
        except ScriptError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _ydotool(args: list[str]) -> None:
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    socket_path = Path(os.environ.get("YDOTOOL_SOCKET", f"{runtime}/.ydotool_socket"))
    if not socket_path.exists():
        raise ScriptError(f"socket do ydotool não existe: {socket_path}")
    if not Path("/dev/uinput").exists():
        raise ScriptError("/dev/uinput não existe; carregue o módulo uinput")
    env = os.environ.copy()
    env["YDOTOOL_SOCKET"] = str(socket_path)
    try:
        subprocess.run(
            ["ydotool", *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ScriptError(f"ydotool falhou: {str(detail).strip()}") from exc


def unit_key(title: str, keycode: int, key_delay_ms: int | None = None) -> None:
    if not isinstance(keycode, int) or not 1 <= keycode <= 767:
        raise ScriptError(f"keycode inválido: {keycode!r}")
    if key_delay_ms is not None and not 1 <= key_delay_ms <= 1000:
        raise ScriptError(f"duração de tecla inválida: {key_delay_ms!r} ms")
    window_id = unit_focus(title)
    assert_focused(title, window_id)
    args = ["key"]
    if key_delay_ms is not None:
        args.extend(["--key-delay", str(key_delay_ms)])
    args.extend([f"{keycode}:1", f"{keycode}:0"])
    _ydotool(args)


def unit_pointer_center(title: str) -> None:
    unit_click(title, click=False)


def unit_click(
    title: str,
    button: str = "left",
    offset_x: int = 0,
    offset_y: int = 0,
    repeat: int = 1,
    recenter: bool = True,
    *,
    click: bool = True,
) -> None:
    from x11_pointer import X11Pointer, aim

    if button not in {"left", "right"} or not 1 <= repeat <= 3:
        raise ScriptError("botão ou repetição inválidos")
    window_id = unit_focus(title)
    settle = float(os.environ.get("SETUP_INSTANCES_WAIT_POINTER_WARP", "0.30"))
    if not 0 <= settle <= 2:
        raise ScriptError("espera do ponteiro fora do intervalo 0..2")
    time.sleep(settle)
    try:
        with X11Pointer(title) as pointer:
            if recenter or offset_x or offset_y:
                if recenter:
                    x, y = pointer.width // 2, pointer.height // 2
                else:
                    x, y = pointer.position()
                aim(pointer, (x + offset_x, y + offset_y),
                    lambda dx, dy: _ydotool(["mousemove", "--", str(dx), str(dy)]),
                    time.sleep, lambda: assert_focused(title, window_id))
            x, y = pointer.position()
            if not (0 <= x < pointer.width and 0 <= y < pointer.height):
                raise ScriptError("cursor fora da janela; clique cancelado")
            assert_focused(title, window_id)
            if click:
                args = ["click"]
                if repeat > 1:
                    args.extend(["--repeat", str(repeat), "--next-delay", "100"])
                _ydotool(args + [{"left": "0xC0", "right": "0xC1"}[button]])
    except (RuntimeError, OSError) as exc:
        raise ScriptError(str(exc)) from exc


def unit_left_click(
    title: str,
    offset_x: int = 0,
    offset_y: int = 0,
    *,
    recenter: bool = True,
) -> None:
    unit_click(title, "left", offset_x, offset_y, recenter=recenter)


def unit_right_click(title: str, *, recenter: bool = True) -> None:
    unit_click(title, "right", recenter=recenter)


def unit_double_click(
    title: str,
    offset_x: int = 0,
    offset_y: int = 0,
    *,
    recenter: bool = True,
) -> None:
    unit_click(title, "left", offset_x, offset_y, repeat=2, recenter=recenter)


def focused_action(title: str, action: str, *args: object) -> None:
    window_id = unit_focus(title)
    assert_focused(title, window_id)
    niri_action(action, *args)


def snapshot(label: str) -> Path:
    state_dir = Path(
        os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))
    ) / "setup-instances"
    state_dir.mkdir(parents=True, exist_ok=True)
    # Keep one current snapshot per label instead of accumulating a file on
    # every grid run. Remove files created by the older timestamped scheme.
    for legacy in state_dir.glob(f"{label}-*.json"):
        legacy.unlink()
    target = state_dir / f"{label}.json"
    payload = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "windows": all_windows(),
        "workspaces": niri_json("workspaces"),
        "outputs": niri_json("outputs"),
    }
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(target)
    return target
