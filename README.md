# niri-instance-scripts

Personal helpers for opening several application instances, sending a short
input sequence and arranging their windows into tiled columns on Niri.

I keep the commands separate so I can rerun one step or work on a single window.
The menu positions and key sequence are specific to my setup; adjust them before
running the full sequence on yours.

## Setup

Requires Python 3.10+, Niri, ydotool with its daemon running and access to
`/dev/uinput`. Pointer commands also need XWayland, `DISPLAY` and `libX11.so.6`.
Window lookup uses Niri IPC; measuring the pointer uses the focused X11 client,
so the click helpers currently work with XWayland windows only.

```sh
mkdir -p ~/.config/setup-instances
cp config.example.json ~/.config/setup-instances/instances.json
export PATH="$PWD/bin:$PATH"
```

Edit the copied JSON with your application's `app_id`, exact window titles,
instance directories and launch command. `launch` is an argument list, with
`{unit}`, `{profile}` and `{title}` substituted for each target. It runs directly,
without a shell. The example names and command are placeholders for local values.

Use `niri msg --json windows` to find titles and app IDs. Create the named
workspace in your Niri config. For pointer commands, enable this in your existing
`input` block so switching windows brings the cursor into the focused window:

```kdl
warp-mouse-to-focus
```

The scripts don't edit the compositor config. If the cursor is outside the client
area or focus can't be confirmed, the click is cancelled.

To use a different JSON file:

```sh
export SETUP_INSTANCES_CONFIG="$PWD/config.local.json"
```

## Commands

```sh
window-action list
window-action focus 01-alpha
launch-instances --only 01-alpha --dry-run
join-server --title 01-alpha --dry-run
configure-instances --title 01-alpha --dry-run
setup-instances --dry-run
```

`launch-instances` skips open targets and waits for the selected titles.
`join-server` clicks a menu and a saved entry, using offsets from the measured
client center. It expects 240×240 windows before the final layout.
`configure-instances` sends the resume/recall keys, opens a selector, selects an
item, then sends the mode key and each target's final action.

Test each step on one window first. `--dry-run` prints the planned actions without
launching processes or sending input; it doesn't verify the desktop state.

```sh
launch-instances --only 01-alpha
join-server --title 01-alpha
configure-instances --title 01-alpha
arrange-grid
```

For several targets, use `--all` or `--batch TITLE TITLE` with the join and
configure commands. Configuration runs one phase across the selected windows
before proceeding to the next. Each window keeps its own minimum wait between
selection, mode and final action.

`setup-instances` runs launch, menu selection, configuration and layout in that
order. It requires all targets to be closed initially, waits for every window
and then allows six seconds for the initial screen. Use `--main-menu-wait` to
adjust that delay.

## Local adjustments

`columns` lists titles left to right, with each column ordered top to bottom.
Each target appears once. `width` sets a uniform column width; heights are left
to Niri. The grid checks the resulting order and saves before/after snapshots
under `~/.local/state/setup-instances`, respecting `XDG_STATE_HOME`.

Key values are Linux input keycodes. `final` is `pointer` for a right click or
`key-inspect` for the activate key followed by the inspect key.

Menu offsets and delays can be overridden without editing the scripts:

```sh
export SETUP_INSTANCES_MENU_OFFSET_Y=22
export SETUP_INSTANCES_ITEM_OFFSET_Y=-94
export SETUP_INSTANCES_PANEL_OFFSET_Y=-50
export SETUP_INSTANCES_WAIT_MENU=1.5
export SETUP_INSTANCES_WAIT_GUI=0.8
export SETUP_INSTANCES_WAIT_STAGE=3
export SETUP_INSTANCES_WAIT_KEY=3
```

Offsets are client pixels from the center. Calibrate them before resizing into
the final columns. The pointer helper measures after each movement and cancels
if it can't reach the requested point.

Run the small regression suite with:

```sh
python3 -m unittest discover -s tests -v
```
