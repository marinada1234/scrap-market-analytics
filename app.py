import streamlit as st
import pandas as pd

from data_loader import (
    load_market_data,
    load_price_indicators
)

import streamlit as st
import pandas as pd

from data_loader import (
    load_market_data,
    load_price_indicators,
    load_fair_value_data
)
from charts import create_market_chart
from forecast_model import build_forecast


from indicators import (
    create_rebar_scrap_indicator,
    create_scrap_hbi_indicator,
    create_scrap_pig_indicator,
    create_fair_value_indicator,
    create_scrap_zscore_indicator,
    calculate_fair_value,
    calculate_spread_zscore

)
from market_commentary import generate_scrap_commentary

from ai_commentary import generate_scrap_ai_commentary
# ======================================================
# СТИЛЬ ПАНЕЛЕЙ
# ======================================================
st.markdown(
    """
    <style>

    /* Наши две панели */
    div[data-testid="stVerticalBlock"]:has(> div .price-panel-marker),
    div[data-testid="stVerticalBlock"]:has(> div .demand-panel-marker) {
        border: 2px solid #00D4C8 !important;
        border-radius: 12px !important;
        padding: 16px !important;
        margin-top: 8px !important;
        margin-bottom: 18px !important;
    }

    /* Убираем рамку у самого внешнего блока страницы */
    section[data-testid="stMain"] > div > div[data-testid="stVerticalBlock"] {
        border: none !important;
    }

    .price-panel-marker,
    .demand-panel-marker {
        display: none;
    }

    </style>
    """,
    unsafe_allow_html=True
)
# ======================================================
# ЗАГРУЗКА ДАННЫХ
# ======================================================

# ======================================================
# КЭШИРОВАНИЕ ДАННЫХ
# ======================================================

@st.cache_data(ttl=43200)
def get_market_data():
    return load_market_data()


@st.cache_data(ttl=43200)
def get_price_indicators():
    return load_price_indicators()

@st.cache_data(ttl=43200)
def get_fair_value_data():
    return load_fair_value_data()

fair_value_data = get_fair_value_data()
df = get_market_data()
prices = get_price_indicators()

forecast_df = build_forecast(prices["scrap"])

# ==================================================
# РЕШЕНИЕ СИСТЕМЫ
# ==================================================

fair_result = calculate_fair_value(
    fair_value_data
)

fair_result = calculate_spread_zscore(
    fair_result
)

fair_current = (
    fair_result
    .dropna(subset=["spread_z"])
    .iloc[-1]
)

# Среднемесячная цена — для сравнения с fair value
fair_actual_price = float(
    fair_current["scrap_price_wavg"]
)

fair_value = float(
    fair_current["fair_value"]
)

spread_z = float(
    fair_current["spread_z"]
)

# Последняя фактическая котировка — для прогноза ARIMA
current_price = float(
    prices["scrap"]
    .dropna(subset=["scrap_price_ufo"])
    .sort_values("date")
    ["scrap_price_ufo"]
    .iloc[-1]
)

# Прогноз ARIMA на следующий месяц
forecast_next_month = float(
    forecast_df["forecast_price"].iloc[0]
)


# ==================================================
# ФАКТИЧЕСКИЙ КРАТКОСРОЧНЫЙ ТРЕНД ЦЕНЫ ЛОМА
# ==================================================

scrap_history = (
    prices["scrap"]
    .dropna(subset=["scrap_price_ufo"])
    .sort_values("date")
    [["date", "scrap_price_ufo"]]
    .tail(5)
    .copy()
)

scrap_history["change"] = (
    scrap_history["scrap_price_ufo"].pct_change() * 100
)

trend_start_date = scrap_history["date"].iloc[0]
trend_end_date = scrap_history["date"].iloc[-1]

changes = scrap_history["change"].dropna()

# Суммарное изменение от первой до последней точки
trend_change_pct = (
    (
        scrap_history["scrap_price_ufo"].iloc[-1]
        / scrap_history["scrap_price_ufo"].iloc[0]
        - 1
    )
    * 100
)

