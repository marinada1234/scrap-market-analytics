import pandas as pd
import plotly.graph_objects as go


# =====================================================
# УНИВЕРСАЛЬНЫЙ РАСЧЁТ СПРЕДА
# =====================================================

def create_spread_indicator(
    data_1,
    col_1,
    data_2,
    col_2,
    title,
    subtitle,
    spread_direction="first_minus_second"
):

    # Последняя котировка каждого месяца — ряд 1
    first = (
        data_1[["date", col_1]]
        .dropna()
        .sort_values("date")
        .copy()
    )

    first["date"] = pd.to_datetime(first["date"])
    first["month"] = first["date"].dt.to_period("M")

    first = (
        first
        .groupby("month")
        .tail(1)
        [["month", col_1]]
    )


    # Последняя котировка каждого месяца — ряд 2
    second = (
        data_2[["date", col_2]]
        .dropna()
        .sort_values("date")
        .copy()
    )

    second["date"] = pd.to_datetime(second["date"])
    second["month"] = second["date"].dt.to_period("M")

    second = (
        second
        .groupby("month")
        .tail(1)
        [["month", col_2]]
    )


    # Объединяем
    spread = pd.merge(
        first,
        second,
        on="month",
        how="inner"
    )

    spread["date"] = spread["month"].dt.to_timestamp("M")


    # Рассчитываем спред
    if spread_direction == "first_minus_second":

        spread["spread"] = (
            spread[col_1] - spread[col_2]
        )

    else:

        spread["spread"] = (
            spread[col_2] - spread[col_1]
        )


    # =====================================================
    # ИСТОРИЧЕСКИЙ ДИАПАЗОН
    # =====================================================

    p25 = spread["spread"].quantile(0.25)
    p50 = spread["spread"].quantile(0.50)
    p75 = spread["spread"].quantile(0.75)

    current = spread["spread"].iloc[-1]


    # =====================================================
    # СОСТОЯНИЕ
    # =====================================================

    if current > p75:

        deviation = (current / p75 - 1) * 100

        status = (
            f"↑ {deviation:.1f}% выше верхней границы"
        )

    elif current < p25:

        deviation = (current / p25 - 1) * 100

        status = (
            f"↓ {abs(deviation):.1f}% ниже нижней границы"
        )

    else:

        status = "В пределах нормального диапазона"


    # =====================================================
    # ГРАФИК
    # =====================================================

    fig = go.Figure()


    # Верхняя граница
    fig.add_trace(
        go.Scatter(
            x=spread["date"],
            y=[p75] * len(spread),
            mode="lines",
            line=dict(width=0),
            hoverinfo="skip",
            showlegend=False
        )
    )


    # Нормальный диапазон P25-P75
    fig.add_trace(
        go.Scatter(
            x=spread["date"],
            y=[p25] * len(spread),
            mode="lines",
            line=dict(width=0),

            fill="tonexty",
            fillcolor="rgba(34, 197, 94, 0.15)",

            name="Нормальный диапазон P25–P75",

            hoverinfo="skip"
        )
    )


    # Медиана
    fig.add_trace(
        go.Scatter(
            x=spread["date"],
            y=[p50] * len(spread),

            mode="lines",

            name="Медиана",

            line=dict(
                width=1.5,
                dash="dash",
                color="#9CA3AF"
            ),

            hovertemplate=(
                f"Медиана: {p50:,.0f} ₽/т"
                "<extra></extra>"
            )
        )
    )


    # Фактический спред
    fig.add_trace(
        go.Scatter(
            x=spread["date"],
            y=spread["spread"],

            mode="lines",

            name=title,

            line=dict(
                width=2.5,
                color="#F5B942"
            ),

            hovertemplate=(
                "%{x|%m.%Y}<br>"
                "Спред: %{y:,.0f} ₽/т"
                "<extra></extra>"
            )
        )
    )


    # Последняя точка
    fig.add_trace(
        go.Scatter(
            x=[spread["date"].iloc[-1]],
            y=[current],

            mode="markers",

            marker=dict(
                size=10,
                color="#FAFAFA"
            ),

            showlegend=False,

            hovertemplate=(
                "Текущий спред: %{y:,.0f} ₽/т"
                "<extra></extra>"
            )
        )
    )


    # =====================================================
    # ОФОРМЛЕНИЕ
    # =====================================================

    fig.update_layout(

        template="plotly_dark",

        height=450,

        title=dict(
            text=(
                f"<b>{title}</b>"
                "<br>"
                f"<sup>{subtitle}</sup>"
            )
        ),

        hovermode="x unified",

        yaxis_title="₽/т",

        xaxis_title="",

        margin=dict(
            l=10,
            r=10,
            t=70,
            b=10
        ),

        legend=dict(
            orientation="h",
            y=1.02,
            x=0,
            font=dict(size=10)
        )
    )


    return {
        "fig": fig,
        "current": current,
        "p25": p25,
        "p50": p50,
        "p75": p75,
        "status": status,
        "data": spread
    }


