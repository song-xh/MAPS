"""Plotly views of one recorded MPCS episode."""

from __future__ import annotations

from collections import Counter
from math import cos, pi, sin
from typing import Any

import plotly.graph_objects as go


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
        font=dict(family="Microsoft YaHei, Segoe UI, sans-serif", color="#334155", size=12),
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


def map_figure(run: dict[str, Any] | None, index: int, focus: str | None, selected: str | None) -> go.Figure:
    figure = go.Figure()
    if not run:
        figure.add_annotation(text="运行一个场景后，包裹与车辆会出现在这里", showarrow=False,
                              font=dict(size=16, color="#94a3b8"))
        return _theme(figure, height=525)
    step = run["steps"][index]
    platforms = run["meta"]["platforms"]
    catalog = run["catalog"]
    state = step["state"]
    visible = {
        parcel_id: item for parcel_id, item in catalog.items()
        if item["arrival_s"] <= step["decision_time_s"] or
        state["parcels"].get(parcel_id, {}).get("status") != "future"
    }
    point_items = [(f"parcel:{pid}", item["point"]) for pid, item in visible.items()]
    point_items += [(f"vehicle:{vid}", item["point"]) for vid, item in state["vehicles"].items()]
    positions = _spread(point_items)
    if step["stage"] in {"local", "auction", "settlement"}:
        for parcel_id, detail in step["details"].items():
            if parcel_id not in visible:
                continue
            links = detail.get("local_matches", ())
            if step["stage"] in {"auction", "settlement"} and detail.get("serving_receipt"):
                links = [detail["serving_receipt"]]
            for link in links:
                vehicle_id = link["vehicle_id"]
                if f"vehicle:{vehicle_id}" not in positions:
                    continue
                x0, y0 = positions[f"parcel:{parcel_id}"]
                x1, y1 = positions[f"vehicle:{vehicle_id}"]
                cross = state["vehicles"][vehicle_id]["platform"] != catalog[parcel_id]["origin"]
                figure.add_trace(go.Scatter(
                    x=[x0, x1], y=[y0, y1], mode="lines", showlegend=False,
                    line=dict(color="#f97316" if cross else "#10b981", width=3 if parcel_id == selected else 1.8,
                              dash="dot" if cross else "solid"),
                    hoverinfo="skip",
                ))
    for platform in platforms:
        parcel_ids = [pid for pid, item in visible.items() if item["origin"] == platform]
        if parcel_ids:
            figure.add_trace(go.Scatter(
                x=[positions[f"parcel:{pid}"][0] for pid in parcel_ids],
                y=[positions[f"parcel:{pid}"][1] for pid in parcel_ids],
                mode="markers+text", name=f"{platform} 包裹", legendgroup=platform,
                text=[visible[pid]["label"] if pid == selected else "" for pid in parcel_ids],
                textposition="top center", textfont=dict(size=11, color="#0f172a"),
                marker=dict(
                    symbol="circle", size=[19 if pid == selected else 13 for pid in parcel_ids],
                    color=color_for(platform, platforms),
                    opacity=[1 if state["parcels"].get(pid, {}).get("status") not in {"expired"} else 0.35 for pid in parcel_ids],
                    line=dict(color="#0f172a" if platform == focus else "white", width=2.3 if platform == focus else 1),
                ),
                customdata=[["parcel", pid, visible[pid]["label"]] for pid in parcel_ids],
                hovertemplate="<b>%{customdata[2]}</b><br>%{customdata[1]}<extra></extra>",
            ))
        vehicle_ids = [vid for vid, item in state["vehicles"].items() if item["platform"] == platform]
        if vehicle_ids:
            figure.add_trace(go.Scatter(
                x=[positions[f"vehicle:{vid}"][0] for vid in vehicle_ids],
                y=[positions[f"vehicle:{vid}"][1] for vid in vehicle_ids],
                mode="markers", name=f"{platform} 车辆", legendgroup=platform, showlegend=False,
                marker=dict(symbol="square", size=13, color=color_for(platform, platforms),
                            line=dict(color="#0f172a" if platform == focus else "white", width=2)),
                customdata=[["vehicle", vid] for vid in vehicle_ids],
                hovertemplate="<b>%{customdata[1]}</b><extra></extra>",
            ))
    figure.update_xaxes(showgrid=True, gridcolor="#e9eff6", zeroline=False, title="经度 / 显示错位")
    figure.update_yaxes(showgrid=True, gridcolor="#e9eff6", zeroline=False, title="纬度 / 显示错位",
                        scaleanchor="x", scaleratio=1)
    figure.update_layout(
        dragmode="pan", uirevision="maps-location", hovermode="closest",
        annotations=[dict(x=1, y=1.04, xref="paper", yref="paper", showarrow=False,
                          text="○ 包裹    ■ 车辆    ─ 本地匹配    ··· 跨平台匹配",
                          font=dict(size=11, color="#64748b"), xanchor="right")],
    )
    return _theme(figure, height=525, margin=38)