negative_moves = int((changes < 0).sum())
positive_moves = int((changes > 0).sum())

# Тренд считаем устойчивым, если минимум
# 3 из 4 последних движений направлены одинаково

if negative_moves >= 3 and trend_change_pct <= -1:

    price_trend = "down"

elif positive_moves >= 3 and trend_change_pct >= 1:

    price_trend = "up"

else:

    price_trend = "sideways"

commentary = generate_scrap_commentary(
    current_price=current_price,
    fair_actual_price=fair_actual_price,
    fair_value=fair_value,
    spread_z=spread_z,
    forecast_next_month=forecast_next_month,
    price_trend=price_trend,
    trend_change_pct=trend_change_pct,
    trend_start_date=trend_start_date,
    trend_end_date=trend_end_date
)
# ==================================================
# AI-КОММЕНТАРИЙ
# ==================================================

fair_value_diff_pct = (
    (fair_actual_price - fair_value)
    / fair_value
    * 100
)

forecast_change_pct = (
    (forecast_next_month - current_price)
    / current_price
    * 100
)

# ======================================================
# НАСТРОЙКИ ГРАФИКА
# ======================================================

NAMES = {
    "scrap_price_end": "♻️ Лом 3А УФО",
    "scrap_price_index_rf": "🇷🇺 Индекс лома РФ",
    "rebar_price_end": "🏗 Арматура А3",
    "hbi_price_end": "🔥 ГБЖ",
    "pig_iron_price_end": "⚫ Чугун",
    "billet_fob_rub_end": "🌍 Заготовка FOB Турция",
    "scrap_supply_ru": "🚚 Поставки лома РФ",
    "scrap_supply_ufo": "🚚 Поставки лома УФО",
    "eaf_production_ru": "⚡ Электросталь РФ",
    "eaf_production_ufo": "⚡ Электросталь УФО"
}


COLORS = {
    "scrap_price_end": "#00D4C8",
    "scrap_price_index_rf": "#00A6FF",
    "rebar_price_end": "#22C55E",
    "hbi_price_end": "#FF9800",
    "pig_iron_price_end": "#A855F7",
    "billet_fob_rub_end": "#E91E63",
    "scrap_supply_ru": "#FFD54F",
    "scrap_supply_ufo": "#FF7043",
    "eaf_production_ru": "#66BB6A",
    "eaf_production_ufo": "#42A5F5"
}

def prepare_chart_data(df, prices):

    # Месячная основа: поставки и электросталь
    chart = df[
        [
            "date",
            "scrap_supply_ru",
            "scrap_supply_ufo",
            "eaf_production_ru",
            "eaf_production_ufo"
        ]
    ].copy()

    chart["date"] = pd.to_datetime(chart["date"]).dt.to_period("M")

    # --------------------------------------------------
    # Последняя котировка каждого месяца
    # --------------------------------------------------

    def monthly_last(data, source_col, target_col):

        temp = data[["date", source_col]].dropna().copy()
        temp["date"] = pd.to_datetime(temp["date"])

        temp = (
            temp.sort_values("date")
            .groupby(temp["date"].dt.to_period("M"))
            .tail(1)
        )

        temp["date"] = temp["date"].dt.to_period("M")

        return temp[
            ["date", source_col]
        ].rename(columns={source_col: target_col})


    # Лом УФО
    chart = chart.merge(
        monthly_last(
            prices["scrap"],
            "scrap_price_ufo",
            "scrap_price_end"
        ),
        on="date",
        how="outer"
    )

    # Индекс лома РФ
    chart = chart.merge(
        monthly_last(
            prices["scrap_index"],
            "scrap_index_current",
            "scrap_price_index_rf"
        ),
        on="date",
        how="outer"
    )

    # Арматура
    chart = chart.merge(
        monthly_last(
            prices["rebar"],
            "rebar_price",
            "rebar_price_end"
        ),
        on="date",
        how="outer"
    )

    # ГБЖ
    chart = chart.merge(
        monthly_last(
            prices["hbi"],
            "hbi_price",
            "hbi_price_end"
        ),
        on="date",
        how="outer"
    )

    # Чугун
    chart = chart.merge(
        monthly_last(
            prices["pig"],
            "pig_iron_price",
            "pig_iron_price_end"
        ),
        on="date",
        how="outer"
    )

    # Заготовка
    chart = chart.merge(
        monthly_last(
            prices["billet"],
            "billet_fob_rub",
            "billet_fob_rub_end"
        ),
        on="date",
        how="outer"
    )

    # Возвращаем обычную дату
    chart["date"] = chart["date"].dt.to_timestamp("M")

    return chart.sort_values("date").reset_index(drop=True)
