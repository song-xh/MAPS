"""Local interactive MAPS system demonstration."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from typing import Any

from dash import ALL, Dash, Input, Output, Patch, State, ctx, dcc, html, no_update

from maps_demo.engine import (
    POLICIES, STAGES, available_orders, clock_time, parse_clock, run_demo, source_options,
)
from maps_demo.figures import (
    color_for,
    flow_figure,
    map_dynamic_traces,
    map_figure,
    map_static_trace_count,
    minute_profit_figure,
    platform_profit_figure,
    profit_figure,
    status_figure,
)

REPLAY_PATH = Path("output/maps-demo/latest.json")
_ACTIVE_RUN: dict[str, Any] | None = None
_ACTIVE_RUN_ID = 0
_RUN_JOB: dict[str, Any] | None = None


def _cache_run(run: dict[str, Any]) -> dict[str, int]:
    global _ACTIVE_RUN, _ACTIVE_RUN_ID
    _ACTIVE_RUN_ID += 1
    _ACTIVE_RUN = run
    return {"id": _ACTIVE_RUN_ID}


def _get_run(reference: dict[str, int] | None) -> dict[str, Any] | None:
    return _ACTIVE_RUN if reference and reference.get("id") == _ACTIVE_RUN_ID else None


STAGE_LABELS = {
    "workload": ("01", "Workload", "Order arrivals"),
    "parcel": ("02", "Parcel", "Pool decisions"),
    "local": ("03", "Local decision", "Feasible matches"),
    "auction": ("04", "Auction", "Cross-platform bids"),
    "settlement": ("05", "Settlement", "Assignments & ledger"),
}
POLICY_LABELS = {
    "release-first": "Release all · demo rule",
    "local-first": "Local all · demo rule",
    "wait-first": "Wait all · demo rule",
    "localsum": "LocalSum",
    "rl-capa": "RL-CAPA baseline",
    "mra": "MRA",
    "impgta": "IMPGTA",
    "fed-ltd": "Fed-LTD",
}
STATUS_LABELS = {
    "future": "Not arrived", "waiting": "Pending", "public_this_step": "Released this frame",
    "cross_pool": "Cross-platform pool", "local_assigned": "Locally assigned",
    "cross_assigned": "Cross-platform assigned", "collected": "Collected",
    "unloaded": "Unloaded", "expired": "Expired",
}


def _field(label: str, control: Any, hint: str | None = None) -> html.Div:
    return html.Div(className="field", children=[
        html.Label(label), control,
        html.Small(hint, className="field-hint") if hint is not None else None,
    ])


def _number(identity: str, value: int | float, *, minimum: int | float,
            maximum: int | float | None = None, step: int | float = 1) -> dcc.Input:
    return dcc.Input(id=identity, type="number", value=value, min=minimum, max=maximum,
                     step=step, className="input")


def _select(identity: str, options: list[tuple[str, Any]], value: Any) -> dcc.Dropdown:
    return dcc.Dropdown(
        id=identity,
        options=[{"label": label, "value": option} for label, option in options],
        value=value, clearable=False, className="select",
    )


def _metric(label: str, value: str, note: str = "") -> html.Div:
    return html.Div(className="metric", children=[
        html.Span(label, className="metric-label"),
        html.Strong(value, className="metric-value"),
        html.Small(note, className="metric-note"),
    ])


def _card(title: str, child: Any, kicker: str | None = None, extra_class: str = "") -> html.Div:
    return html.Div(className=f"card {extra_class}", children=[
        html.Div(className="card-heading", children=[
            html.Div([html.Span(kicker, className="eyebrow") if kicker else None,
                      html.H3(title)]),
        ]), child,
    ])


def _table(headers: list[str], rows: list[list[Any]]) -> html.Table:
    return html.Table(className="data-table", children=[
        html.Thead(html.Tr([html.Th(header) for header in headers])),
        html.Tbody([html.Tr([html.Td(cell) for cell in row]) for row in rows]),
    ])


def _settings(dataset: str, platforms: int, seed: int, pickup_mode: str, pickups: int,
              dropoff_mode: str, dropoffs: int, split: str, window_start: str, window_end: str,
              source_ids: list[dict], source_values: list[str],
              vehicles: int, step_size: int, matcher: str, mechanism: str,
              radius: float, deadline: int, sharing: float,
              policy_ids: list[dict], policy_values: list[str],
              primary_platform: str = "P1") -> dict[str, Any]:
    return {
        "dataset": dataset, "platforms": int(platforms), "seed": int(seed),
        "primary_platform": primary_platform,
        "pickups_per_platform": "all" if pickup_mode == "all" else int(pickups),
        "dropoffs_per_platform": "all" if dropoff_mode == "all" else int(dropoffs),
        "split": split, "window_start": window_start, "window_end": window_end,
        "sources": {item["index"]: value for item, value in zip(source_ids, source_values, strict=True)}
                   if dataset != "synthetic" else {},
        "vehicles_per_platform": int(vehicles), "step_size_s": int(step_size),
        "matcher": matcher, "mechanism": mechanism,
        "service_radius_km": float(radius), "deadline_s": int(deadline),
        "sharing_rate": float(sharing),
        "policies": {item["index"]: value for item, value in zip(policy_ids, policy_values, strict=True)},
    }


def _simulation_page() -> html.Div:
    return html.Div(id="simulation-page", className="page", children=[
        html.Div(className="page-intro", children=[
            html.Div([html.Span("01 / SIMULATION", className="eyebrow"),
                      html.H2("Configure a cooperative assignment run"),
                      html.P("Set the workload, platform sources and MPCS mechanisms. Each run produces a process replay and analysis.")]),
            html.Div(id="dirty-note", className="dirty-note"),
        ]),
        html.Div(className="simulation-grid", children=[
            _card("Scenario & workload", html.Div(children=[
                html.Div(className="field-grid", children=[
                _field("Dataset", _select("dataset", [
                    ("Synthetic", "synthetic"), ("Chengdu", "chengdu"),
                    ("Shanghai", "shanghai"), ("Shanghai 16", "shanghai16"),
                ], "synthetic")),
                _field("Data split", _select("split", [(name.title(), name) for name in ("train", "validation", "test")], "test")),
                _field("Platforms", _select("platforms", [(str(n), n) for n in range(2, 17)], 4),
                       "Synthetic is adjustable; real datasets use a fixed platform count."),
                _field("Focus platform", _select("focus-platform", [(f"P{i}", f"P{i}") for i in range(1, 5)], "P1"),
                       "RL-CAPA uses this platform as the auction origin for the next run."),
                _field("Random seed", _number("seed", 11, minimum=0, maximum=2147483647)),
                _field("Arrival window start", dcc.Input(id="window-start", type="time", value="00:00", className="input")),
                _field("Arrival window end", dcc.Input(id="window-end", type="time", value="00:01", className="input")),
                _field("Pickup sample", _select("pickup-mode", [("Count", "count"), ("All eligible", "all")], "count")),
                _field("Pickups per platform", _number("pickups", 3, minimum=0)),
                _field("Dropoff sample", _select("dropoff-mode", [("Count", "count"), ("All eligible", "all")], "count")),
                _field("Dropoffs per platform", _number("dropoffs", 1, minimum=0)),
                _field("Vehicles per platform", _number("vehicles", 2, minimum=1)),
                _field("Frame interval / s", _select("step-size", [(str(x), x) for x in (10, 15, 20, 30, 60)], 30)),
                ]),
                html.Div(className="section-divider"),
                html.Div(className="inline-heading", children=[html.H4("Platform order dates"),
                    html.Small("Distinct dates on the same city road network")]),
                html.Div(id="source-controls", className="policy-grid"),
                html.Div(id="availability", className="availability"),
            ]), "A / INPUT"),
            _card("Decisions & mechanisms", html.Div(children=[
                html.Div(className="field-grid", children=[
                    _field("Local matcher", _select("matcher", [("Greedy", "greedy"), ("KM · maximum matching", "km")], "km")),
                    _field("Cross-platform mechanism", _select("mechanism", [
                        ("Paper · reverse Vickrey", "paper"),
                        ("Regional fixed payment", "regional-fixed"),
                        ("Pool random candidate", "pool-random"),
                    ], "paper"), html.Span(id="mechanism-note")),
                ]),
                html.Div(className="section-divider"),
                html.Div(className="inline-heading", children=[html.H4("Platform pool policies"),
                                                          html.Small("LOCAL / RELEASE / WAIT")]),
                html.Div(id="policy-controls", className="policy-grid"),
                html.Details(className="advanced", children=[
                    html.Summary("More simulation parameters"),
                    html.Div(className="field-grid", children=[
                        _field("Vehicle service radius / km", _number("radius", 10.0, minimum=0.1, maximum=100, step=0.1)),
                        _field("Pickup deadline / s", _number("deadline", 60, minimum=1, maximum=1800)),
                        _field("Cooperation sharing rate", _number("sharing", 0.3, minimum=0.01, maximum=1, step=0.01)),
                    ]),
                ]),
            ]), "B / MECHANISM"),
        ]),
        html.Div(className="run-bar", children=[
            html.Div([html.Span("RUN A SCENARIO", className="eyebrow"),
                      html.P("Collect all platform actions per frame, then match, auction and settle.")]),
            html.Div(className="button-row", children=[
                html.Button("Run simulation →", id="run-button", className="button primary"),
                html.Button("Load last replay", id="load-button", className="button secondary"),
            ]),
        ]),
        dcc.Interval(id="run-poll", interval=400, disabled=True),
        html.Div(className="run-progress-wrap", children=[
            html.Progress(id="run-progress", value=0, max=100),
            html.Div(id="run-status", className="run-status"),
        ]),
        html.Div(id="simulation-result"),
    ])


def _inspection_page() -> html.Div:
    return html.Div(id="inspection-page", className="page", style={"display": "none"}, children=[
        html.Div(className="page-intro", children=[
            html.Div([html.Span("02 / INSPECTION", className="eyebrow"),
                      html.H2("Inspect each decision batch"),
                      html.P("Step through all pending parcels, local matching, partner bids and settlement in each frame.")]),
            html.Div(id="inspection-source", className="source-pill"),
        ]),
        html.Div(id="current-metrics", className="metric-grid"),
        html.Div(id="stage-strip", className="stage-strip"),
        html.Div(className="inspection-grid", children=[
            _card("Road network & assignments", html.Div(children=[
                html.Div(className="map-toolbar", children=[
                    dcc.Checklist(
                        id="map-layers",
                        options=[
                            {"label": "Processed roads", "value": "road"},
                            {"label": "Station", "value": "station"},
                        ],
                        value=["road", "station"], inline=True, className="map-layers",
                    ),
                    html.Span("○ Unmatched parcel   ■ EV   ─ Road route   - - Local match   ··· Cross match", className="map-legend-hint"),
                ]),
                dcc.Graph(id="map", figure=map_figure(None, 0, None, None), config={
                    "scrollZoom": True, "displayModeBar": True, "displaylogo": False,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                }),
                html.Div(id="map-caption", className="figure-caption"),
            ]), "SPATIAL VIEW", "map-card"),
            _card("Batch decision trace", html.Div(id="parcel-details", className="parcel-details"),
                  "BATCH TRACE", "details-card"),
        ]),
        _card("Platform decision archive", html.Div(id="platform-details", className="platform-details"),
              "PLATFORM TRACE", "platform-card"),
        _card("Process timeline", html.Div(children=[
            html.Div(className="playback-row", children=[
                html.Div(className="button-row", children=[
                    html.Button("▶ Play", id="play-button", className="button primary small"),
                    html.Button("←", id="prev-button", className="button secondary small"),
                    html.Button("→", id="next-button", className="button secondary small"),
                    html.Button("Reset", id="reset-button", className="button secondary small"),
                ]),
                html.Div(id="step-label", className="step-label"),
                _select("speed", [("0.5×", 0.5), ("1×", 1), ("2×", 2)], 1),
            ]),
            dcc.Slider(id="timeline", min=0, max=0, value=0, step=1, marks=None,
                       tooltip={"placement": "bottom", "always_visible": False}),
        ]), "REPLAY", "playback-card"),
    ])


def _analysis_page() -> html.Div:
    return html.Div(id="analysis-page", className="page", style={"display": "none"}, children=[
        html.Div(className="page-intro", children=[
            html.Div([html.Span("03 / ANALYSIS", className="eyebrow"),
                      html.H2("Outcomes & platform flows"),
                      html.P("Analysis ends at the selected arrival window boundary; the replay continues through outstanding deadlines.")]),
            html.Button("Download replay JSON", id="download-button", className="button secondary"),
        ]),
        html.Div(id="final-metrics", className="metric-grid"),
        html.Div(id="analysis-content"),
    ])


app = Dash(__name__, assets_folder="assets", title="MAPS · System Demo")
server = app.server
app.layout = html.Div(className="app-shell", children=[
    dcc.Store(id="run-store"), dcc.Store(id="play-state", data=False),
    dcc.Interval(id="play-interval", interval=1200, disabled=True),
    dcc.Download(id="download-json"),
    html.Header(className="topbar", children=[
        html.Div(className="brand", children=[
            html.Div("M", className="brand-mark"),
            html.Div([html.Strong("MAPS"), html.Small("Multi-Platform Auction-aware Parcel Assignment System")]),
        ]),
        html.Div(className="topbar-right", children=[
            html.Span("COOPERATIVE URBAN LOGISTICS", className="topbar-context"),
            html.Span("LOCAL SYSTEM DEMO", className="topbar-badge"),
        ]),
    ]),
    html.Div(className="workspace", children=[
        dcc.Tabs(id="section", value="simulation", className="nav-tabs", children=[
            dcc.Tab(label="01  Simulation", value="simulation", className="nav-tab", selected_className="nav-tab selected"),
            dcc.Tab(label="02  Inspection", value="inspection", className="nav-tab", selected_className="nav-tab selected"),
            dcc.Tab(label="03  Analysis", value="analysis", className="nav-tab", selected_className="nav-tab selected"),
        ]),
        _simulation_page(), _inspection_page(), _analysis_page(),
    ]),
    html.Footer("MAPS · Local computation and replay / current MPCS mechanism", className="footer"),
])


@app.callback(
    Output("simulation-page", "style"), Output("inspection-page", "style"),
    Output("analysis-page", "style"), Input("section", "value"),
)
def show_section(section: str):
    return tuple({} if section == name else {"display": "none"}
                 for name in ("simulation", "inspection", "analysis"))


@app.callback(
    Output("platforms", "value"), Output("platforms", "disabled"),
    Output("pickup-mode", "disabled"), Output("dropoff-mode", "disabled"),
    Output("vehicles", "disabled"), Output("radius", "disabled"),
    Output("deadline", "disabled"), Output("vehicles", "value"),
    Output("deadline", "value"), Output("window-start", "value"),
    Output("window-end", "value"), Output("pickup-mode", "value"),
    Output("dropoff-mode", "value"),
    Input("dataset", "value"), State("platforms", "value"),
)
def dataset_controls(dataset: str, count: int):
    fixed = {"chengdu": 4, "shanghai": 4, "shanghai16": 16}
    synthetic = dataset == "synthetic"
    start, end = {"synthetic": ("00:00", "00:01"), "chengdu": ("07:00", "07:05"),
                  "shanghai": ("09:00", "10:00"), "shanghai16": ("09:00", "10:00")}[dataset]
    return (count if synthetic else fixed[dataset], not synthetic, synthetic, synthetic,
            False, False, False, 2 if synthetic else 4, 60 if synthetic else 720,
            start, end, "count", "count")


@app.callback(Output("pickups", "disabled"), Input("pickup-mode", "value"))
def pickup_count_control(mode: str):
    return mode == "all"


@app.callback(Output("dropoffs", "disabled"), Input("dropoff-mode", "value"))
def dropoff_count_control(mode: str):
    return mode == "all"


@app.callback(Output("source-controls", "children"),
              Input("dataset", "value"), Input("split", "value"), Input("platforms", "value"))
def platform_sources(dataset: str, split: str, count: int):
    if dataset == "synthetic":
        return html.Small("Synthetic orders are generated for each platform; no source date is needed.")
    from mpcs.config import DatasetSplit
    from mpcs.experiments.Presets import dataset_preset
    sources = source_options(dataset)
    preset = dataset_preset(dataset, output_root=Path("output/maps-demo"))
    return [html.Div(className="policy-row", children=[
        html.Span(platform, className="platform-chip",
                  style={"--platform-color": color_for(platform, list(preset.platform_ids))}),
        dcc.Dropdown(id={"type": "source", "index": platform},
                     options=[{"label": name.removeprefix("order_"), "value": name} for name in sources],
                     value=(preset.dataset.source_files_for_platform(platform, DatasetSplit(split))[0]
                            if preset.dataset.source_files_for_platform(platform, DatasetSplit(split))[0] in sources
                            else sources[index]),
                     clearable=False, className="select"),
    ]) for index, platform in enumerate(preset.platform_ids)]


@app.callback(
    Output("availability", "children"),
    Input("dataset", "value"), Input("split", "value"),
    Input("window-start", "value"), Input("window-end", "value"),
    Input("platforms", "value"), Input("pickups", "value"), Input("dropoffs", "value"),
    Input({"type": "source", "index": ALL}, "id"),
    Input({"type": "source", "index": ALL}, "value"),
)
def show_availability(dataset, split, start, end, platforms, pickups, dropoffs,
                      source_ids, source_values):
    if not start or not end or len(source_ids) != (0 if dataset == "synthetic" else int(platforms)):
        return "Select an arrival window and one date per platform."
    try:
        settings = {"dataset": dataset, "split": split, "platforms": platforms,
                    "window_start": start, "window_end": end,
                    "pickups_per_platform": pickups or 0, "dropoffs_per_platform": dropoffs or 0,
                    "sources": {item["index"]: value for item, value in zip(source_ids, source_values)}}
        counts = available_orders(settings)
        return html.Div(children=[
            html.Strong(f"Eligible orders in {start}–{end}"),
            _table(["Platform", "Pickup", "Dropoff"], [
                [platform, values["pickup"], values["dropoff"]] for platform, values in counts.items()
            ]),
            html.Small("Synthetic counts follow the requested generated workload." if dataset == "synthetic"
                       else "Counts follow parsing, deduplication and the operational grid filter."),
        ])
    except (ValueError, OSError) as error:
        return html.Span(str(error), className="status-error")


@app.callback(
    Output("focus-platform", "options"), Output("focus-platform", "value"),
    Output("policy-controls", "children"), Input("platforms", "value"),
    State("focus-platform", "value"),
)
def platform_controls(count: int, focus: str | None):
    count = int(count or 2)
    platforms = [f"P{i}" for i in range(1, count + 1)]
    controls = []
    defaults = ("release-first", "local-first", "mra", "impgta")
    for index, platform in enumerate(platforms):
        controls.append(html.Div(className="policy-row", children=[
            html.Span(platform, className="platform-chip", style={"--platform-color": color_for(platform, platforms)}),
            dcc.Dropdown(
                id={"type": "policy", "index": platform},
                options=[{"label": POLICY_LABELS[name], "value": name} for name in POLICIES],
                value=defaults[index] if index < len(defaults) else "local-first",
                clearable=False, className="select",
            ),
        ]))
    return ([{"label": platform, "value": platform} for platform in platforms],
            focus if focus in platforms else "P1", controls)


@app.callback(
    Output("mechanism", "disabled"), Output("mechanism-note", "children"),
    Input("focus-platform", "value"),
    Input({"type": "policy", "index": ALL}, "id"),
    Input({"type": "policy", "index": ALL}, "value"),
)
def capa_mechanism(focus: str, policy_ids: list[dict], policy_values: list[str]):
    selected = dict(zip((item["index"] for item in policy_ids), policy_values))
    if selected.get(focus) == "rl-capa":
        return True, "RL-CAPA uses its own local matcher and DAPA for this primary platform."
    return False, ""


def _run_worker(job: dict[str, Any], settings: dict[str, Any]) -> None:
    def progress(value: float, label: str) -> None:
        job["percent"] = int(value)
        job["label"] = label
    try:
        result = run_demo(settings, progress=progress)
        REPLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPLAY_PATH.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        job["result"] = result
        progress(100, f"Completed {len(result['batches'])} frames and {len(result['steps'])} replay steps.")
    except Exception as error:
        job["error"] = str(error)
        job["label"] = f"Simulation failed: {error}"
    finally:
        job["done"] = True


@app.callback(
    Output("run-store", "data"), Output("run-status", "children"),
    Output("run-progress", "value"), Output("run-poll", "disabled"),
    Output("run-button", "disabled"), Output("load-button", "disabled"),
    Input("run-button", "n_clicks"), Input("load-button", "n_clicks"),
    Input("run-poll", "n_intervals"),
    State("dataset", "value"), State("platforms", "value"), State("seed", "value"),
    State("pickup-mode", "value"), State("pickups", "value"),
    State("dropoff-mode", "value"), State("dropoffs", "value"),
    State("split", "value"), State("window-start", "value"), State("window-end", "value"),
    State({"type": "source", "index": ALL}, "id"),
    State({"type": "source", "index": ALL}, "value"),
    State("vehicles", "value"), State("step-size", "value"),
    State("matcher", "value"), State("mechanism", "value"),
    State("radius", "value"), State("deadline", "value"), State("sharing", "value"),
    State({"type": "policy", "index": ALL}, "id"),
    State({"type": "policy", "index": ALL}, "value"),
    State("focus-platform", "value"),
    prevent_initial_call=True,
)
def run_or_load(_run, _load, _poll, dataset, platforms, seed, pickup_mode, pickups,
                dropoff_mode, dropoffs, split, window_start, window_end, source_ids,
                source_values, vehicles, step_size, matcher, mechanism, radius,
                deadline, sharing, policy_ids, policy_values, primary_platform):
    global _RUN_JOB
    trigger = ctx.triggered_id
    if trigger == "run-poll":
        job = _RUN_JOB
        if job is None:
            return no_update, no_update, no_update, True, False, False
        if not job["done"]:
            return no_update, job["label"], job["percent"], False, True, True
        _RUN_JOB = None
        if "error" in job:
            return no_update, html.Span(job["label"], className="status-error"), job["percent"], True, False, False
        return (_cache_run(job["result"]), html.Span(job["label"], className="status-success"),
                100, True, False, False)
    if _RUN_JOB is not None:
        return no_update, "A simulation is already running.", no_update, False, True, True
    if trigger == "load-button":
        try:
            result = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
            if "analysis_end_s" not in result["meta"] or "batch_parcels" not in result["steps"][0]:
                raise ValueError("This replay predates batch inspection; run a new scenario.")
            result["meta"]["source"] = "replay"
            return (_cache_run(result), html.Span("Loaded the previous replay.", className="status-success"),
                    100, True, False, False)
        except (OSError, ValueError) as error:
            return no_update, html.Span(f"Replay load failed: {error}", className="status-error"), 0, True, False, False
    try:
        settings = _settings(dataset, platforms, seed, pickup_mode, pickups,
                             dropoff_mode, dropoffs, split, window_start, window_end,
                             source_ids, source_values, vehicles, step_size, matcher,
                             mechanism, radius, deadline, sharing, policy_ids, policy_values,
                             primary_platform)
        if parse_clock(window_start) >= parse_clock(window_end):
            raise ValueError("Arrival window end must follow its start")
        job = {"percent": 0, "label": "Preparing scenario", "done": False}
        _RUN_JOB = job
        Thread(target=_run_worker, args=(job, settings), daemon=True).start()
        return no_update, job["label"], 0, False, True, True
    except (ValueError, TypeError) as error:
        return no_update, html.Span(str(error), className="status-error"), 0, True, False, False


@app.callback(
    Output("dirty-note", "children"),
    Input("run-store", "data"), Input("dataset", "value"), Input("platforms", "value"),
    Input("seed", "value"), Input("pickup-mode", "value"), Input("pickups", "value"),
    Input("dropoff-mode", "value"), Input("dropoffs", "value"),
    Input("split", "value"), Input("window-start", "value"), Input("window-end", "value"),
    Input({"type": "source", "index": ALL}, "id"),
    Input({"type": "source", "index": ALL}, "value"),
    Input("vehicles", "value"), Input("step-size", "value"), Input("matcher", "value"),
    Input("mechanism", "value"), Input("radius", "value"), Input("deadline", "value"),
    Input("sharing", "value"), Input({"type": "policy", "index": ALL}, "id"),
    Input({"type": "policy", "index": ALL}, "value"), Input("focus-platform", "value"),
)
def config_notice(reference: dict | None, dataset: str, platforms: int, seed: int,
                  pickup_mode: str, pickups: int, dropoff_mode: str, dropoffs: int,
                  split: str, window_start: str, window_end: str,
                  source_ids: list[dict], source_values: list[str],
                  vehicles: int, step_size: int,
                  matcher: str, mechanism: str, radius: float, deadline: int,
                  sharing: float, policy_ids: list[dict], policy_values: list[str],
                  primary_platform: str):
    run = _get_run(reference)
    if not run:
        return "Ready to run"
    try:
        current = _settings(dataset, platforms, seed, pickup_mode, pickups,
                            dropoff_mode, dropoffs, split, window_start, window_end,
                            source_ids, source_values, vehicles, step_size, matcher,
                            mechanism, radius, deadline, sharing, policy_ids, policy_values,
                            primary_platform)
    except (ValueError, TypeError):
        return "Complete the configuration before running"
    return ("Settings changed · run again to apply" if current != run["meta"]["settings"]
            else "Results match the current settings")


@app.callback(Output("simulation-result", "children"), Input("run-store", "data"))
def simulation_result(reference: dict | None):
    run = _get_run(reference)
    if not run:
        return html.Div(className="empty-panel", children=[
            html.Span("WORKLOAD → PARCEL → LOCAL → AUCTION → SETTLEMENT", className="eyebrow"),
            html.P("Run a scenario to inspect every frame and parcel decision."),
        ])
    summary = run["summary"]
    return html.Div(className="simulation-summary", children=[
        _metric("Pickup parcels", str(summary["total"]), f"{run['meta']['split']} split"),
        _metric("Assigned by window end", str(summary["assigned"]), f"Assignment rate {summary['assignment_rate']:.1%}"),
        _metric("Cross-platform", str(summary["cross_count"]), "Origin differs from serving platform"),
        _metric("Window ledger total", f"{summary['profit']:.2f}", f"Through {clock_time(run['meta']['analysis_end_s'])}"),
    ])


@app.callback(
    Output("timeline", "max"), Input("run-store", "data"),
)
def timeline_max(reference: dict | None):
    run = _get_run(reference)
    return max(0, len(run["steps"]) - 1) if run else 0


@app.callback(
    Output("play-state", "data"), Input("play-button", "n_clicks"),
    Input("reset-button", "n_clicks"), Input("run-store", "data"),
    Input("timeline", "value"), State("play-state", "data"), State("timeline", "max"),
)
def playing(_play: int, _reset: int, _run: dict | None, value: int, active: bool, maximum: int):
    if ctx.triggered_id == "play-button":
        return not active
    if ctx.triggered_id in {"reset-button", "run-store"} or value >= maximum:
        return False
    return active


@app.callback(
    Output("play-interval", "disabled"), Output("play-interval", "interval"),
    Output("play-button", "children"), Input("play-state", "data"),
    Input("speed", "value"), Input("run-store", "data"),
)
def interval_control(active: bool, speed: float, run: dict | None):
    return (not active or not run, int(1200 / float(speed or 1)), "Ⅱ Pause" if active else "▶ Play")


@app.callback(
    Output("timeline", "value"), Input("run-store", "data"),
    Input("next-button", "n_clicks"), Input("prev-button", "n_clicks"),
    Input("reset-button", "n_clicks"), Input("play-interval", "n_intervals"),
    State("timeline", "value"), State("play-state", "data"),
)
def move_timeline(reference: dict | None, _next: int, _prev: int, _reset: int,
                  _tick: int, value: int | None, active: bool):
    run = _get_run(reference)
    if not run:
        return 0
    maximum = len(run["steps"]) - 1
    current = int(value or 0)
    trigger = ctx.triggered_id
    if trigger in {"run-store", "reset-button"}:
        return next((step["index"] for step in run["steps"]
                     if step["stage"] == "workload" and step["decisions"]), 0)
    if trigger == "next-button" or (trigger == "play-interval" and active):
        return min(maximum, current + 1)
    if trigger == "prev-button":
        return max(0, current - 1)
    return no_update


def _stage_strip(stage: str, batch: int) -> list[html.Div]:
    active_index = STAGES.index(stage)
    return [html.Div(className=f"stage-item {'active' if index == active_index else 'done' if index < active_index else ''}",
                     children=[html.Span(number, className="stage-number"),
                               html.Div([html.Strong(english), html.Small(description)]),
                               html.Span("→" if index < 4 else "", className="stage-arrow")])
            for index, (number, english, description) in enumerate(STAGE_LABELS.values())]


def _batch_detail(run: dict[str, Any], index: int) -> Any:
    step = run["steps"][index]
    stage_index = STAGES.index(step["stage"])
    catalog = run["catalog"]
    batch_ids = step.get("batch_parcels", [])
    if run["meta"]["mechanism"] == "dapa":
        primary = run["meta"]["primary_platform"]
        batch_ids = [parcel_id for parcel_id in batch_ids
                     if catalog[parcel_id]["origin"] == primary]
    if not batch_ids:
        return html.P("No pickup parcels await a decision in this batch.", className="muted")
    rows = []
    local_count = cross_count = released_count = 0
    for parcel_id in batch_ids:
        parcel = catalog[parcel_id]
        state = step["state"]["parcels"][parcel_id]
        detail = step["details"].get(parcel_id, {})
        action = step["decisions"].get(parcel_id)
        local = (detail.get("local_matches") or [None])[0] if stage_index >= 2 else None
        award = (detail.get("awards") or [None])[0] if stage_index >= 3 else None
        serving = detail.get("serving_receipt") if stage_index >= 4 else None
        if local:
            local_count += 1
        if award:
            cross_count += 1
        if action == "RELEASE":
            released_count += 1
        local_text = (f"{local['vehicle_id']} · {local['extra_km']:.2f} km" if local
                      else "Released" if action == "RELEASE" and stage_index >= 2
                      else "No feasible match" if stage_index >= 2 else "—")
        cross_text = (f"{award['winner']} / {serving['vehicle_id'] if serving else 'EV pending'}"
                      if award else "No valid bid" if action == "RELEASE" and stage_index >= 3
                      else "—")
        rows.append([
            html.Div([html.Strong(parcel["label"]), html.Code(parcel_id, title=parcel_id)]),
            parcel["origin"],
            STATUS_LABELS.get(state["status"], state["status"]),
            action if stage_index >= 1 and action else "—",
            local_text, cross_text,
        ])
    sections = [
        html.Div(className="parcel-title", children=[
            html.Div([html.Span("CURRENT FRAME", className="eyebrow"),
                      html.H3(f"Batch {step['batch']} · {clock_time(step['decision_time_s'])}")]),
            html.Span(f"{len(batch_ids)} parcels", className="status-badge"),
        ]),
        html.Div(className="workload-chips", children=[
            html.Span(f"{len(batch_ids)} pending in batch"),
            html.Span(f"{local_count} local matches"),
            html.Span(f"{released_count} released"),
            html.Span(f"{cross_count} cross awards"),
        ]),
        html.Div(className="batch-table-wrap", children=_table(
            ["Parcel", "Origin", "Status", "Pool action", "Local match", "Cross match"], rows
        )),
    ]
    if stage_index >= 2:
        candidate_rows = []
        for parcel_id in batch_ids:
            detail = step["details"].get(parcel_id, {})
            selected = {match["vehicle_id"] for match in detail.get("local_matches", [])}
            for option in detail.get("local_options", []):
                threshold = step.get("thresholds", {}).get(catalog[parcel_id]["origin"])
                revenue = option.get("revenue_score")
                decision = ("Matched" if option["vehicle_id"] in selected else
                            "Below threshold" if revenue is not None and threshold is not None
                            and revenue < threshold else
                            "Released after batch planning" if step["decisions"].get(parcel_id) == "RELEASE"
                            and revenue is not None else "Candidate")
                candidate_rows.append([
                    catalog[parcel_id]["label"], option["vehicle_id"],
                    f"{option['extra_km']:.3f} km", clock_time(option["eta_s"]),
                    f"{revenue:.3f} / {threshold:.3f}" if revenue is not None and threshold is not None else "—",
                    decision,
                ])
        sections.append(html.Div(className="trace-section", children=[
            html.H4("Local candidate evaluation"),
            html.P("Revenue score / dynamic threshold is shown for RL-CAPA pairs.",
                   className="hint-line") if step.get("thresholds") else None,
            html.Div(className="batch-table-wrap", children=_table(
                ["Parcel", "Candidate EV", "Extra distance", "ETA", "Revenue / threshold", "Result"],
                candidate_rows,
            )) if candidate_rows else html.P("No feasible local candidates in this batch.", className="muted"),
        ]))
    if stage_index >= 3:
        auctions = []
        for parcel_id in batch_ids:
            detail = step["details"].get(parcel_id, {})
            if step["decisions"].get(parcel_id) != "RELEASE" and not detail.get("valid_bids"):
                continue
            bids = sorted(detail.get("platform_bids") or detail.get("valid_bids", []),
                          key=lambda item: item["amount"])
            award = (detail.get("awards") or [None])[0]
            candidates = detail.get("intent_candidates", [])
            auctions.append(html.Div(className="trace-section", children=[
                html.Div(className="parcel-title", children=[
                    html.H4(catalog[parcel_id]["label"]),
                    html.Span("Awarded" if award else "Unmatched", className="status-badge"),
                ]),
                html.P("Eligible partner intents: " + (
                    "; ".join(f"{item['platform']} → {', '.join(item['vehicle_ids'])}"
                              for item in candidates) if candidates else "none"
                ), className="hint-line"),
                _table(
                    ["Partner", "Courier bid", "Platform bid", "Auction result"]
                    if run["meta"]["mechanism"] == "dapa"
                    else ["Partner", "Valid bid", "Auction result"],
                    [([bid["platform"], f"{bid['courier_bid']:.3f}",
                       f"{bid['amount']:.3f}"] if run["meta"]["mechanism"] == "dapa"
                      else [bid["platform"], f"{bid['amount']:.3f}"])
                     + ["Above limit" if not bid.get("valid", True) else
                        "Winner" if award and award["winner"] == bid["platform"] else "Valid bid"]
                     for bid in bids],
                ) if bids else html.P("No eligible partner submitted a bid.", className="muted"),
                html.Div(
                    f"Selected {award['winner']} · payment {award['payment']:.3f} "
                    f"· {award['valid_bidder_count']} valid bids",
                    className="award-line"
                ) if award else None,
            ]))
        sections.append(html.Div(className="auction-list", children=[
            html.H4("Cross-platform auction by parcel"),
            html.P("All eligible partners quote; the lowest valid platform bid wins. "
                   "With two or more valid bids, payment is the second-lowest bid.",
                   className="hint-line") if run["meta"]["mechanism"] in {"paper", "dapa"} else None,
            *auctions,
        ]) if auctions else html.P("No released parcels entered the auction in this batch.",
                                   className="muted"))
    if stage_index >= 4:
        settlements = []
        for parcel_id in batch_ids:
            detail = step["details"].get(parcel_id, {})
            receipt = detail.get("origin_receipt")
            if receipt:
                settlements.append([
                    catalog[parcel_id]["label"],
                    detail.get("outcome", "Assigned"),
                    f"{receipt['utility']:.3f}",
                    f"{receipt['payment']:.3f}" if receipt["payment"] is not None else "—",
                ])
        if settlements:
            sections.append(html.Div(className="trace-section", children=[
                html.H4("Batch settlement"),
                _table(["Parcel", "Outcome", "Origin utility", "Cross payment"], settlements),
            ]))
    return sections


@app.callback(
    Output("map", "figure"), Output("current-metrics", "children"),
    Output("stage-strip", "children"), Output("parcel-details", "children"),
    Output("platform-details", "children"),
    Output("step-label", "children"), Output("inspection-source", "children"),
    Output("map-caption", "children"),
    Input("run-store", "data"), Input("timeline", "value"),
    Input("focus-platform", "value"),
    Input("map-layers", "value"),
)
def render_inspection(reference: dict | None, index: int | None, focus: str | None,
                      layers: list[str] | None):
    run = _get_run(reference)
    if not run:
        return (map_figure(None, 0, None, None), [], [],
                html.P("Run a scenario in Simulation first.", className="muted"),
                html.P("Select a platform after running a scenario.", className="muted"),
                "Awaiting simulation", "No run",
                "The full processed road network and stations appear after a run. Scroll to zoom and drag to pan.")
    index = max(0, min(int(index or 0), len(run["steps"]) - 1))
    step = run["steps"][index]
    metrics = step["metrics"]
    stage = STAGE_LABELS[step["stage"]]
    cards = [
        _metric("Current frame", f"{step['batch']:02d}", clock_time(step['decision_time_s'])),
        _metric("Pending parcels", str(sum(
            parcel_state["status"] == "waiting"
            for parcel_state in step["state"]["parcels"].values()
        )), "All platforms"),
        _metric("Assigned", f"{metrics['assigned']} / {metrics['total']}", "Pickup parcels"),
        _metric("Cumulative ledger", f"{metrics['profit']:.2f}", "All platforms"),
    ]
    own = [(pid, state) for pid, state in step["state"]["parcels"].items()
           if run["catalog"][pid]["origin"] == focus]
    matched = [state for _, state in own if state["serving_platform"]]
    archive = metrics.get("platform_archive", {}).get(focus, {})
    decisions = ([value for pid, value in step["decisions"].items()
                  if run["catalog"][pid]["origin"] == focus]
                 if step["stage"] != "workload" else [])
    platform_cards = html.Div(children=[
        html.Div(className="parcel-title", children=[
            html.Div([html.Span("FOCUS PLATFORM", className="eyebrow"), html.H3(focus or "—")]),
            html.Span(clock_time(step["decision_time_s"]), className="status-badge"),
        ]),
        html.Div(className="platform-stat-grid", children=[
            _metric("Pending", str(sum(state["status"] == "waiting" for _, state in own)), "Current stage"),
            _metric("Local decisions", str(decisions.count("LOCAL")), "This frame"),
            _metric("Cross decisions", str(decisions.count("RELEASE")), "This frame"),
            _metric("Matched", str(len(matched)), "Cumulative"),
            _metric("Locally processed", str(sum(state["serving_platform"] == focus for state in matched)), "Cumulative matches"),
            _metric("Cross-platform processed", str(sum(state["serving_platform"] != focus for state in matched)), "Cumulative matches"),
            _metric("Current profit", f"{metrics['profit_by_platform'].get(focus, 0):.2f}", "Ledger to current stage"),
            _metric("Local match profit", f"{archive.get('local_profit', 0):.2f}", "Cumulative"),
            _metric("Cross-platform profit", f"{archive.get('cross_profit', 0):.2f}", "Origin + serving"),
            _metric("Dropoff profit", f"{archive.get('dropoff_profit', 0):.2f}", "Included in current profit"),
        ]),
    ])
    geography = run.get("geography")
    if geography:
        caption = (
            f"{run['meta']['dataset']} processed network · {geography['node_count']:,} nodes / "
            f"{geography['arc_count']:,} directed arcs · all {geography['display_segment_count']:,} distinct "
            f"road connections drawn · {len(geography['stations'])} stations. "
            "Scroll to zoom, drag to pan, double-click to reset. Only unmatched parcels are mapped. Solid routes follow roads; dashed connectors show matches."
        )
    else:
        caption = "This replay has no saved road layer; parcel and EV markers remain available."
    if ctx.triggered_id in {"run-store", "map-layers"}:
        map_view = map_figure(run, index, focus, None, layers)
    else:
        map_view = Patch()
        first_dynamic = map_static_trace_count(run, layers)
        for position, trace in enumerate(map_dynamic_traces(run, index, focus, None)):
            map_view["data"][first_dynamic + position] = trace.to_plotly_json()
    return (
        map_view, cards, _stage_strip(step["stage"], step["batch"]),
        _batch_detail(run, index), platform_cards,
        f"Frame {step['batch']} · {stage[1]} · {index + 1}/{len(run['steps'])}",
        "Loaded replay" if run["meta"]["source"] == "replay" else "Computed run · stage replay",
        caption,
    )


@app.callback(
    Output("final-metrics", "children"), Output("analysis-content", "children"),
    Input("run-store", "data"), Input("focus-platform", "value"),
)
def render_analysis(reference: dict | None, focus: str | None):
    run = _get_run(reference)
    if not run:
        return [], html.Div("Run a scenario to generate outcome charts.", className="empty-panel")
    summary = run["summary"]
    cards = [
        _metric("Assigned / pickup parcels", f"{summary['assigned']} / {summary['total']}", f"Assignment rate {summary['assignment_rate']:.1%}"),
        _metric("Local / cross matches", f"{summary['local_count']} / {summary['cross_count']}", "Committed by window end"),
        _metric("Collected / unloaded", f"{summary['collected']} / {summary['unloaded']}", "Progress by window end"),
        _metric("Window ledger total", f"{summary['profit']:.2f}", f"Through {clock_time(run['meta']['analysis_end_s'])}"),
    ]
    content = html.Div(children=[
        html.Div(className="chart-grid", children=[
            _card("Cumulative ledger profit", dcc.Graph(figure=profit_figure(run, focus), config={"displayModeBar": False}), "TIME SERIES"),
            _card("Profit per minute", dcc.Graph(figure=minute_profit_figure(run, focus), config={"displayModeBar": False}), "ONE-MINUTE DELTA"),
            _card("Profit by platform", dcc.Graph(figure=platform_profit_figure(run, focus), config={"displayModeBar": False}), "PLATFORM VIEW"),
            _card("Pickup assignment status", dcc.Graph(figure=status_figure(run), config={"displayModeBar": False}), "OUTCOMES"),
            _card("Origin → serving platform", dcc.Graph(figure=flow_figure(run), config={"displayModeBar": False}), "COOPERATION FLOW"),
        ]),
        _card("Run provenance", html.Div(className="meta-grid", children=[
            html.Div([html.Small("Dataset / split"), html.Strong(f"{run['meta']['dataset']} / {run['meta']['split']}")]),
            html.Div([html.Small("Analysis window"), html.Strong(f"{run['meta']['settings']['window_start']}–{run['meta']['settings']['window_end']}")]),
            html.Div([html.Small("Seed"), html.Strong(str(run['meta']['seed']))]),
            html.Div([html.Small("Local matcher"), html.Strong(run['meta']['matcher'].upper())]),
            html.Div([html.Small("Cross-platform mechanism"), html.Strong(run['meta']['mechanism'])]),
            html.Div([html.Small("Analyzed / replay frames"), html.Strong(f"{summary['batch']} / {len(run['batches'])}")]),
        ]), "PROVENANCE"),
    ])
    return cards, content


@app.callback(
    Output("download-json", "data"), Input("download-button", "n_clicks"),
    State("run-store", "data"), prevent_initial_call=True,
)
def download_replay(_clicks: int, reference: dict | None):
    run = _get_run(reference)
    if not run:
        return no_update
    return dcc.send_string(json.dumps(run, ensure_ascii=False, indent=2), "maps-replay.json")


def main() -> None:
    app.run(debug=False, host="127.0.0.1", port=8050)


if __name__ == "__main__":
    main()
