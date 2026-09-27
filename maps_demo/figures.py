"""Plotly views of one recorded MPCS episode."""

from __future__ import annotations

from collections import Counter
from math import cos, pi, sin
from typing import Any

import plotly.graph_objects as go

from maps_demo.engine import clock_time

PLATFORM_COLORS = (
    "#1677ff", "#f59e0b", "#10b981", "#a855f7",
    "#ef4444", "#06b6d4", "#d97706", "#6366f1",
    "#84cc16", "#ec4899", "#14b8a6", "#8b5cf6",
    "#eab308", "#0ea5e9", "#f97316", "#64748b",
)


def color_for(platform: str, platforms: list[str]) -> str:
    return PLATFORM_COLORS[platforms.index(platform) % len(PLATFORM_COLORS)]


def _theme(figure: go.Figure, *, height: int = 310, margin: int = 30) -> go.Figure:
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Segoe UI, sans-serif", color="#334155", size=12),
        margin=dict(l=margin, r=margin, t=25, b=35),
        height=height,
        showlegend=True,
        legend=dict(orientation="h", y=-0.05, x=0, font=dict(size=11)),
        hoverlabel=dict(bgcolor="#111827", font=dict(color="white")),
    )
    return figure


def _spread(points: list[tuple[str, list[float]]]) -> dict[str, tuple[float, float]]:
    """Separate identical displayed coordinates while keeping the real point in hover text."""
    grouped: dict[tuple[float, float], list[str]] = {}
    for identity, point in points:
        grouped.setdefault((point[0], point[1]), []).append(identity)
    located = {}
    for (x, y), identities in grouped.items():
        for index, identity in enumerate(identities):
            if len(identities) == 1:
                located[identity] = (x, y)
            else:
                angle = 2 * pi * index / len(identities)
                radius = 0.000065 + 0.00002 * (index // 9)
                located[identity] = (x + radius * cos(angle), y + radius * sin(angle))
    return located


def map_static_trace_count(run: dict[str, Any], layers: list[str] | None) -> int:
    active = set(layers) if layers is not None else {"road", "station"}
    geography = run.get("geography", {})
    return int("road" in active and bool(geography.get("segments"))) + int(
        "station" in active and bool(geography.get("stations"))
    )


def map_dynamic_traces(run: dict[str, Any], index: int, focus: str | None,
                       selected: str | None) -> list[go.Scatter]:
    step = run["steps"][index]
    platforms = run["meta"]["platforms"]
    catalog = run["catalog"]
    state = step["state"]
    visible = {
        parcel_id: item for parcel_id, item in catalog.items()
        if state["parcels"].get(parcel_id, {}).get("status")
        in {"waiting", "public_this_step", "cross_pool"}
    }
    point_items = [(f"parcel:{pid}", item["point"]) for pid, item in visible.items()]
    point_items += [(f"vehicle:{vid}", item["point"]) for vid, item in state["vehicles"].items()]
    positions = _spread(point_items)
    links = {(cross, highlighted): ([], []) for cross in (False, True)
             for highlighted in (False, True)}
    if step["stage"] in {"local", "auction", "settlement"}:
        for parcel_id, detail in step["details"].items():
            if parcel_id not in visible:
                continue
            matches = detail.get("local_matches", ())
            if step["stage"] in {"auction", "settlement"} and detail.get("serving_receipt"):
                matches = [detail["serving_receipt"]]
            for match in matches:
                vehicle_id = match["vehicle_id"]
                if f"vehicle:{vehicle_id}" not in positions:
                    continue
                cross = state["vehicles"][vehicle_id]["platform"] != catalog[parcel_id]["origin"]
                xs, ys = links[(cross, parcel_id == selected)]
                x0, y0 = positions[f"parcel:{parcel_id}"]
                x1, y1 = positions[f"vehicle:{vehicle_id}"]
                xs.extend((x0, x1, None))
                ys.extend((y0, y1, None))
    traces: list[go.Scatter] = []
    for cross in (False, True):
        for highlighted in (False, True):
            xs, ys = links[(cross, highlighted)]
            traces.append(go.Scatter(
                x=xs, y=ys, mode="lines", showlegend=False,
                line=dict(color="#f97316" if cross else "#10b981",
                          width=3 if highlighted else 1.8,
                          dash="dot" if cross else "dash"),
                hoverinfo="skip",
            ))
    for platform in platforms:
        route_x, route_y = [], []
        for vehicle in state["vehicles"].values():
            if vehicle["platform"] != platform:
                continue
            navigation = vehicle.get("navigation", [])
            if len(navigation) > 1:
                route_x.extend([point[0] for point in navigation] + [None])
                route_y.extend([point[1] for point in navigation] + [None])
        traces.append(go.Scatter(
            x=route_x, y=route_y, mode="lines", showlegend=False,
            line=dict(color=color_for(platform, platforms), width=2.5 if platform == focus else 1.4),
            opacity=0.72 if platform == focus else 0.36, hoverinfo="skip",
        ))
    for platform in platforms:
        parcel_ids = [pid for pid, item in visible.items() if item["origin"] == platform]
        traces.append(go.Scatter(
            x=[positions[f"parcel:{pid}"][0] for pid in parcel_ids],
            y=[positions[f"parcel:{pid}"][1] for pid in parcel_ids],
            mode="markers+text", name=f"{platform} parcels", legendgroup=platform,
            showlegend=bool(parcel_ids),
            text=[visible[pid]["label"] if pid == selected else "" for pid in parcel_ids],
            textposition="top center", textfont=dict(size=11, color="#0f172a"),
            marker=dict(
                symbol="circle", size=[19 if pid == selected else 13 for pid in parcel_ids],
                color=color_for(platform, platforms),
                line=dict(color="#0f172a" if platform == focus else "white", width=2.3 if platform == focus else 1),
            ),
            customdata=[["parcel", pid, visible[pid]["label"]] for pid in parcel_ids],
            hovertemplate="<b>%{customdata[2]}</b><br>%{customdata[1]}<extra></extra>",
        ))
        vehicle_ids = [vid for vid, item in state["vehicles"].items() if item["platform"] == platform]
        traces.append(go.Scatter(
            x=[positions[f"vehicle:{vid}"][0] for vid in vehicle_ids],
            y=[positions[f"vehicle:{vid}"][1] for vid in vehicle_ids],
            mode="markers", name=f"{platform} EVs", legendgroup=platform, showlegend=False,
            marker=dict(symbol="square", size=13, color=color_for(platform, platforms),
                        line=dict(color="#0f172a" if platform == focus else "white", width=2)),
            customdata=[["vehicle", vid] for vid in vehicle_ids],
            hovertemplate="<b>%{customdata[1]}</b><extra></extra>",
        ))
    return traces


def map_figure(run: dict[str, Any] | None, index: int, focus: str | None,
               selected: str | None, layers: list[str] | None = None) -> go.Figure:
    figure = go.Figure()
    if not run:
        figure.add_annotation(text="Run a scenario to view parcels and EVs", showarrow=False,
                              font=dict(size=16, color="#94a3b8"))
        return _theme(figure, height=525)
    active_layers = set(layers) if layers is not None else {"road", "station"}
    geography = run.get("geography", {})
    if "road" in active_layers and geography.get("segments"):
        road_x: list[float | None] = []
        road_y: list[float | None] = []
        for x0, y0, x1, y1 in geography["segments"]:
            road_x.extend((x0, x1, None))
            road_y.extend((y0, y1, None))
        figure.add_trace(go.Scattergl(
            x=road_x, y=road_y, mode="lines", name="Processed roads",
            legendgroup="geography", showlegend=False, hoverinfo="skip",
            line=dict(color="#b8c8d8", width=1.3),
        ))
    if "station" in active_layers and geography.get("stations"):
        stations = geography["stations"]
        station_size = 8 if len(stations) > 20 else 12
        figure.add_trace(go.Scattergl(
            x=[item["point"][0] for item in stations],
            y=[item["point"][1] for item in stations],
            mode="markers", name="Station", legendgroup="geography", showlegend=False,
            marker=dict(symbol="diamond", size=station_size, color="#254d88", opacity=0.8,
                        line=dict(color="white", width=0.8)),
            customdata=[[item["id"], item["node"]] for item in stations],
            hovertemplate="Station %{customdata[0]}<br>Road node %{customdata[1]}<extra></extra>",
        ))
    for trace in map_dynamic_traces(run, index, focus, selected):
        figure.add_trace(trace)
    figure.update_xaxes(showgrid=True, gridcolor="#e9eff6", zeroline=False, title="Longitude")
    figure.update_yaxes(showgrid=True, gridcolor="#e9eff6", zeroline=False, title="Latitude",
                        scaleanchor="x", scaleratio=1)
    figure.update_layout(
        dragmode="pan", uirevision=run["meta"]["dataset"], hovermode="closest",
        legend=dict(entrywidth=115, entrywidthmode="pixels", y=-0.18),
    )
    figure = _theme(figure, height=535, margin=56)
    figure.update_layout(margin=dict(l=65, r=25, t=25, b=82), legend=dict(y=-0.2))
    return figure


def _analysis_batches(run: dict[str, Any]) -> list[dict[str, Any]]:
    end = run["meta"].get("analysis_end_s")
    return [item for item in run["batches"] if end is None or item["decision_time_s"] < end]


def _clock_axis(figure: go.Figure, seconds: list[int], title: str = "Time") -> None:
    if not seconds:
        return
    first = min(seconds) // 60
    last = max(seconds) // 60
    stride = max(1, (last - first + 1) // 8)
    ticks = list(range(first, last + 1, stride))
    if ticks[-1] != last:
        ticks.append(last)
    figure.update_xaxes(title=title, tickmode="array", tickvals=[minute * 60 for minute in ticks],
                        ticktext=[clock_time(minute * 60) for minute in ticks], gridcolor="#e9eff6")


def profit_figure(run: dict[str, Any], focus: str | None) -> go.Figure:
    batches = _analysis_batches(run)
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=[item["decision_time_s"] for item in batches], y=[item["profit"] for item in batches],
        mode="lines+markers", name="All platforms", line=dict(color="#2563eb", width=3),
        fill="tozeroy", fillcolor="rgba(37,99,235,0.08)",
        customdata=[clock_time(item["decision_time_s"]) for item in batches],
        hovertemplate="%{customdata}<br>Ledger total=%{y:.2f}<extra></extra>",
    ))
    if focus:
        figure.add_trace(go.Scatter(
            x=[item["decision_time_s"] for item in batches],
            y=[item["profit_by_platform"].get(focus, 0) for item in batches],
            mode="lines+markers", name=focus,
            line=dict(color=color_for(focus, run["meta"]["platforms"]), width=2, dash="dot"),
            customdata=[clock_time(item["decision_time_s"]) for item in batches],
            hovertemplate=f"{focus} at %{{customdata}}: %{{y:.2f}}<extra></extra>",
        ))
    _clock_axis(figure, [batches[0]["decision_time_s"],
                         run["meta"].get("analysis_end_s", batches[-1]["time_s"])])
    figure.update_xaxes(range=[batches[0]["decision_time_s"],
                               run["meta"].get("analysis_end_s", batches[-1]["time_s"])])
    figure.update_yaxes(title="Ledger profit", gridcolor="#e9eff6")
    return _theme(figure)