# ======================================================
# НАСТРОЙКА СТРАНИЦЫ
# ======================================================

st.set_page_config(
    page_title="Scrap Market Analytics",
    page_icon="📊",
    layout="wide"
)

df_chart = prepare_chart_data(df, prices)
# ======================================================
# HEADER
# ======================================================

st.title(
    "📊 Scrap Market Analytics"
)

st.caption(
    "Мониторинг • Анализ • Прогноз рынка стального лома"
)

st.divider()


# ======================================================
# ФУНКЦИЯ:
# ТЕКУЩАЯ ЦЕНА VS КОНЕЦ ПРЕДЫДУЩЕГО МЕСЯЦА
# ======================================================

def get_current_vs_prev_month(
    data,
    price_col
):

    data = (
        data[
            ["date", price_col]
        ]
        .dropna()
        .sort_values("date")
        .copy()
    )

    current_date = data["date"].iloc[-1]
    current = data[price_col].iloc[-1]

    current_month = current_date.to_period("M")
    prev_month = current_month - 1

    prev_data = data[
        data["date"].dt.to_period("M")
        == prev_month
    ]

    if prev_data.empty:
        return current, current, current_date

    previous = prev_data[price_col].iloc[-1]

    return current, previous, current_date

# ======================================================
# ФУНКЦИЯ КАРТОЧКИ
# ======================================================

def show_metric(
    col,
    title,
    current,
    previous,
    unit,
    date=None
):

    change = current - previous

    pct = (
        change
        / previous
        * 100
    )

    with col:

        st.metric(
            label=title,
            value=f"{current:,.0f} {unit}",
            delta=(
                f"{change:+,.0f} "
                f"({pct:+.1f}%)"
            )
        )

        if date is not None:
            st.caption(
                f"📅 на {date:%d.%m.%Y}"
            )
# ======================================================
# ПОЛУЧАЕМ АКТУАЛЬНЫЕ ЦЕНЫ
# ======================================================

scrap_cur, scrap_prev, scrap_date = get_current_vs_prev_month(
    prices["scrap"],
    "scrap_price_ufo"
)

index_cur, index_prev, index_date = get_current_vs_prev_month(
    prices["scrap_index"],
    "scrap_index_current"
)

rebar_cur, rebar_prev, rebar_date = get_current_vs_prev_month(
    prices["rebar"],
    "rebar_price"
)

hbi_cur, hbi_prev, hbi_date = get_current_vs_prev_month(
    prices["hbi"],
    "hbi_price"
)

pig_cur, pig_prev, pig_date = get_current_vs_prev_month(
    prices["pig"],
    "pig_iron_price"
)

billet_cur, billet_prev, billet_date = get_current_vs_prev_month(
    prices["billet"],
    "billet_fob_rub"
)
index_date = scrap_date

# ======================================================
# ПОСЛЕДНИЕ МЕСЯЧНЫЕ ДАННЫЕ
# ДЛЯ ФУНДАМЕНТАЛЬНЫХ ПОКАЗАТЕЛЕЙ
# ======================================================

last = df.iloc[-1]
prev = df.iloc[-2]

demand_date = pd.to_datetime(
    last["date"]
)

