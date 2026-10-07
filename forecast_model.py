import pandas as pd
import numpy as np

from statsmodels.tsa.arima.model import ARIMA


def build_forecast(scrap_data):

    # ==========================================
    # ПОСЛЕДНЯЯ КОТИРОВКА КАЖДОГО МЕСЯЦА
    # ==========================================

    data = (
        scrap_data[
            ["date", "scrap_price_ufo"]
        ]
        .dropna()
        .sort_values("date")
        .copy()
    )

    data["month"] = (
        pd.to_datetime(data["date"])
        .dt.to_period("M")
    )

    scrap_last = (
        data
        .groupby("month")
        .tail(1)
        .reset_index(drop=True)
    )

    # ==========================================
    # ARIMA(1,1,1)
    # ==========================================

    price_series = (
        scrap_last["scrap_price_ufo"]
        .reset_index(drop=True)
    )

    last_price = price_series.iloc[-1]
    last_month = scrap_last["month"].iloc[-1]

    model = ARIMA(
        price_series,
        order=(1, 1, 1)
    )

    fit = model.fit()

    forecast = fit.forecast(
        steps=3
    )

    # ==========================================
    # ДАТЫ ПРОГНОЗА
    # ==========================================

    forecast_dates = pd.date_range(
        start=last_month.to_timestamp("M")
        + pd.DateOffset(months=1),
        periods=3,
        freq="ME"
    )

    # ==========================================
    # РЕЗУЛЬТАТ
    # ==========================================

    forecast_df = pd.DataFrame({
        "date": forecast_dates,
        "forecast_price": np.asarray(forecast)
    })

    forecast_df["change_pct"] = (
        forecast_df["forecast_price"]
        / last_price
        - 1
    ) * 100

    return forecast_df