def minute_profit_figure(run: dict[str, Any], focus: str | None) -> go.Figure:
    batches = _analysis_batches(run)
    if not batches:
        return _theme(go.Figure())
    start_minute = batches[0]["decision_time_s"] // 60
    end_minute = (run["meta"].get("analysis_end_s", batches[-1]["time_s"]) - 1) // 60
    minutes = list(range(start_minute, end_minute + 1))
    totals = {minute: 0.0 for minute in minutes}
    platform_totals = {minute: 0.0 for minute in minutes}
    previous = 0.0
    previous_focus = 0.0
    for item in batches:
        minute = item["decision_time_s"] // 60
        totals[minute] += item["profit"] - previous
        previous = item["profit"]
        current_focus = item["profit_by_platform"].get(focus, 0.0) if focus else 0.0
        platform_totals[minute] += current_focus - previous_focus
        previous_focus = current_focus
    figure = go.Figure()
    figure.add_trace(go.Bar(
        x=[minute * 60 for minute in minutes], y=[totals[minute] for minute in minutes],
        name="All platforms", marker_color="#3b82f6", width=48,
        customdata=[clock_time(minute * 60) for minute in minutes],
        hovertemplate="%{customdata}–next minute<br>Profit=%{y:.2f}<extra></extra>",
    ))
    if focus:
        figure.add_trace(go.Scatter(
            x=[minute * 60 for minute in minutes], y=[platform_totals[minute] for minute in minutes],
            name=focus, mode="lines+markers", line=dict(color=color_for(focus, run["meta"]["platforms"]), width=2),
            customdata=[clock_time(minute * 60) for minute in minutes],
            hovertemplate=f"{focus} at %{{customdata}}: %{{y:.2f}}<extra></extra>",
        ))
    _clock_axis(figure, [minute * 60 for minute in minutes], "Minute")
    figure.update_xaxes(range=[minutes[0] * 60 - 50, minutes[-1] * 60 + 50])
    figure.update_yaxes(title="Profit in minute", gridcolor="#e9eff6")
    return _theme(figure)