months_ru = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь"
}

demand_period = (
    f"{months_ru[demand_date.month]} "
    f"{demand_date.year}"
)
# ======================================================
# ДРАЙВЕРЫ РЫНКА
# ======================================================

st.subheader(
    "🌐 Драйверы рынка"
)


# ======================================================
# ЦЕНОВЫЕ ИНДИКАТОРЫ
# ======================================================

with st.container(border=True):

    st.markdown(
        '<span class="price-panel-marker"></span>',
        unsafe_allow_html=True
    )

    st.markdown(
        "### 💰 Ценовые индикаторы"
    )

    st.caption(
        "Текущая котировка и изменение относительно "
        "последней котировки предыдущего месяца"
    )

    c1, c2, c3 = st.columns(3)

    show_metric(
        c1,
        "♻️ Лом 3А УФО",
        scrap_cur,
        scrap_prev,
        "руб./т",
        scrap_date
    )

    show_metric(
        c2,
        "🇷🇺 Индекс лома РФ",
        index_cur,
        index_prev,
        "руб./т",
        index_date
    )

    show_metric(
        c3,
        "🏗 Арматура А3",
        rebar_cur,
        rebar_prev,
        "руб./т",
        rebar_date
    )


    st.markdown("")

    c1, c2, c3 = st.columns(3)

    show_metric(
        c1,
        "🔥 ГБЖ",
        hbi_cur,
        hbi_prev,
        "руб./т",
        hbi_date
    )

    show_metric(
        c2,
        "⚫ Чугун",
        pig_cur,
        pig_prev,
        "руб./т",
        pig_date
    )

    show_metric(
        c3,
        "🌍 Заготовка FOB Турция",
        billet_cur,
        billet_prev,
        "руб./т",
        billet_date
    )


# ======================================================
# ПОКАЗАТЕЛИ СПРОСА
# ======================================================

with st.container(border=True):

    st.markdown(
        '<span class="demand-panel-marker"></span>',
        unsafe_allow_html=True
    )

    st.markdown(
        "### 🏭 Показатели спроса на лом"
    )

    st.caption(
    f"📅 {demand_period} • изменение месяц к месяцу"
)

    c1, c2, c3, c4 = st.columns(4)

    show_metric(
        c1,
        "🚚 Поставки лома РФ",
        last["scrap_supply_ru"],
        prev["scrap_supply_ru"],
        "тыс. т"
    )

    show_metric(
        c2,
        "🚚 Поставки лома УФО",
        last["scrap_supply_ufo"],
        prev["scrap_supply_ufo"],
        "тыс. т"
    )

    show_metric(
        c3,
        "⚡ Электросталь РФ",
        last["eaf_production_ru"],
        prev["eaf_production_ru"],
        "тыс. т"
    )

    show_metric(
        c4,
        "⚡ Электросталь УФО",
        last["eaf_production_ufo"],
        prev["eaf_production_ufo"],
        "тыс. т"
    )


st.divider()
# ======================================================
# АНАЛИЗ ДИНАМИКИ РЫНКА
# ======================================================

st.subheader(
    "📈 Динамика рынка"
)


# ======================================================
# ПЕРИОД И РЕЖИМ ОТОБРАЖЕНИЯ
# ======================================================

col_period, col_mode = st.columns(2)


with col_period:

    st.markdown("**Период**")

    period = st.radio(
        "Период",
        ["1Г", "2Г", "3Г", "Все"],
        horizontal=True,
        label_visibility="collapsed"
    )


with col_mode:

    st.markdown("**Отображение**")

    mode = st.radio(
        "Отображение",
        [
            "Цена",
            "Спрос",
            "Изменения с начала периода",
            "изменения М/М"
        ],
        horizontal=True,
        label_visibility="collapsed"
    )


# ======================================================
# ВЫБОР ФАКТОРОВ
# ======================================================

