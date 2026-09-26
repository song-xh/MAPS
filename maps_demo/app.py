"""Local interactive MAPS system demonstration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from maps_demo.engine import MATCHERS, MECHANISMS, POLICIES, STAGES, run_demo
from maps_demo.figures import (
    color_for, flow_figure, map_figure, platform_profit_figure,
    profit_figure, status_figure,
)


REPLAY_PATH = Path("output/maps-demo/latest.json")
STAGE_LABELS = {
    "workload": ("01", "Workload", "任务到达"),
    "parcel": ("02", "Parcel", "平台分池动作"),
    "local": ("03", "Local decision", "本地可行匹配"),
    "auction": ("04", "Auction", "跨平台竞价"),
    "settlement": ("05", "Settlement", "执行与结算"),
}
POLICY_LABELS = {
    "release-first": "全部共享 · 演示规则",
    "local-first": "全部本地 · 演示规则",
    "wait-first": "全部等待 · 演示规则",
    "localsum": "LocalSum",
    "rl-capa": "RL-CAPA 基线",
    "mra": "MRA",
    "impgta": "IMPGTA",
    "fed-ltd": "Fed-LTD",
}
STATUS_LABELS = {
    "future": "尚未到达", "waiting": "待处理", "public_this_step": "本帧共享",
    "cross_pool": "跨平台池", "local_assigned": "本地已分配",
    "cross_assigned": "跨平台已分配", "collected": "已取件",
    "unloaded": "已卸货", "expired": "已过期",
}


def _field(label: str, control: Any, hint: str | None = None) -> html.Div:
    return html.Div(className="field", children=[
        html.Label(label), control,
        html.Small(hint, className="field-hint") if hint else None,
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


def _settings(dataset: str, platforms: int, seed: int, pickups: int, dropoffs: int,
              vehicles: int, step_size: int, matcher: str, mechanism: str,
              radius: float, deadline: int, sharing: float,
              policy_ids: list[dict], policy_values: list[str]) -> dict[str, Any]:
    return {
        "dataset": dataset, "platforms": int(platforms), "seed": int(seed),
        "pickups_per_platform": int(pickups), "dropoffs_per_platform": int(dropoffs),
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
                      html.H2("配置并运行一场合作分配"),
                      html.P("调整 CLI 与 config 中影响演示的设置。一次运行生成真实过程回放与结果产物。")]),
            html.Div(id="dirty-note", className="dirty-note"),
        ]),
        html.Div(className="simulation-grid", children=[
            _card("场景与工作量", html.Div(className="field-grid", children=[
                _field("数据预设", _select("dataset", [
                    ("Synthetic · 无外部数据", "synthetic"), ("Chengdu · 本地数据", "chengdu"),
                    ("Shanghai · 本地数据", "shanghai"), ("Shanghai 16 · 本地数据", "shanghai16"),
                ], "synthetic")),
                _field("平台数量", _select("platforms", [(str(n), n) for n in range(2, 17)], 4),
                       "Synthetic 可调整；真实数据按预设固定"),
                _field("目标平台", _select("focus-platform", [(f"P{i}", f"P{i}") for i in range(1, 5)], "P1"),
                       "仅影响高亮，不改变仿真"),
                _field("随机种子", _number("seed", 11, minimum=0, maximum=2147483647)),
                _field("每平台取件", _number("pickups", 3, minimum=1, maximum=30), "仅 Synthetic"),
                _field("每平台既有送件", _number("dropoffs", 1, minimum=0, maximum=20), "仅 Synthetic"),
                _field("每平台车辆", _number("vehicles", 2, minimum=1, maximum=16), "仅 Synthetic"),
                _field("物理帧间隔 / 秒", _select("step-size", [(str(x), x) for x in (10, 15, 20, 30, 45, 60)], 30)),
            ]), "A / INPUT"),
            _card("决策与机制", html.Div(children=[
                html.Div(className="field-grid", children=[
                    _field("本地匹配", _select("matcher", [("Greedy", "greedy"), ("KM · 最大匹配", "km")], "km")),
                    _field("跨平台机制", _select("mechanism", [
                        ("Paper · 反向 Vickrey", "paper"),
                        ("Regional fixed · 固定支付", "regional-fixed"),
                        ("Pool random · 随机单候选", "pool-random"),
                    ], "paper")),
                ]),
                html.Div(className="section-divider"),
                html.Div(className="inline-heading", children=[html.H4("各平台分池策略"),
                                                          html.Small("先决定 LOCAL / RELEASE / WAIT")]),
                html.Div(id="policy-controls", className="policy-grid"),
                html.Details(className="advanced", children=[
                    html.Summary("更多仿真参数"),
                    html.Div(className="field-grid", children=[
                        _field("车辆服务半径 / km", _number("radius", 10.0, minimum=0.1, maximum=100, step=0.1), "仅 Synthetic"),
                        _field("取件期限 / 秒", _number("deadline", 60, minimum=1, maximum=600), "仅 Synthetic"),
                        _field("跨平台分享比例", _number("sharing", 0.3, minimum=0.01, maximum=1, step=0.01)),
                    ]),
                ]),
            ]), "B / MECHANISM"),
        ]),
        html.Div(className="run-bar", children=[
            html.Div([html.Span("RUN A SCENARIO", className="eyebrow"),
                      html.P("同一物理帧收集全部平台动作，然后匹配、竞价与结算。")]),
            html.Div(className="button-row", children=[
                html.Button("运行仿真 →", id="run-button", className="button primary"),
                html.Button("加载上次回放", id="load-button", className="button secondary"),
            ]),
        ]),
        dcc.Loading(html.Div(id="run-status", className="run-status"), type="circle"),
        html.Div(id="simulation-result"),
    ])


def _inspection_page() -> html.Div:
    return html.Div(id="inspection-page", className="page", style={"display": "none"}, children=[
        html.Div(className="page-intro", children=[
            html.Div([html.Span("02 / INSPECTION", className="eyebrow"),
                      html.H2("沿一件包裹追踪完整决策"),
                      html.P("点地图包裹或从列表选择；横向切换工作量、分池、本地匹配、竞价和结算。")]),
            html.Div(id="inspection-source", className="source-pill"),
        ]),
        html.Div(id="current-metrics", className="metric-grid"),
        html.Div(id="stage-strip", className="stage-strip"),
        html.Div(className="inspection-grid", children=[
            _card("平台与包裹", html.Div(children=[
                dcc.Graph(id="map", figure=map_figure(None, 0, None, None), config={"displayModeBar": False}),
                html.Div("地图点位来自场景经纬度；重合点为阅读而轻微错位，连线表示匹配关系。", className="figure-caption"),
            ]), "SPATIAL VIEW", "map-card"),
            _card("包裹决策档案", html.Div(children=[
                _field("选择包裹", dcc.Dropdown(id="parcel-picker", options=[], placeholder="先运行场景", className="select")),
                html.Div(id="parcel-details", className="parcel-details"),
            ]), "DECISION TRACE", "details-card"),
        ]),
        _card("过程时间轴", html.Div(children=[
            html.Div(className="playback-row", children=[
                html.Div(className="button-row", children=[
                    html.Button("▶ 播放", id="play-button", className="button primary small"),
                    html.Button("←", id="prev-button", className="button secondary small"),
                    html.Button("→", id="next-button", className="button secondary small"),
                    html.Button("重置", id="reset-button", className="button secondary small"),
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
                      html.H2("结果产物与平台间流向"),
                      html.P("数字来自同次仿真的经济账本和生命周期；分配、取件与卸货分别统计。")]),
            html.Button("下载本次回放 JSON", id="download-button", className="button secondary"),
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
    html.Footer("MAPS · 本地计算与回放 / 当前 MPCS 机制", className="footer"),
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
    Output("pickups", "disabled"), Output("dropoffs", "disabled"),
    Output("vehicles", "disabled"), Output("radius", "disabled"),
    Output("deadline", "disabled"), Input("dataset", "value"), State("platforms", "value"),
)
def dataset_controls(dataset: str, count: int):
    fixed = {"chengdu": 4, "shanghai": 4, "shanghai16": 16}
    synthetic = dataset == "synthetic"
    return (count if synthetic else fixed[dataset],) + (not synthetic,) * 6


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
    Output("run-store", "data"), Output("run-status", "children"),
    Input("run-button", "n_clicks"), Input("load-button", "n_clicks"),
    State("dataset", "value"), State("platforms", "value"), State("seed", "value"),
    State("pickups", "value"), State("dropoffs", "value"), State("vehicles", "value"),
    State("step-size", "value"), State("matcher", "value"), State("mechanism", "value"),
    State("radius", "value"), State("deadline", "value"), State("sharing", "value"),
    State({"type": "policy", "index": ALL}, "id"),
    State({"type": "policy", "index": ALL}, "value"),
    running=[
        (Output("run-button", "disabled"), True, False),
        (Output("load-button", "disabled"), True, False),
    ],
    prevent_initial_call=True,
)
def run_or_load(_run: int, _load: int, dataset: str, platforms: int, seed: int,
                pickups: int, dropoffs: int, vehicles: int, step_size: int,
                matcher: str, mechanism: str, radius: float, deadline: int,
                sharing: float, policy_ids: list[dict], policy_values: list[str]):
    try:
        if ctx.triggered_id == "load-button":
            result = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
            result["meta"]["source"] = "replay"
            return result, html.Span("已加载上次运行的真实过程回放。", className="status-success")
        settings = _settings(dataset, platforms, seed, pickups, dropoffs, vehicles,
                             step_size, matcher, mechanism, radius, deadline, sharing,
                             policy_ids, policy_values)
        result = run_demo(settings)
        REPLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPLAY_PATH.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result, html.Span(
            f"已完成 {len(result['batches'])} 个物理帧，记录 {len(result['steps'])} 个展示步骤。",
            className="status-success",
        )
    except Exception as error:
        return None, html.Span(f"运行失败：{error}", className="status-error")


@app.callback(
    Output("dirty-note", "children"),
    Input("run-store", "data"), Input("dataset", "value"), Input("platforms", "value"),
    Input("seed", "value"), Input("pickups", "value"), Input("dropoffs", "value"),
    Input("vehicles", "value"), Input("step-size", "value"), Input("matcher", "value"),
    Input("mechanism", "value"), Input("radius", "value"), Input("deadline", "value"),
    Input("sharing", "value"), Input({"type": "policy", "index": ALL}, "id"),
    Input({"type": "policy", "index": ALL}, "value"),
)
def config_notice(run: dict | None, dataset: str, platforms: int, seed: int,
                  pickups: int, dropoffs: int, vehicles: int, step_size: int,
                  matcher: str, mechanism: str, radius: float, deadline: int,
                  sharing: float, policy_ids: list[dict], policy_values: list[str]):
    if not run:
        return "准备就绪 · 可直接运行默认场景"
    try:
        current = _settings(dataset, platforms, seed, pickups, dropoffs, vehicles,
                            step_size, matcher, mechanism, radius, deadline, sharing,
                            policy_ids, policy_values)
    except (ValueError, TypeError):
        return "参数尚未完整；请检查输入"
    return ("参数已修改 · 重新运行后生效" if current != run["meta"]["settings"]
            else "当前结果对应面板设置")


@app.callback(Output("simulation-result", "children"), Input("run-store", "data"))
def simulation_result(run: dict | None):
    if not run:
        return html.Div(className="empty-panel", children=[
            html.Span("WORKLOAD → PARCEL → LOCAL → AUCTION → SETTLEMENT", className="eyebrow"),
            html.P("运行后可在 Inspection 查看每个物理帧和包裹的决策路径。"),
        ])
    summary = run["summary"]
    return html.Div(className="simulation-summary", children=[
        _metric("取件包裹", str(summary["total"]), "本次 test 场景"),
        _metric("已分配", str(summary["assigned"]), f"分配率 {summary['assignment_rate']:.1%}"),
        _metric("跨平台", str(summary["cross_count"]), "来源与服务平台不同"),
        _metric("经济账本合计", f"{summary['profit']:.2f}", "非准时完成率"),
    ])


@app.callback(
    Output("parcel-picker", "options"), Output("parcel-picker", "value"),
    Input("run-store", "data"), Input("map", "clickData"), Input("focus-platform", "value"),
    State("parcel-picker", "value"),
)
def choose_parcel(run: dict | None, click: dict | None, focus: str | None, current: str | None):
    if not run:
        return [], None
    catalog = run["catalog"]
    options = [{"label": f"{item['label']} · t={item['arrival_s']}s", "value": parcel_id}
               for parcel_id, item in catalog.items()]
    if ctx.triggered_id == "map" and click:
        custom = click["points"][0].get("customdata")
        if custom and custom[0] == "parcel" and custom[1] in catalog:
            return options, custom[1]
    if current in catalog and ctx.triggered_id != "run-store":
        return options, current
    cross = [parcel_id for parcel_id, state in run["steps"][-1]["state"]["parcels"].items()
             if parcel_id in catalog and catalog[parcel_id]["origin"] == focus and
             state["serving_platform"] not in (None, focus)]
    preferred = cross or [pid for pid, item in catalog.items() if item["origin"] == focus]
    return options, (preferred or list(catalog))[0] if catalog else None


@app.callback(
    Output("timeline", "max"), Input("run-store", "data"),
)
def timeline_max(run: dict | None):
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
    return (not active or not run, int(1200 / float(speed or 1)), "Ⅱ 暂停" if active else "▶ 播放")


@app.callback(
    Output("timeline", "value"), Input("run-store", "data"),
    Input("next-button", "n_clicks"), Input("prev-button", "n_clicks"),
    Input("reset-button", "n_clicks"), Input("play-interval", "n_intervals"),
    State("timeline", "value"), State("play-state", "data"),
)
def move_timeline(run: dict | None, _next: int, _prev: int, _reset: int,
                  _tick: int, value: int | None, active: bool):
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
                               html.Div([html.Strong(english), html.Small(chinese)]),
                               html.Span("→" if index < 4 else "", className="stage-arrow")])
            for index, (number, english, chinese) in enumerate(STAGE_LABELS.values())]


def _parcel_detail(run: dict[str, Any], index: int, parcel_id: str | None) -> Any:
    if not parcel_id or parcel_id not in run["catalog"]:
        return html.P("选择一件包裹查看决策。", className="muted")
    step = run["steps"][index]
    item = run["catalog"][parcel_id]
    state = step["state"]["parcels"].get(parcel_id, {})
    current = step["details"].get(parcel_id, {})
    history = next((prior["details"][parcel_id] for prior in reversed(run["steps"][:index + 1])
                    if prior["stage"] == "settlement" and parcel_id in prior["details"]), {})
    detail = current or history
    stage_index = STAGES.index(step["stage"])
    action = step["decisions"].get(parcel_id)
    sections = [
        html.Div(className="parcel-title", children=[
            html.Div([html.Span("PICKUP PARCEL", className="eyebrow"), html.H3(item["label"])]),
            html.Span(STATUS_LABELS.get(state.get("status"), state.get("status", "—")), className="status-badge"),
        ]),
        html.Div(className="fact-grid", children=[
            html.Div([html.Small("来源平台"), html.Strong(item["origin"])]),
            html.Div([html.Small("服务平台"), html.Strong(state.get("serving_platform") or "—")]),
            html.Div([html.Small("到达 / 期限"), html.Strong(f"{item['arrival_s']} / {item['deadline_s']} s")]),
            html.Div([html.Small("票价"), html.Strong(f"{item['fare']:.2f}")]),
        ]),
    ]
    if stage_index == 0:
        waiting = {
            platform: sum(1 for pid, parcel_state in step["state"]["parcels"].items()
                          if run["catalog"][pid]["origin"] == platform and
                          parcel_state["status"] == "waiting")
            for platform in run["meta"]["platforms"]
        }
        sections.append(html.Div(className="trace-section", children=[
            html.H4("本帧工作量"),
            html.Div(className="workload-chips", children=[
                html.Span(f"{platform} · {count} 件待处理")
                for platform, count in waiting.items()
            ]),
        ]))
    if stage_index >= 1:
        sections.append(html.Div(className="trace-section", children=[
            html.H4("平台分池动作"),
            html.P(action or "本帧无新动作", className="action-value"),
        ]))
    if stage_index >= 2:
        options = detail.get("local_options", [])
        matches = detail.get("local_matches", [])
        selected_vehicles = {match["vehicle_id"] for match in matches}
        sections.append(html.Div(className="trace-section", children=[
            html.H4("本地可行匹配"),
            _table(["候选车辆", "新增距离", "预计取件", "结果"], [
                [option["vehicle_id"], f"{option['extra_km']:.3f} km",
                 f"{option['eta_s']:.0f} s", "✓ 提交" if option["vehicle_id"] in selected_vehicles else "候选"]
                for option in options
            ]) if options else html.P("本帧无本地可行候选或未进入本地池。", className="muted"),
        ]))
    if stage_index >= 3:
        bids = sorted(detail.get("valid_bids", []), key=lambda row: row["amount"])
        candidate_groups = detail.get("intent_candidates", [])
        award = (detail.get("awards") or [None])[0]
        mechanism = run["meta"]["mechanism"]
        rule = ("最低有效报价获胜；多家按次低价支付，单家按自身报价支付" if mechanism == "paper"
                else "固定比例支付机制；选中平台报价与实付可不同")
        sections.append(html.Div(className="trace-section", children=[
            html.H4("跨平台竞价"),
            html.P(rule, className="hint-line"),
            html.Div(className="candidate-line", children=[
                html.Strong("参与候选："),
                "；".join(f"{candidate['platform']} → {', '.join(candidate['vehicle_ids'])}"
                         for candidate in candidate_groups) if candidate_groups else "无候选意向",
            ]),
            _table(["平台", "有效报价", "结果"], [
                [bid["platform"], f"{bid['amount']:.3f}",
                 "✓ 获胜" if award and award["winner"] == bid["platform"] else "未选中"]
                for bid in bids
            ]) if bids else html.P("本帧没有该包裹的有效竞价。", className="muted"),
            html.Div(f"胜者 {award['winner']} · 实付 {award['payment']:.3f} · 有效平台 {award['valid_bidder_count']} 家",
                     className="award-line") if award else None,
        ]))
    if stage_index >= 4:
        receipt = detail.get("origin_receipt")
        serving = detail.get("serving_receipt")
        sections.append(html.Div(className="trace-section", children=[
            html.H4("执行与结算"),
            html.P(f"结果：{detail.get('outcome', '本帧无新结果')}", className="hint-line"),
            html.Div(className="receipt-grid", children=[
                html.Div([html.Small("来源平台单项效用"),
                          html.Strong(f"{receipt['utility']:.3f}" if receipt else
                                      f"{detail['item_utility']:.3f}" if "item_utility" in detail else "—")]),
                html.Div([html.Small("服务车辆"), html.Strong(serving["vehicle_id"] if serving else state.get("vehicle_id") or "—")]),
                html.Div([html.Small("服务平台单项效用"), html.Strong(f"{serving['utility']:.3f}" if serving else "—")]),
                html.Div([html.Small("跨平台支付"), html.Strong(f"{receipt['payment']:.3f}" if receipt and receipt["payment"] is not None else "—")]),
            ]),
        ]))
    return sections


@app.callback(
    Output("map", "figure"), Output("current-metrics", "children"),
    Output("stage-strip", "children"), Output("parcel-details", "children"),
    Output("step-label", "children"), Output("inspection-source", "children"),
    Input("run-store", "data"), Input("timeline", "value"),
    Input("focus-platform", "value"), Input("parcel-picker", "value"),
)
def render_inspection(run: dict | None, index: int | None, focus: str | None, parcel: str | None):
    if not run:
        return (map_figure(None, 0, None, None), [], [],
                html.P("先在 Simulation 运行一个场景。", className="muted"), "等待运行", "未运行")
    index = max(0, min(int(index or 0), len(run["steps"]) - 1))
    step = run["steps"][index]
    metrics = step["metrics"]
    stage = STAGE_LABELS[step["stage"]]
    cards = [
        _metric("当前物理帧", f"{step['batch']:02d}", f"t = {step['decision_time_s']} s"),
        _metric("当前待处理", str(sum(
            parcel_state["status"] == "waiting"
            for parcel_state in step["state"]["parcels"].values()
        )), "所有平台当前观测"),
        _metric("已分配", f"{metrics['assigned']} / {metrics['total']}", "取件包裹"),
        _metric("累计账本", f"{metrics['profit']:.2f}", "全平台"),
    ]
    return (
        map_figure(run, index, focus, parcel), cards, _stage_strip(step["stage"], step["batch"]),
        _parcel_detail(run, index, parcel),
        f"第 {step['batch']} 帧 · {stage[1]} · {index + 1}/{len(run['steps'])}",
        "预计算回放" if run["meta"]["source"] == "replay" else "本次计算 · 阶段回放",
    )


@app.callback(
    Output("final-metrics", "children"), Output("analysis-content", "children"),
    Input("run-store", "data"), Input("focus-platform", "value"),
)
def render_analysis(run: dict | None, focus: str | None):
    if not run:
        return [], html.Div("先运行场景，结果图表将在这里生成。", className="empty-panel")
    summary = run["summary"]
    cards = [
        _metric("已分配 / 总取件", f"{summary['assigned']} / {summary['total']}", f"分配率 {summary['assignment_rate']:.1%}"),
        _metric("本地 / 跨平台", f"{summary['local_count']} / {summary['cross_count']}", "实际提交的匹配"),
        _metric("已取件 / 已卸货", f"{summary['collected']} / {summary['unloaded']}", "完成进度"),
        _metric("经济账本合计", f"{summary['profit']:.2f}", "来源与服务平台合计"),
    ]
    content = html.Div(children=[
        html.Div(className="chart-grid", children=[
            _card("累计经济账本", dcc.Graph(figure=profit_figure(run, focus), config={"displayModeBar": False}), "TIME SERIES"),
            _card("逐平台经济账本", dcc.Graph(figure=platform_profit_figure(run, focus), config={"displayModeBar": False}), "PLATFORM VIEW"),
            _card("取件分配状态", dcc.Graph(figure=status_figure(run), config={"displayModeBar": False}), "OUTCOMES"),
            _card("来源 → 服务平台", dcc.Graph(figure=flow_figure(run), config={"displayModeBar": False}), "COOPERATION FLOW"),
        ]),
        _card("本次运行信息", html.Div(className="meta-grid", children=[
            html.Div([html.Small("数据 / split"), html.Strong(f"{run['meta']['dataset']} / {run['meta']['split']}")]),
            html.Div([html.Small("种子"), html.Strong(str(run['meta']['seed']))]),
            html.Div([html.Small("本地匹配"), html.Strong(run['meta']['matcher'].upper())]),
            html.Div([html.Small("跨平台机制"), html.Strong(run['meta']['mechanism'])]),
            html.Div([html.Small("帧数"), html.Strong(str(len(run['batches'])))]),
        ]), "PROVENANCE"),
    ])
    return cards, content


@app.callback(
    Output("download-json", "data"), Input("download-button", "n_clicks"),
    State("run-store", "data"), prevent_initial_call=True,
)
def download_replay(_clicks: int, run: dict | None):
    if not run:
        return no_update
    return dcc.send_string(json.dumps(run, ensure_ascii=False, indent=2), "maps-replay.json")


def main() -> None:
    app.run(debug=False, host="127.0.0.1", port=8050)


if __name__ == "__main__":
    main()