def platform_profit_figure(run: dict[str, Any], focus: str | None) -> go.Figure:
    platforms = run["meta"]["platforms"]
    totals = run["summary"]["profit_by_platform"]
    figure = go.Figure(go.Bar(
        x=platforms, y=[totals.get(platform, 0) for platform in platforms],
        showlegend=False,
        marker=dict(color=[color_for(platform, platforms) for platform in platforms],
                    line=dict(color=["#0f172a" if platform == focus else "white" for platform in platforms], width=2)),
        text=[f"{totals.get(platform, 0):.2f}" for platform in platforms], textposition="outside",
        hovertemplate="%{x}<br>Ledger profit=%{y:.2f}<extra></extra>",
    ))
    figure.update_yaxes(title="Ledger profit", gridcolor="#e9eff6")
    return _theme(figure)


def status_figure(run: dict[str, Any]) -> go.Figure:
    summary = run["summary"]
    labels = ["Local assignment", "Cross-platform assignment", "Expired", "Unassigned"]
    values = [summary["local_count"], summary["cross_count"], summary["expired"],
              max(0, summary["total"] - summary["assigned"] - summary["expired"])]
    figure = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        showlegend=False,
        marker_color=["#10b981", "#f97316", "#ef4444", "#94a3b8"],
        text=values, textposition="outside",
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    figure.update_xaxes(title="Pickup parcels", gridcolor="#e9eff6")
    figure.update_yaxes(autorange="reversed")
    return _theme(figure)


def flow_figure(run: dict[str, Any]) -> go.Figure:
    platforms = run["meta"]["platforms"]
    flow_index = run["summary"].get("flow_step_index", len(run["steps"]) - 1)
    final_parcels = run["steps"][flow_index]["state"]["parcels"]
    counts: Counter[tuple[str, str]] = Counter()
    for parcel_id, state in final_parcels.items():
        serving = state["serving_platform"]
        if serving:
            counts[(run["catalog"][parcel_id]["origin"], serving)] += 1
    figure = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            pad=18, thickness=16,
            label=[f"Origin {platform}" for platform in platforms] + [f"Serving {platform}" for platform in platforms],
            color=[color_for(platform, platforms) for platform in platforms] * 2,
        ),
        link=dict(
            source=[platforms.index(origin) for origin, _ in counts],
            target=[len(platforms) + platforms.index(serving) for _, serving in counts],
            value=list(counts.values()),
            color=["rgba(249,115,22,0.45)" if origin != serving else "rgba(16,185,129,0.34)"
                   for origin, serving in counts],
            hovertemplate="%{source.label} → %{target.label}<br>%{value} parcels<extra></extra>",
        ),
    ))
    return _theme(figure, height=350)