price_factors = [
    "scrap_price_end",
    "scrap_price_index_rf",
    "rebar_price_end",
    "hbi_price_end",
    "pig_iron_price_end",
    "billet_fob_rub_end"
]

demand_factors = [
    "scrap_supply_ru",
    "scrap_supply_ufo",
    "eaf_production_ru",
    "eaf_production_ufo"
]


# ------------------------------------------------------
# ЦЕНА / ИЗМЕНЕНИЯ С НАЧАЛА ПЕРИОДА
# ------------------------------------------------------

if mode in ["Цена", "Изменения с начала периода"]:

    st.markdown("**Ценовые факторы**")

    selected = st.multiselect(
        "Ценовые факторы",
        options=price_factors,
        default=["scrap_price_end"],
        format_func=lambda x: NAMES[x],
        label_visibility="collapsed"
    )


# ------------------------------------------------------
# СПРОС
# ------------------------------------------------------

elif mode == "Спрос":

    st.markdown("**Показатели спроса**")

    selected = st.multiselect(
        "Показатели спроса",
        options=demand_factors,
        default=["scrap_supply_ru"],
        format_func=lambda x: NAMES[x],
        label_visibility="collapsed"
    )


# ------------------------------------------------------
# ИЗМЕНЕНИЯ М/М
# ------------------------------------------------------

else:

    st.markdown("**Факторы**")

    selected = st.multiselect(
        "Факторы",
        options=price_factors + demand_factors,
        default=["scrap_price_end"],
        format_func=lambda x: NAMES[x],
        label_visibility="collapsed"
    )

# ======================================================
# ГРАФИК
# ======================================================