def profit_figure(run: dict[str, Any], focus: str | None) -> go.Figure:
    batches = run["batches"]
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=[item["time_s"] for item in batches], y=[item["profit"] for item in batches],
        mode="lines+markers", name="全平台", line=dict(color="#2563eb", width=3),
        fill="tozeroy", fillcolor="rgba(37,99,235,0.08)",
        hovertemplate="t=%{x}s<br>账本合计=%{y:.2f}<extra></extra>",
    ))
    if focus:
        figure.add_trace(go.Scatter(
            x=[item["time_s"] for item in batches],
            y=[item["profit_by_platform"].get(focus, 0) for item in batches],
            mode="lines+markers", name=focus,
            line=dict(color=color_for(focus, run["meta"]["platforms"]), width=2, dash="dot"),
            hovertemplate=f"{focus}：%{{y:.2f}}<extra></extra>",
        ))
    figure.update_xaxes(title="模拟时间 / s", gridcolor="#e9eff6")
    figure.update_yaxes(title="经济账本金额", gridcolor="#e9eff6")
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
        hovertemplate="%{x}<br>账本金额=%{y:.2f}<extra></extra>",
    ))
    figure.update_yaxes(title="经济账本金额", gridcolor="#e9eff6")
    return _theme(figure)


def status_figure(run: dict[str, Any]) -> go.Figure:
    summary = run["summary"]
    labels = ["本地分配", "跨平台分配", "过期", "未分配"]
    values = [summary["local_count"], summary["cross_count"], summary["expired"],
              max(0, summary["total"] - summary["assigned"] - summary["expired"])]
    figure = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        showlegend=False,
        marker_color=["#10b981", "#f97316", "#ef4444", "#94a3b8"],
        text=values, textposition="outside",
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    figure.update_xaxes(title="取件包裹数", gridcolor="#e9eff6")
    figure.update_yaxes(autorange="reversed")
    return _theme(figure)


def flow_figure(run: dict[str, Any]) -> go.Figure:
    platforms = run["meta"]["platforms"]
    final_parcels = run["steps"][-1]["state"]["parcels"]
    counts: Counter[tuple[str, str]] = Counter()
    for parcel_id, state in final_parcels.items():
        serving = state["serving_platform"]
        if serving:
            counts[(run["catalog"][parcel_id]["origin"], serving)] += 1
    figure = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            pad=18, thickness=16,
            label=[f"来源 {platform}" for platform in platforms] + [f"服务 {platform}" for platform in platforms],
            color=[color_for(platform, platforms) for platform in platforms] * 2,
        ),
        link=dict(
            source=[platforms.index(origin) for origin, _ in counts],
            target=[len(platforms) + platforms.index(serving) for _, serving in counts],
            value=list(counts.values()),
            color=["rgba(249,115,22,0.45)" if origin != serving else "rgba(16,185,129,0.34)"
                   for origin, serving in counts],
            hovertemplate="%{source.label} → %{target.label}<br>%{value} 件<extra></extra>",
        ),
    ))
    return _theme(figure, height=350)