# =====================================================
# 1. АРМАТУРА - ЛОМ
# =====================================================

def create_rebar_scrap_indicator(prices):

    return create_spread_indicator(
        prices["rebar"],
        "rebar_price",

        prices["scrap"],
        "scrap_price_ufo",

        title="Арматура − лом",

        subtitle="Ценовое пространство для лома"
    )


# =====================================================
# 2. ЛОМ - ГБЖ
# =====================================================

def create_scrap_hbi_indicator(prices):

    return create_spread_indicator(
        prices["scrap"],
        "scrap_price_ufo",

        prices["hbi"],
        "hbi_price",

        title="Лом − ГБЖ",

        subtitle="Относительная стоимость металлической шихты"
    )


# =====================================================
# 3. ЛОМ - ЧУГУН
# =====================================================

def create_scrap_pig_indicator(prices):

    return create_spread_indicator(
        prices["scrap"],
        "scrap_price_ufo",

        prices["pig"],
        "pig_iron_price",

        title="Лом − чугун",

        subtitle="Относительная стоимость металлической шихты"
    )
from sklearn.linear_model import LinearRegression
import pandas as pd
import numpy as np


def calculate_fair_value(df):
    """
    Модельная цена лома 3А УФО.

    Модель:
    scrap_price_wavg(t) =
        scrap_price_wavg(t-1)
        + hbi_price_wavg(t-1)
        + rebar_price_avg(t-1)

    Спецификация выбрана по walk-forward тесту:
    MAE  = 1280.58 руб./т
    MAPE = 5.42%
    """

    data = df[
        [
            "date",
            "scrap_price_wavg",
            "hbi_price_wavg",
            "rebar_price_avg"
        ]
    ].copy()

    data = data.sort_values("date")

    # лаги на 1 месяц
    data["scrap_lag1"] = data["scrap_price_wavg"].shift(1)
    data["hbi_lag1"] = data["hbi_price_wavg"].shift(1)
    data["rebar_lag1"] = data["rebar_price_avg"].shift(1)

    data = data.dropna().reset_index(drop=True)

    features = [
        "scrap_lag1",
        "hbi_lag1",
        "rebar_lag1"
    ]

    # модель обучаем на всей доступной истории
    model = LinearRegression()

    model.fit(
        data[features],
        data["scrap_price_wavg"]
    )

    # модельная цена для каждого месяца
    data["fair_value"] = model.predict(
        data[features]
    )

    # отклонение фактической цены
    data["fair_value_gap"] = (
        data["scrap_price_wavg"]
        - data["fair_value"]
    )

    data["fair_value_gap_pct"] = (
        data["fair_value_gap"]
        / data["fair_value"]
        * 100
    )

    return data[
        [
            "date",
            "scrap_price_wavg",
            "fair_value",
            "fair_value_gap",
            "fair_value_gap_pct"
        ]
    ]
import plotly.graph_objects as go


def create_fair_value_indicator(df):

    data = calculate_fair_value(df)

    current = data.iloc[-1]

    actual = current["scrap_price_wavg"]
    fair = current["fair_value"]
    gap_pct = current["fair_value_gap_pct"]

    

    # ----------------------------------------------------------
    # ГРАФИК
    # ----------------------------------------------------------

    fig = go.Figure()

    # Фактическая цена
    fig.add_trace(
        go.Scatter(
            x=data["date"],
            y=data["scrap_price_wavg"],
            mode="lines",
            name="Фактическая цена",
            line=dict(
                width=2.5,
                color="#F5B942"
            ),
            hovertemplate=(
                "%{x|%m.%Y}<br>"
                "Факт: %{y:,.0f} ₽/т"
                "<extra></extra>"
            )
        )
    )

    # Модельная цена
    fig.add_trace(
        go.Scatter(
            x=data["date"],
            y=data["fair_value"],
            mode="lines",
            name="Модельная цена",
            line=dict(
                width=2,
                dash="dash",
                color="#00D4C8"
            ),
            hovertemplate=(
                "%{x|%m.%Y}<br>"
                "Модельная цена: %{y:,.0f} ₽/т"
                "<extra></extra>"
            )
        )
    )

    # Последняя фактическая точка
    fig.add_trace(
        go.Scatter(
            x=[current["date"]],
            y=[actual],
            mode="markers",
            showlegend=False,
            marker=dict(
                size=11,
                color="#FAFAFA"
            ),
            hovertemplate=(
                "Факт: %{y:,.0f} ₽/т"
                "<extra></extra>"
            )
        )
    )

    fig.update_layout(
    title=None,
    height=430,
    margin=dict(
        l=20,
        r=20,
        t=30,
        b=20
    ),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    hovermode="x unified",
    legend=dict(
        orientation="h",
        y=1.02,
        x=0
    ),
    xaxis=dict(
        showgrid=False
    ),
    yaxis=dict(
        title="₽/т",
        gridcolor="rgba(255,255,255,0.08)",
        tickformat=","
    )
)
    return fig