if selected:


    fig = create_market_chart(
        df=df_chart,
        forecast_df=forecast_df,
        period=period,
        mode=mode,
        selected=selected,
        COLORS=COLORS,
        NAMES=NAMES,
        prices=prices
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

else:

    st.info(
        "Выберите хотя бы один показатель."
    )

st.markdown("### ⚖️ Индикаторы рынка")

rebar_scrap = create_rebar_scrap_indicator(prices)
scrap_hbi = create_scrap_hbi_indicator(prices)
scrap_pig = create_scrap_pig_indicator(prices)

col1, col2, col3 = st.columns(3)

import inspect
st.write("AI FUNCTION:", inspect.signature(generate_scrap_ai_commentary))

ai_commentary = generate_scrap_ai_commentary(
    current_price=current_price,
    fair_value=fair_value,
    fair_value_diff_pct=fair_value_diff_pct,
    spread_z=spread_z,
    forecast_next_month=forecast_next_month,
    forecast_change_pct=forecast_change_pct,
    price_trend=price_trend,
    trend_change_pct=trend_change_pct,
    trend_start_date=trend_start_date,
    trend_end_date=trend_end_date,
    purchase_title=commentary["purchase_title"],
    recommendation=commentary["recommendation"],

    rebar_scrap_status=rebar_scrap["status"],
    rebar_scrap_current=rebar_scrap["current"],
    rebar_scrap_p25=rebar_scrap["p25"],
    rebar_scrap_p75=rebar_scrap["p75"],

    scrap_hbi_status=scrap_hbi["status"],
    scrap_hbi_current=scrap_hbi["current"],
    scrap_hbi_p25=scrap_hbi["p25"],
    scrap_hbi_p75=scrap_hbi["p75"]
)

def show_signal(status, signal):

    if signal == "positive":
        bg = "rgba(34, 197, 94, 0.15)"
        border = "#22C55E"
        color = "#4ADE80"

    elif signal == "negative":
        bg = "rgba(239, 68, 68, 0.15)"
        border = "#EF4444"
        color = "#F87171"

    else:
        bg = "rgba(156, 163, 175, 0.12)"
        border = "#6B7280"
        color = "#D1D5DB"

    st.markdown(
        f"""
        <div style="
            background:{bg};
            border:1px solid {border};
            border-radius:8px;
            padding:10px 12px;
            text-align:center;
            color:{color};
            font-weight:600;
            font-size:16px;
        ">
            {status}
        </div>
        """,
        unsafe_allow_html=True
    )
with col1:
    st.plotly_chart(
        rebar_scrap["fig"],
        use_container_width=True
    )

    show_signal(
        rebar_scrap["status"],
        "positive" if rebar_scrap["current"] > rebar_scrap["p75"]
        else "negative" if rebar_scrap["current"] < rebar_scrap["p25"]
        else "neutral"
    )


with col2:
    st.plotly_chart(
        scrap_hbi["fig"],
        use_container_width=True
    )

    show_signal(
        scrap_hbi["status"],
        "positive" if scrap_hbi["current"] < scrap_hbi["p25"]
        else "negative" if scrap_hbi["current"] > scrap_hbi["p75"]
        else "neutral"
    )


with col3:
    st.plotly_chart(
        scrap_pig["fig"],
        use_container_width=True
    )

    show_signal(
        scrap_pig["status"],
        "neutral"
    )

st.markdown("## 📊 Оценка состояния рынка")

indicator_mode = st.radio(
    "Показатель",
    [
        "⚖ Справедливая цена",
        "📊 Перегрев / недооценка",
       
    ],
    horizontal=True
)

if indicator_mode == "⚖ Справедливая цена":

    fair_fig = create_fair_value_indicator(
        fair_value_data
    )

    st.plotly_chart(
        fair_fig,
        use_container_width=True
    )


elif indicator_mode == "📊 Перегрев / недооценка":

    z_fig, z_status, z_signal = (
        create_scrap_zscore_indicator(
            fair_value_data
        )
    )

    st.plotly_chart(
        z_fig,
        use_container_width=True
    )

    show_signal(z_status, z_signal)

# ==================================================
# РЕШЕНИЕ СИСТЕМЫ
# ==================================================

st.subheader(
    "💡 Решение системы"
)

# Сигнал закупки
if commentary["purchase_signal"] == "buy":

    st.success(
        commentary["purchase_title"]
    )

elif commentary["purchase_signal"] == "avoid":

    st.error(
        commentary["purchase_title"]
    )

else:

    st.warning(
        commentary["purchase_title"]
    )


# Состояние рынка + цена + прогноз
st.info(
    commentary["comment"]
)


# ==================================================
# РЕКОМЕНДАЦИЯ
# ==================================================

if commentary["purchase_signal"] == "buy":

    st.success(
        f"📌 Рекомендация:\n\n"
        f"{commentary['recommendation']}"
    )

elif commentary["purchase_signal"] == "avoid":

    st.error(
        f"📌 Рекомендация:\n\n"
        f"{commentary['recommendation']}"
    )

else:

    st.warning(
        f"📌 Рекомендация:\n\n"
        f"{commentary['recommendation']}"
    )
# ==================================================
# AI-АНАЛИЗ
# ==================================================

st.markdown("## 🤖 Аналитический комментарий")

st.markdown("**Текущая оценка**")
st.info(ai_commentary["current_assessment"])

st.markdown("**Прогноз на следующий месяц**")
st.info(ai_commentary["next_month"])

st.markdown("**Ключевые рыночные факторы**")
st.info(ai_commentary["market_factors"])

st.markdown("**Структурный прогноз 6–12 месяцев**")
st.warning(ai_commentary["structural_outlook"])

st.markdown("**Вывод для закупок**")
st.info(ai_commentary["procurement_conclusion"])

if ai_commentary["sources"]:
    st.caption(
        "Источники: "
        + " • ".join(ai_commentary["sources"])
    )

if commentary["purchase_signal"] == "buy":
    st.success(
        f"📌 Рекомендация:\n\n"
        f"{commentary['recommendation']}"
    )

elif commentary["purchase_signal"] == "avoid":
    st.error(
        f"📌 Рекомендация:\n\n"
        f"{commentary['recommendation']}"
    )

else:
    st.warning(
        f"📌 Рекомендация:\n\n"
        f"{commentary['recommendation']}"
    )