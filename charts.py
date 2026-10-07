import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def create_market_chart(
        df,
        forecast_df,
        period,
        mode,
        selected,
        COLORS,
        NAMES,
        prices
):

    # =====================================================
    # 1. ПОДГОТОВКА ДАННЫХ
    # =====================================================

    df = df.copy()

    df["date"] = pd.to_datetime(
        df["date"]
    )

    df = df.sort_values(
        "date"
    )


    # =====================================================
    # 2. ВЫБОР ПЕРИОДА
    # =====================================================

    max_date = df["date"].max()

    if period == "1Г":

        start_date = (
            max_date
            - pd.DateOffset(years=1)
        )

    elif period == "2Г":

        start_date = (
            max_date
            - pd.DateOffset(years=2)
        )

    elif period == "3Г":

        start_date = (
            max_date
            - pd.DateOffset(years=3)
        )

    else:

        start_date = df["date"].min()


    df_plot = df[
        df["date"] >= start_date
    ].copy()

    df_chart = df_plot.copy()

    # Для графика спроса переводим поставки лома в реальные тонны
    if mode == "Спрос":
        df_chart["scrap_supply_ru"] = df_chart["scrap_supply_ru"]
        df_chart["scrap_supply_ufo"] = df_chart["scrap_supply_ufo"]


    # =====================================================
    # 3. РЕЖИМ ОТОБРАЖЕНИЯ
    # =====================================================

    if mode == "Цена":

        ylabel = "руб./т"


    elif mode == "Изменения с начала периода":

        ylabel = "%"

        for factor in selected:

            series = (
                df_plot[factor]
                .dropna()
            )

            if series.empty:
                continue

            base_value = series.iloc[0]

            df_chart[factor] = (
                (
                    df_plot[factor]
                    - base_value
                )
                / base_value
                * 100
            ).round(0)

    elif mode == "Спрос":

        df_chart["scrap_supply_ru"] = df_chart["scrap_supply_ru"]
        df_chart["scrap_supply_ufo"] = df_chart["scrap_supply_ufo"]

        df_chart["eaf_production_ru"] = df_chart["eaf_production_ru"]
        df_chart["eaf_production_ufo"] = df_chart["eaf_production_ufo"]

        ylabel = "тыс. т"


    elif mode == "изменения М/М":

        ylabel = "%"

        for factor in selected:

            df_chart[factor] = (
                df_plot[factor]
                .pct_change(
                    fill_method=None
                )
                * 100
            ).round(0)


    # =====================================================
    # 4. ГРАФИК
    # =====================================================

    fig = go.Figure()
    


    # =====================================================
    # ФАКТИЧЕСКИЕ ДАТЫ ПОСЛЕДНИХ КОТИРОВОК
    # Используются только для tooltip текущего месяца
    # =====================================================

    current_quote_dates = {
        "scrap_price_end": pd.to_datetime(
            prices["scrap"]["date"]
        ).max(),

        "scrap_price_index_rf": pd.to_datetime(
            prices["scrap_index"]["date"]
        ).max(),

        "rebar_price_end": pd.to_datetime(
            prices["rebar"]["date"]
        ).max(),

        "hbi_price_end": pd.to_datetime(
            prices["hbi"]["date"]
        ).max(),

        "pig_iron_price_end": pd.to_datetime(
            prices["pig"]["date"]
        ).max(),

        "billet_fob_rub_end": pd.to_datetime(
            prices["billet"]["date"]
        ).max()
    }

    current_month = pd.Timestamp.today().to_period("M")


    for factor in selected:

        if factor not in df_chart.columns:
            continue

        chart_data = (
            df_chart[
                ["date", factor]
            ]
            .dropna()
        )

        if chart_data.empty:
            continue

        # Даты, которые будут показаны только в tooltip
        # Для истории оставляем конец месяца
        hover_dates = (
            chart_data["date"]
            .dt.strftime("%d.%m.%Y")
            .copy()
        )

        # Только текущему календарному месяцу
        # подставляем реальную дату последней котировки
        if factor in current_quote_dates:

            mask = (
                chart_data["date"].dt.to_period("M")
                == current_month
            )

            real_date = current_quote_dates[factor]

            if mask.any() and pd.notna(real_date):
                hover_dates.loc[mask] = (
                    real_date.strftime("%d.%m.%Y")
                )

        customdata = (
            hover_dates
            .to_numpy()
            .reshape(-1, 1)
        )
        
        # Формат tooltip в зависимости от режима
        if mode == "Цена":

            hover = "%{y:,.0f} руб./т"

        elif mode == "Спрос":

            hover = "%{y:,.0f} тыс. т"

        else:

            hover = "%{y:+.0f}%"

        # ---------------------------------------------
        # Дата для tooltip
        # ---------------------------------------------

        hover_dates = (
            chart_data["date"]
            .dt.strftime("%d.%m.%Y")
            .copy()
        )

        # Только для ценовых показателей
        # и только для текущего календарного месяца
        if factor in current_quote_dates:

            mask = (
                chart_data["date"].dt.to_period("M")
                == current_month
            )

            if mask.any():

                real_date = current_quote_dates[factor]

                if pd.notna(real_date):

                    hover_dates.loc[mask] = (
                        real_date.strftime("%d.%m.%Y")
                    )

        customdata = (
            hover_dates
            .to_numpy()
            .reshape(-1, 1)
        )

        fig.add_trace(

            go.Scatter(

                x=chart_data["date"],

                y=chart_data[factor],
                customdata=customdata,

                mode="lines",

                name=NAMES[factor],

                line=dict(
                    width=3,
                    color=COLORS[factor]
                ),

                hovertemplate=(
                    "%{customdata[0]}<br>"
                    + NAMES[factor]
                    + ": "
                    + hover
                    + "<extra></extra>"
                )
            )
        )


    # =====================================================
    # 5. ТЕКУЩАЯ ЦЕНА И ПРОГНОЗ
    # =====================================================

    if (
        mode == "Цена"
        and "scrap_price_end" in selected
    ):

        current = (
            df_plot[
                ["date", "scrap_price_end"]
            ]
            .dropna()
        )

        if not current.empty:

            current_date = current["date"].iloc[-1]
            current_price = current["scrap_price_end"].iloc[-1]


            # ==========================================
            # ТЕКУЩАЯ ЦЕНА
            # ==========================================

            fig.add_trace(

                go.Scatter(

                    x=[current_date],

                    y=[current_price],

                    mode="markers+text",

                    name="Текущая цена",

                    text=[
                        f"{current_price:,.0f} руб./т"
                    ],

                    textposition="top center",

                    marker=dict(
                        size=14,
                        color="#00D4C8",
                        symbol="circle"
                    ),

                    # Не создаём второй tooltip
                    hoverinfo="skip"
                )
            )


            # ==========================================
            # ПРОГНОЗ ARIMA
            # ==========================================

            if (
                forecast_df is not None
                and not forecast_df.empty
            ):

                # Соединяем последний факт с прогнозом
                forecast_line = pd.concat(
                    [
                        pd.DataFrame({
                            "date": [current_date],
                            "forecast_price": [current_price]
                        }),

                        forecast_df[
                            ["date", "forecast_price"]
                        ]
                    ],
                    ignore_index=True
                )


                # Пунктирная линия прогноза
                # Последний факт нужен только для соединения линии
                fig.add_trace(

                    go.Scatter(

                        x=forecast_line["date"],

                        y=forecast_line["forecast_price"],

                        mode="lines",

                        name="Прогноз ARIMA",

                        line=dict(
                            width=3,
                            dash="dash",
                            color="#00D4C8"
                        ),

                        hoverinfo="skip"
                    )
                )


                # Tooltip только для будущих прогнозных точек
                fig.add_trace(

                    go.Scatter(

                        x=forecast_df["date"],

                        y=forecast_df["forecast_price"],

                        mode="markers",

                        name="Прогноз",

                        marker=dict(
                            size=8,
                            color="#00D4C8"
                        ),

                        hovertemplate=(
                            "%{x|%m.%Y}<br>"
                            "Прогноз: %{y:,.0f} руб./т"
                            "<extra></extra>"
                        ),

                        showlegend=False
                    )
                )


    # =====================================================
    # 6. ОФОРМЛЕНИЕ
    # =====================================================

    fig.update_layout(

        template="plotly_dark",

        height=650,

        hovermode="x unified",

        hoverlabel=dict(
            font_size=17
        ),

        yaxis_title=ylabel,

        xaxis_title="",

        margin=dict(
            l=20,
            r=20,
            t=30,
            b=20
        ),

        legend=dict(
            orientation="v",
            x=1.01,
            y=1
        )
    )

    return fig