def calculate_spread_zscore(fair_df):

    data = fair_df.copy()

    window = 12

    data["spread_mean"] = (
        data["fair_value_gap"]
        .rolling(window)
        .mean()
    )

    data["spread_std"] = (
        data["fair_value_gap"]
        .rolling(window)
        .std()
    )

    data["spread_z"] = (
        data["fair_value_gap"]
        - data["spread_mean"]
    ) / data["spread_std"]

    return data
def create_scrap_zscore_indicator(df):

    fair = calculate_fair_value(df)

    data = calculate_spread_zscore(fair)

    data = data.dropna(
        subset=["spread_z"]
    )

    current = data.iloc[-1]

    z = current["spread_z"]

    # -----------------------------
    # Сигнал
    # -----------------------------

    if z >= 1.5:
        status = f"↑ Перегрев: Z-score {z:.2f}"
        signal = "negative"

    elif z <= -1.5:
        status = f"↓ Недооценка: Z-score {z:.2f}"
        signal = "positive"

    else:
        status = f"Норма: Z-score {z:.2f}"
        signal = "neutral"

    # -----------------------------
    # График
    # -----------------------------

    fig = go.Figure()

    # зона перегрева
    fig.add_hrect(
        y0=1.5,
        y1=3,
        fillcolor="rgba(239,68,68,0.15)",
        line_width=0
    )

    # зона недооценки
    fig.add_hrect(
        y0=-3,
        y1=-1.5,
        fillcolor="rgba(34,197,94,0.15)",
        line_width=0
    )

    # верхний порог
    fig.add_hline(
        y=1.5,
        line_dash="dash",
        line_color="#EF4444"
    )

    # нижний порог
    fig.add_hline(
        y=-1.5,
        line_dash="dash",
        line_color="#00D4C8"
    )

    # нулевая линия
    fig.add_hline(
        y=0,
        line_color="#FAFAFA",
        line_width=2
    )

    # Z-score
    fig.add_trace(
        go.Scatter(
            x=data["date"],
            y=data["spread_z"],
            mode="lines",
            name="Z-score",
            line=dict(
                width=2.5,
                color="#A855F7"
            ),
            hovertemplate=(
                "%{x|%m.%Y}<br>"
                "Z-score: %{y:.2f}"
                "<extra></extra>"
            )
        )
    )

    # текущая точка
    fig.add_trace(
        go.Scatter(
            x=[current["date"]],
            y=[z],
            mode="markers",
            name="Текущее значение",
            marker=dict(
                size=11,
                color="#FAFAFA",
                line=dict(
                    width=2,
                    color="#A855F7"
                )
            ),
            hovertemplate=(
                "Z-score: %{y:.2f}"
                "<extra></extra>"
            )
        )
    )

    fig.update_layout(
        title="Перегрев / недооценка рынка лома",
        height=430,
        margin=dict(
            l=20,
            r=20,
            t=60,
            b=20
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",

        yaxis=dict(
            title="Отклонение от модельной цены (σ)",
            range=[-3, 3],
            gridcolor="rgba(255,255,255,0.08)"
        ),

        xaxis=dict(
            showgrid=False
        ),

        legend=dict(
            orientation="h",
            y=1.02,
            x=0
        )
    )

    return fig, status, signal
def calculate_market_pressure_scrap(df):

    data = df.copy()
    data = data.sort_values("date")

    # Месячные изменения
    data["rebar_chg"] = data["rebar_price_avg"].pct_change()
    data["eaf_chg"] = data["eaf_production_ru"].pct_change()
    data["supply_chg"] = data["scrap_supply_ru"].pct_change()

    def normalize(x):
        return (x - x.mean()) / x.std()

    data["rebar_norm"] = normalize(data["rebar_chg"])
    data["eaf_norm"] = normalize(data["eaf_chg"])
    data["supply_norm"] = normalize(data["supply_chg"])

    # Индекс рыночного давления
    data["market_pressure"] = (
        0.40 * data["rebar_norm"]
        + 0.35 * data["eaf_norm"]
        + 0.25 * data["supply_norm"]
    )

    return data
