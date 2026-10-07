import os
import requests
import pandas as pd
from dotenv import load_dotenv
# ======================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ======================================================
load_dotenv()
# ======================================================
# НАСТРОЙКИ API
# ======================================================
BASE_URL = os.getenv(
  "METALS_BASE_URL",
  "https://client.metalsmining.ru"
)
EMAIL = os.getenv(
  "METALS_EMAIL"
)
PASSWORD = os.getenv(
  "METALS_PASSWORD"
)
# ======================================================
# ПОЛУЧЕНИЕ ТОКЕНА
# ======================================================
def get_metals_token():
  if not EMAIL:
    raise ValueError(
      "В .env не найден METALS_EMAIL"
    )
  if not PASSWORD:
    raise ValueError(
      "В .env не найден METALS_PASSWORD"
    )
  url = f"{BASE_URL}/api/v1/auth/login"
  payload = {
    "email": EMAIL,
    "password": PASSWORD
  }
  response = requests.post(
    url,
    json=payload,
    timeout=60
  )
  response.raise_for_status()
  data = response.json()
  # ========================================================
  # API может возвращать token:
  #
  # 1. напрямую:
  #   {"token": "..."}
  #
  # 2. внутри result:
  #   {"result": {"token": "..."}}
  #
  # Поддерживаем оба варианта.
  # ========================================================
  token = data.get("token")
  if not token:
    token = (
      data.get("result", {})
      .get("token")
    )
  if not token:
    raise ValueError(
      f"API не вернул token. Ответ: {data}"
    )
  return token
# ======================================================
# КАТАЛОГ КОТИРОВОК ЛОМА
# ======================================================
SCRAP_CATALOG_ID = 587588
def get_scrap_catalog(token):
  url = f"{BASE_URL}/api/v1/base/1"
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
  }
  params = {
    "with": "catalogsTree"
  }
  response = requests.get(
    url,
    headers=headers,
    params=params,
    timeout=120
  )
  response.raise_for_status()
  result = response.json()
  tree = result["data"].get(
    "catalogs_tree",
    []
  )
  return tree
# ======================================================
# ПОИСК НУЖНОГО КАТАЛОГА
# ======================================================
def find_catalog(items, target_id):
  for item in items:
    if item["id"] == target_id:
      return item
    result = find_catalog(
      item.get("children", []),
      target_id
    )
    if result is not None:
      return result
  return None
# ======================================================
# ID ВСЕХ КОТИРОВОК ЛОМА 3А
# ======================================================
def get_scrap_3a_ids(token):
  tree = get_scrap_catalog(token)
  scrap_catalog = find_catalog(
    tree,
    SCRAP_CATALOG_ID
  )
  if scrap_catalog is None:
    raise ValueError(
      f"Каталог {SCRAP_CATALOG_ID} не найден"
    )
  scrap_ids = [
    item["id"]
    for item in scrap_catalog.get("children", [])
    if item.get("name", "").startswith("3А")
    and not item.get("disabled", False)
  ]
  if not scrap_ids:
    raise ValueError(
      "Котировки лома 3А не найдены"
    )
  return scrap_ids
# ======================================================
# ЗАГРУЗКА КОТИРОВОК ЛОМА 3А
# ======================================================
def load_scrap_prices(
  token,
  date_from="2021-01-01",
  date_to=None
):
  if date_to is None:
        date_to = pd.Timestamp.today().strftime("%Y-%m-%d")
  
  scrap_ids = get_scrap_3a_ids(token)
  url = f"{BASE_URL}/api/v1/export.p"
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
  }
  payload = {
    "base_id": 1,
    "date_from": date_from,
    "date_to": date_to,
    "display": "range",
    "output": "screen",
    "show_output": "vertical",
    "periodicity": "week",
    "truncate": 0,
    "hide_null": True,
    "catalog_id": scrap_ids
  }
  response = requests.post(
    url,
    headers=headers,
    json=payload,
    timeout=30
  )
  response.raise_for_status()
  return response.json()
# ======================================================
# ПРЕОБРАЗОВАНИЕ КОТИРОВОК В DATAFRAME
# ======================================================
def parse_scrap_prices(data):
  rows = []
  for row in data.get("data", []):
    if len(row) < 6:
      continue
    rows.append({
      "date": row[0].get("text"),
      "category": row[1].get("text"),
      "product": row[2].get("text"),
      "market": row[3].get("text"),
      "quote": row[4].get("text"),
      "price": row[5].get("text")
    })
  df = pd.DataFrame(rows)
  if df.empty:
    return df
  # Дата
  df["date"] = pd.to_datetime(
    df["date"],
    format="%d.%m.%Y",
    errors="coerce"
  )
  # Цена
  df["price"] = pd.to_numeric(
    df["price"],
    errors="coerce"
  )
  # Убираем некорректные строки
  df = df.dropna(
    subset=["date", "price"]
  )
  # Сортируем
  df = df.sort_values(
    ["quote", "date"]
  ).reset_index(drop=True)
  return df
# ======================================================
# РАЗБОР НАЗВАНИЯ КОТИРОВКИ
# ======================================================
def add_scrap_attributes(df):
  df = df.copy()
  # Базис поставки
  df["basis"] = df["quote"].str.extract(
    r"\b(CPT|FCA)\b",
    expand=False
  )
  # Вид транспорта
  df["transport"] = df["quote"].str.extract(
    r"\b(ж/д|авто)\b",
    expand=False
  )
  # Регион
  df["region"] = (
    df["quote"]
    .str.replace(
      r"^3А,\s*РФ\s+(?:CPT|FCA)\s+(?:ж/д|авто)\s+",
      "",
      regex=True
    )
    .str.replace(
      r",\s*руб\./т,\s*без НДС$",
      "",
      regex=True
    )
    .str.strip()
  )
  return df
  # ======================================================
# ЦЕЛЕВАЯ КОТИРОВКА — ЛОМ 3А УРАЛЬСКИЙ ФО
# ======================================================
def get_target_scrap_ufo(df):
  target = df[
    (df["region"] == "Уральский ФО")
    & (df["basis"] == "CPT")
    & (df["transport"] == "ж/д")
  ].copy()
  target = (
    target[
      [
        "date",
        "price"
      ]
    ]
    .rename(
      columns={
        "price": "scrap_price_ufo"
      }
    )
    .sort_values("date")
    .reset_index(drop=True)
  )
  return target
# ======================================================
# РЕГИОНАЛЬНЫЕ КОТИРОВКИ ЛОМА 3А
# ======================================================
def get_scrap_regional_prices(df):
  """
  Выбирает недельные котировки 3А CPT ж/д
  для четырех аналитических регионов.
  """
  region_map = {
    "Уральский ФО": "scrap_price_ufo",
    "Центральный ФО": "scrap_price_cfo",
    "Сибирский ФО": "scrap_price_sfo",
    "Южный ФО": "scrap_price_yufo"
  }
  regional = df[
    (df["basis"] == "CPT")
    & (df["transport"] == "ж/д")
    & (df["region"].isin(region_map.keys()))
  ].copy()
  regional["price_name"] = (
    regional["region"]
    .map(region_map)
  )
  regional = (
    regional[
      [
        "date",
        "price_name",
        "price"
      ]
    ]
    .pivot(
      index="date",
      columns="price_name",
      values="price"
    )
    .reset_index()
    .sort_values("date")
    .reset_index(drop=True)
  )
  regional.columns.name = None
  return regional
# ======================================================
# ID ЗАВОДОВ — ПОСТАВКИ СТАЛЬНОГО ЛОМА
# ======================================================
SCRAP_SUPPLY_CATALOG_ID = 725556
def get_scrap_supply_ids(token):
  url = f"{BASE_URL}/api/v1/base/5"
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
  }
  params = {
    "with": "catalogsTree"
  }
  response = requests.get(
    url,
    headers=headers,
    params=params,
    timeout=30
  )
  response.raise_for_status()
  result = response.json()
  tree = result["data"].get(
    "catalogs_tree",
    []
  )
  scrap_catalog = find_catalog(
    tree,
    SCRAP_SUPPLY_CATALOG_ID
  )
  if scrap_catalog is None:
    raise ValueError(
      f"Каталог {SCRAP_SUPPLY_CATALOG_ID} не найден"
    )
  supply_ids = []
  # Уровень 1:
  # Лом стальной / Лом рельсов / Лом чугуна / Прочие виды
  for scrap_type in scrap_catalog.get("children", []):
    # Уровень 2:
    # конкретные заводы
    for plant in scrap_type.get("children", []):
      if not plant.get("disabled", False):
        supply_ids.append(
          plant["id"]
        )
  return supply_ids
# ======================================================
# ЗАГРУЗКА ПОСТАВОК СТАЛЬНОГО ЛОМА
# ======================================================
def load_scrap_supply(
  token,
  date_from="2021-01-01",
  date_to="2026-08-24"
):
  supply_ids = get_scrap_supply_ids(token)
  url = f"{BASE_URL}/api/v1/export.p"
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
  }
  payload = {
    "base_id": 5,
    "date_from": date_from,
    "date_to": date_to,
    "display": "range",
    "output": "screen",
    "show_output": "vertical",
    "periodicity": "month",
    "truncate": 0,
    "hide_null": True,
    "catalog_id": supply_ids
  }
  response = requests.post(
    url,
    headers=headers,
    json=payload,
    timeout=30
  )
  response.raise_for_status()
  return response.json()
# ПРЕОБРАЗОВАНИЕ ПОСТАВОК ЛОМА В DATAFRAME
# ======================================================
def parse_scrap_supply(data):
  rows = []
  for row in data.get("data", []):
    if len(row) < 7:
      continue
    rows.append({
      "period": row[0].get("text"),
      "category": row[1].get("text"),
      "product": row[2].get("text"),
      "scrap_type": row[3].get("text"),
      "plant": row[4].get("text"),
      "supplier_region": row[5].get("text"),
      "supply": row[6].get("text")
    })
  df = pd.DataFrame(rows)
  if df.empty:
    return df
  # Объём поставок
  df["supply"] = pd.to_numeric(
    df["supply"],
    errors="coerce"
  )
  df = df.dropna(
    subset=["supply"]
  )
  return df
# ======================================================
# ЗАВОДЫ УРАЛЬСКОГО ФЕДЕРАЛЬНОГО ОКРУГА
# ======================================================
UFO_PLANTS = [
  "Ашинский МЗ",
  "Челябинский МК",
  "Первоуральский НТЗ",
  "Северский ТЗ",
  "Промсорт-Урал",
  "Магнитогорский МК",
  "МЗ Электросталь Тюмени",
  "Надеждинский МЗ",
  "Ижсталь",
  "Уральская Сталь"
]
PLANT_REGIONS = {
  # УФО
  "Ашинский МЗ": "УФО",
  "Ижсталь": "УФО",
  "МЗ Электросталь Тюмени": "УФО",
  "Магнитогорский МК": "УФО",
  "Надеждинский МЗ": "УФО",
  "Первоуральский НТЗ": "УФО",
  "Промсорт-Урал": "УФО",
  "Северский ТЗ": "УФО",
  "Уральская Сталь": "УФО",
  "Челябинский МК": "УФО",
  # ЦФО
  "Белорусский МЗ": "ЦФО",
  "Выксунский МЗ": "ЦФО",
  "Новолипецкий МК": "ЦФО",
  "Оскольский ЭМК": "ЦФО",
  "Промсорт-Калуга": "ЦФО",
  "Тульский МПЗ": "ЦФО",
  "Череповецкий МК": "ЦФО",
  # СФО
  "Амурсталь": "СФО",
  "Гурьевский МЗ": "СФО",
  "ЕВРАЗ-ЗСМК": "СФО",
  "ЕВРАЗ-НКМК": "СФО",
  # ЮФО
  "Абинский ЭМЗ": "ЮФО",
  "Волжский ТЗ": "ЮФО",
  "Донской ЭМЗ": "ЮФО",
  "Красный Октябрь": "ЮФО",
  "МЗ Балаково": "ЮФО",
  "Новоросметалл": "ЮФО",
  "Таганрогский МЗ": "ЮФО",
}
# ======================================================
# МЕСЯЧНЫЕ ПОСТАВКИ ЛОМА В УФО
# ======================================================
MONTH_MAP = {
  "янв.": 1,
  "фев.": 2,
  "мар.": 3,
  "апр.": 4,
  "май.": 5,
  "июн.": 6,
  "июл.": 7,
  "авг.": 8,
  "сен.": 9,
  "окт.": 10,
  "ноя.": 11,
  "дек.": 12
}
def get_scrap_supply_ufo(df):
  df = df[
    df["plant"].isin(UFO_PLANTS)
  ].copy()
  # Разбираем дату вида "янв.2021"
  df["month_name"] = df["period"].str.extract(
    r"([а-яё]+\.)",
    expand=False
  )
  df["year"] = pd.to_numeric(
    df["period"].str.extract(
      r"(\d{4})",
      expand=False
    ),
    errors="coerce"
  )
  df["month"] = df["month_name"].map(
    MONTH_MAP
  )
  df["date"] = pd.to_datetime(
    dict(
      year=df["year"],
      month=df["month"],
      day=1
    ),
    errors="coerce"
  )
  # Суммируем все поставки
  # от всех регионов на все заводы УФО
  monthly = (
    df
    .groupby(
      "date",
      as_index=False
    )["supply"]
    .sum()
    .rename(
      columns={
        "supply": "scrap_supply_ufo"
      }
    )
    .sort_values("date")
    .reset_index(drop=True)
  )
  return monthly
def get_monthly_weighted_scrap_price(df_weekly):
  """
  Преобразует недельные котировки лома
  в средневзвешенные месячные цены.
  Вес = количество календарных дней,
  в течение которых действовала котировка.
  """
  df = (
    df_weekly[["date", "scrap_price_ufo"]]
    .dropna()
    .sort_values("date")
    .copy()
  )
  # Дата следующей котировки
  df["next_date"] = df["date"].shift(-1)
  # Последняя котировка действует 7 дней
  df.loc[df.index[-1], "next_date"] = (
    df.loc[df.index[-1], "date"]
    + pd.Timedelta(days=7)
  )
  daily_rows = []
  # Разворачиваем недельные котировки
  # на календарные дни
  for _, row in df.iterrows():
    dates = pd.date_range(
      start=row["date"],
      end=row["next_date"] - pd.Timedelta(days=1),
      freq="D"
    )
    for date in dates:
      daily_rows.append({
        "date": date,
        "scrap_price_ufo": row["scrap_price_ufo"]
      })
  daily = pd.DataFrame(
    daily_rows
  )
  daily["month"] = (
    daily["date"]
    .dt.to_period("M")
    .dt.to_timestamp()
  )
  # Месячные показатели
  monthly = (
    daily
    .groupby(
      "month",
      as_index=False
    )
    .agg(
      scrap_price_wavg=(
        "scrap_price_ufo",
        "mean"
      ),
      scrap_price_min=(
        "scrap_price_ufo",
        "min"
      ),
      scrap_price_max=(
        "scrap_price_ufo",
        "max"
      ),
      scrap_price_start=(
        "scrap_price_ufo",
        "first"
      ),
      scrap_price_end=(
        "scrap_price_ufo",
        "last"
      )
    )
    .rename(
      columns={
        "month": "date"
      }
    )
  )
  # Изменение цены внутри месяца
  monthly["scrap_price_change"] = (
    monthly["scrap_price_end"]
    - monthly["scrap_price_start"]
  )
  monthly["scrap_price_change_pct"] = (
    monthly["scrap_price_change"]
    / monthly["scrap_price_start"]
    * 100
  )
  # Диапазон цены внутри месяца
  monthly["scrap_price_range"] = (
    monthly["scrap_price_max"]
    - monthly["scrap_price_min"]
  )
  # Изменение средневзвешенной цены
  # относительно предыдущего месяца
  monthly["scrap_price_mom"] = (
    monthly["scrap_price_wavg"]
    .diff()
  )
  monthly["scrap_price_mom_pct"] = (
    monthly["scrap_price_wavg"]
    .pct_change()
    * 100
  )
  return monthly
def get_monthly_regional_scrap_prices(df_prices):
  """
  Средневзвешенные месячные цены лома 3А
  по УФО, ЦФО, СФО и ЮФО.
  Вес недельной котировки =
  количество календарных дней её действия.
  """
  region_map = {
    "Уральский ФО": "scrap_price_ufo",
    "Центральный ФО": "scrap_price_cfo",
    "Сибирский ФО": "scrap_price_sfo",
    "Южный ФО": "scrap_price_yufo"
  }
  result = None
  for region, column_name in region_map.items():
    regional = df_prices[
      (df_prices["region"] == region)
      & (df_prices["basis"] == "CPT")
      & (df_prices["transport"] == "ж/д")
    ][["date", "price"]].copy()
    regional = (
      regional
      .dropna()
      .sort_values("date")
      .reset_index(drop=True)
    )
    regional["next_date"] = regional["date"].shift(-1)
    regional.loc[
      regional.index[-1],
      "next_date"
    ] = (
      regional.loc[regional.index[-1], "date"]
      + pd.Timedelta(days=7)
    )
    daily_rows = []
    for _, row in regional.iterrows():
      dates = pd.date_range(
        start=row["date"],
        end=row["next_date"] - pd.Timedelta(days=1),
        freq="D"
      )
      for date in dates:
        daily_rows.append({
          "date": date,
          column_name: row["price"]
        })
    daily = pd.DataFrame(daily_rows)
    daily["month"] = (
      daily["date"]
      .dt.to_period("M")
      .dt.to_timestamp()
    )
    monthly = (
      daily
      .groupby("month", as_index=False)[column_name]
      .mean()
      .rename(columns={"month": "date"})
    )
    if result is None:
      result = monthly
    else:
      result = result.merge(
        monthly,
        on="date",
        how="outer"
      )
  return (
    result
    .sort_values("date")
    .reset_index(drop=True)
  )
# ==========================================================
# ПРОИЗВОДСТВО ЭЛЕКТРОСТАЛИ В РОССИИ
# ==========================================================
EAF_CATALOG_ID = 741421
def load_eaf_production(token):
  """
  Загружает месячное производство электростали
  по предприятиям России.
  """
  url = f"{BASE_URL}/api/v1/export.p"
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
  }
  payload = {
    "base_id": 6,
    "date_from": "2021-01-01",
    "date_to": "2026-08-31",
    "display": "range",
    "output": "screen",
    "show_output": "vertical",
    "periodicity": "month",
    "truncate": 0,
    "hide_null": True,
    "catalog_id": [EAF_CATALOG_ID]
  }
  response = requests.post(
    url,
    headers=headers,
    json=payload,
    timeout=120
  )
  response.raise_for_status()
  return response.json()
def parse_eaf_production(data):
  """
  Преобразует ответ API в таблицу:
  period
  plant
  production
  """
  rows = []
  for row in data.get("data", []):
    if len(row) < 7:
      continue
    rows.append({
      "period": row[0].get("text"),
      "plant": row[5].get("text"),
      "production": row[6].get("text")
    })
  df = pd.DataFrame(rows)
  if df.empty:
    return df
  df["production"] = pd.to_numeric(
    df["production"],
    errors="coerce"
  )
  return (
    df
    .dropna(
      subset=["production"]
    )
    .reset_index(drop=True)
  )
def get_eaf_production_ru(df):
  """
  Суммирует производство электростали
  всех предприятий России по месяцам.
  """
  df = df.copy()
  # Разбираем месяц и год
  df["month_name"] = df["period"].str.extract(
    r"([а-яё]+\.)",
    expand=False
  )
  df["year"] = pd.to_numeric(
    df["period"].str.extract(
      r"(\d{4})",
      expand=False
    ),
    errors="coerce"
  )
  df["month"] = df["month_name"].map(
    MONTH_MAP
  )
  # Создаём нормальную дату
  df["date"] = pd.to_datetime(
    dict(
      year=df["year"],
      month=df["month"],
      day=1
    ),
    errors="coerce"
  )
  # Сумма производства РФ
  monthly = (
    df
    .groupby(
      "date",
      as_index=False
    )["production"]
    .sum()
    .rename(
      columns={
        "production": "eaf_production_ru"
      }
    )
    .sort_values("date")
    .reset_index(drop=True)
  )
  # Изменение месяц к месяцу
  monthly["eaf_production_mom"] = (
    monthly["eaf_production_ru"]
    .diff()
  )
  monthly["eaf_production_mom_pct"] = (
    monthly["eaf_production_ru"]
    .pct_change()
    * 100
  )
  return monthly
def get_scrap_supply_ru(df):
  df = df.copy()
  df["month_name"] = df["period"].str.extract(
    r"([а-яё]+\.)",
    expand=False
  )
  df["year"] = pd.to_numeric(
    df["period"].str.extract(
      r"(\d{4})",
      expand=False
    ),
    errors="coerce"
  )
  df["month"] = df["month_name"].map(
    MONTH_MAP
  )
  df["date"] = pd.to_datetime(
    dict(
      year=df["year"],
      month=df["month"],
      day=1
    ),
    errors="coerce"
  )
  monthly = (
    df
    .groupby(
      "date",
      as_index=False
    )["supply"]
    .sum()
    .rename(
      columns={
        "supply": "scrap_supply_ru"
      }
    )
    .sort_values("date")
    .reset_index(drop=True)
  )
  monthly["scrap_supply_ru_mom"] = (
    monthly["scrap_supply_ru"]
    .diff()
  )
  monthly["scrap_supply_ru_mom_pct"] = (
    monthly["scrap_supply_ru"]
    .pct_change()
    * 100
  )
  return monthly
def get_eaf_production_ufo(df):
  df = df[
    df["plant"].isin(UFO_PLANTS)
  ].copy()
  df["month_name"] = df["period"].str.extract(
    r"([а-яё]+\.)",
    expand=False
  )
  df["year"] = pd.to_numeric(
    df["period"].str.extract(
      r"(\d{4})",
      expand=False
    ),
    errors="coerce"
  )
  df["month"] = df["month_name"].map(
    MONTH_MAP
  )
  df["date"] = pd.to_datetime(
    dict(
      year=df["year"],
      month=df["month"],
      day=1
    ),
    errors="coerce"
  )
  monthly = (
    df
    .groupby(
      "date",
      as_index=False
    )["production"]
    .sum()
    .rename(
      columns={
        "production": "eaf_production_ufo"
      }
    )
    .sort_values("date")
    .reset_index(drop=True)
  )
  monthly["eaf_production_ufo_mom"] = (
    monthly["eaf_production_ufo"]
    .diff()
  )
  monthly["eaf_production_ufo_mom_pct"] = (
    monthly["eaf_production_ufo"]
    .pct_change()
    * 100
  )
  return monthly

PIG_IRON_CATALOG_ID = 587742
def load_pig_iron_prices(token):
  url = f"{BASE_URL}/api/v1/export.p"
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
  }
  payload = {
    "base_id": 1,
    "date_from": "2021-01-01",
    "date_to": pd.Timestamp.today().strftime("%Y-%m-%d"),
    "display": "range",
    "output": "screen",
    "show_output": "vertical",
    "periodicity": "week",
    "truncate": 0,
    "hide_null": True,
    "catalog_id": [PIG_IRON_CATALOG_ID]
  }
  response = requests.post(
    url,
    headers=headers,
    json=payload,
    timeout=120
  )
  response.raise_for_status()
  return response.json()

def parse_pig_iron_prices(data):
  rows = []
  for row in data.get("data", []):
    if len(row) < 6:
      continue
    rows.append({
      "date": row[0].get("text"),
      "price_range": row[5].get("text")
    })
  df = pd.DataFrame(rows)
  if df.empty:
    return df
  df["date"] = pd.to_datetime(
    df["date"],
    format="%d.%m.%Y",
    errors="coerce"
  )
  # Разбиваем диапазон 28750-36000
  price_parts = df["price_range"].str.extract(
    r"([\d\s]+)\s*-\s*([\d\s]+)"
  )
  df["pig_iron_low"] = pd.to_numeric(
    price_parts[0].str.replace(" ", ""),
    errors="coerce"
  )
  df["pig_iron_high"] = pd.to_numeric(
    price_parts[1].str.replace(" ", ""),
    errors="coerce"
  )
  # Середина ценового диапазона
  df["pig_iron_price"] = (
    df["pig_iron_low"]
    + df["pig_iron_high"]
  ) / 2
  df = df.dropna(
    subset=[
      "date",
      "pig_iron_price"
    ]
  )
  return (
    df
    .sort_values("date")
    .reset_index(drop=True)
  )
def get_monthly_pig_iron_price(df_weekly):
  """
  Средневзвешенная месячная цена чугуна.
  Вес недельной котировки =
  количество календарных дней,
  в течение которых она действовала.
  """
  df = (
    df_weekly[
      [
        "date",
        "pig_iron_price"
      ]
    ]
    .dropna()
    .sort_values("date")
    .copy()
  )
  df["next_date"] = df["date"].shift(-1)
  # Последняя недельная котировка действует 7 дней
  df.loc[df.index[-1], "next_date"] = (
    df.loc[df.index[-1], "date"]
    + pd.Timedelta(days=7)
  )
  daily_rows = []
  for _, row in df.iterrows():
    dates = pd.date_range(
      start=row["date"],
      end=(
        row["next_date"]
        - pd.Timedelta(days=1)
      ),
      freq="D"
    )
    for date in dates:
      daily_rows.append({
        "date": date,
        "pig_iron_price": row["pig_iron_price"]
      })
  daily = pd.DataFrame(
    daily_rows
  )
  daily["month"] = (
    daily["date"]
    .dt.to_period("M")
    .dt.to_timestamp()
  )
  monthly = (
    daily
    .groupby(
      "month",
      as_index=False
    )
    .agg(
      pig_iron_price_wavg=(
        "pig_iron_price",
        "mean"
      ),
      pig_iron_price_min=(
        "pig_iron_price",
        "min"
      ),
      pig_iron_price_max=(
        "pig_iron_price",
        "max"
      ),
      pig_iron_price_start=(
        "pig_iron_price",
        "first"
      ),
      pig_iron_price_end=(
        "pig_iron_price",
        "last"
      )
    )
    .rename(
      columns={
        "month": "date"
      }
    )
  )
  monthly["pig_iron_price_change"] = (
    monthly["pig_iron_price_end"]
    - monthly["pig_iron_price_start"]
  )
  monthly["pig_iron_price_change_pct"] = (
    monthly["pig_iron_price_change"]
    / monthly["pig_iron_price_start"]
    * 100
  )
  monthly["pig_iron_price_range"] = (
    monthly["pig_iron_price_max"]
    - monthly["pig_iron_price_min"]
  )
  monthly["pig_iron_price_mom"] = (
    monthly["pig_iron_price_wavg"]
    .diff()
  )
  monthly["pig_iron_price_mom_pct"] = (
    monthly["pig_iron_price_wavg"]
    .pct_change()
    * 100
  )
  return monthly

HBI_CATALOG_ID = 587747
def load_hbi_prices(token):
  url = f"{BASE_URL}/api/v1/export.p"
  headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
  }
  payload = {
    "base_id": 1,
    "date_from": "2021-01-01",
    "date_to": pd.Timestamp.today().strftime("%Y-%m-%d"),
    "display": "range",
    "output": "screen",
    "show_output": "vertical",
    "periodicity": "week",
    "truncate": 0,
    "hide_null": True,
    "catalog_id": [HBI_CATALOG_ID]
  }
  response = requests.post(
    url,
    headers=headers,
    json=payload,
    timeout=120
  )
  response.raise_for_status()
  return response.json()
def parse_hbi_prices(data):
  rows = []
  for row in data.get("data", []):
    if len(row) < 6:
      continue
    rows.append({
      "date": row[0].get("text"),
      "price_range": row[5].get("text")
    })
  df = pd.DataFrame(rows)
  if df.empty:
    return df
  df["date"] = pd.to_datetime(
    df["date"],
    format="%d.%m.%Y",
    errors="coerce"
  )
  # Разбиваем ценовой диапазон
  price_parts = df["price_range"].str.extract(
    r"([\d\s]+)\s*-\s*([\d\s]+)"
  )
  df["hbi_low"] = pd.to_numeric(
    price_parts[0].str.replace(" ", ""),
    errors="coerce"
  )
  df["hbi_high"] = pd.to_numeric(
    price_parts[1].str.replace(" ", ""),
    errors="coerce"
  )
  # Середина диапазона
  df["hbi_price"] = (
    df["hbi_low"]
    + df["hbi_high"]
  ) / 2
  df = df.dropna(
    subset=[
      "date",
      "hbi_price"
    ]
  )
  return (
    df
    .sort_values("date")
    .reset_index(drop=True)
  )
def get_monthly_hbi_price(df_weekly):
  """
  Средневзвешенная месячная цена ГБЖ.
  Вес недельной котировки =
  количество календарных дней,
  в течение которых она действовала.
  """
  df = (
    df_weekly[
      [
        "date",
        "hbi_price"
      ]
    ]
    .dropna()
    .sort_values("date")
    .copy()
  )
  df["next_date"] = df["date"].shift(-1)
  # Последняя котировка действует 7 дней
  df.loc[df.index[-1], "next_date"] = (
    df.loc[df.index[-1], "date"]
    + pd.Timedelta(days=7)
  )
  daily_rows = []
  for _, row in df.iterrows():
    dates = pd.date_range(
      start=row["date"],
      end=(
        row["next_date"]
        - pd.Timedelta(days=1)
      ),
      freq="D"
    )
    for date in dates:
      daily_rows.append({
        "date": date,
        "hbi_price": row["hbi_price"]
      })
  daily = pd.DataFrame(daily_rows)
  daily["month"] = (
    daily["date"]
    .dt.to_period("M")
    .dt.to_timestamp()
  )
  monthly = (
    daily
    .groupby(
      "month",
      as_index=False
    )
    .agg(
      hbi_price_wavg=(
        "hbi_price",
        "mean"
      ),
      hbi_price_min=(
        "hbi_price",
        "min"
      ),
      hbi_price_max=(
        "hbi_price",
        "max"
      ),
      hbi_price_start=(
        "hbi_price",
        "first"
      ),
      hbi_price_end=(
        "hbi_price",
        "last"
      )
    )
    .rename(
      columns={
        "month": "date"
      }
    )
  )
  monthly["hbi_price_change"] = (
    monthly["hbi_price_end"]
    - monthly["hbi_price_start"]
  )
  monthly["hbi_price_change_pct"] = (
    monthly["hbi_price_change"]
    / monthly["hbi_price_start"]
    * 100
  )
  monthly["hbi_price_range"] = (
    monthly["hbi_price_max"]
    - monthly["hbi_price_min"]
  )
  monthly["hbi_price_mom"] = (
    monthly["hbi_price_wavg"]
    .diff()
  )
  monthly["hbi_price_mom_pct"] = (
    monthly["hbi_price_wavg"]
    .pct_change()
    * 100
  )
  return monthly

METALTORG_API_KEY = os.getenv("METALTORG_API_KEY")
def load_metaltorg_series(api_id, column_name):
  if not METALTORG_API_KEY:
    raise ValueError(
      "METALTORG_API_KEY не найден в .env"
    )
  url = (
    f"https://www.metaltorg.ru/api/"
    f"?ID={api_id}"
    f"&API_KEY={METALTORG_API_KEY}"
    f"&format=JSON"
  )
  response = requests.get(
    url,
    timeout=120
  )
  response.raise_for_status()
  data = response.json()
  df = pd.DataFrame(
    data["data"]
  )
  df["date"] = pd.to_datetime(
    df["Year"].astype(str)
    + "-"
    + df["Month"].astype(str)
    + "-"
    + df["Day"].astype(str),
    errors="coerce"
  )
  df[column_name] = pd.to_numeric(
    df["Value"],
    errors="coerce"
  )
  df = (
    df[
      [
        "date",
        column_name
      ]
    ]
    .dropna()
    .sort_values("date")
    .reset_index(drop=True)
  )
  return df
# ==========================================================
# METALTORG: АРМАТУРА И ЗАГОТОВКА
# ==========================================================
REBAR_METALTORG_ID = 4389
BILLET_METALTORG_ID = 4484
def load_cbr_usd():
  url = (
    "https://www.cbr.ru/scripts/XML_dynamic.asp"
    "?date_req1=01/01/2020"
    "&date_req2=31/12/2030"
    "&VAL_NM_RQ=R01235"
  )
  response = requests.get(
    url,
    timeout=120
  )
  response.raise_for_status()
  # Читаем XML ЦБ
  df = pd.read_xml(
    response.content,
    xpath=".//Record"
  )
  df["date"] = pd.to_datetime(
    df["Date"],
    format="%d.%m.%Y",
    errors="coerce"
  )
  df["usd_rub"] = pd.to_numeric(
    df["Value"]
    .astype(str)
    .str.replace(",", ".", regex=False),
    errors="coerce"
  )
  df = (
    df[
      [
        "date",
        "usd_rub"
      ]
    ]
    .dropna()
    .sort_values("date")
    .reset_index(drop=True)
  )
  return df
def prepare_rebar_prices():
  # Цена производителей арматуры А3
  df = load_metaltorg_series(
    REBAR_METALTORG_ID,
    "rebar_price_vat"
  )
  # До 2026 года НДС 20%,
  # с 01.01.2026 — 22%
  vat_factor = pd.Series(
    1.20,
    index=df.index
  )
  vat_factor.loc[
    df["date"] >= pd.Timestamp("2026-01-01")
  ] = 1.22
  df["rebar_price"] = (
    df["rebar_price_vat"]
    / vat_factor
  )
  return df[
    [
      "date",
      "rebar_price"
    ]
  ]


def prepare_billet_prices():
  # Заготовка FOB Турция, $/т
  df = load_metaltorg_series(
    BILLET_METALTORG_ID,
    "billet_fob_usd"
  )
  usd = load_cbr_usd()
  # merge_asof подбирает последний известный
  # курс ЦБ на дату котировки
  df = pd.merge_asof(
    df.sort_values("date"),
    usd.sort_values("date"),
    on="date",
    direction="backward"
  )
  # Перевод $/т → руб./т
  df["billet_fob_rub"] = (
    df["billet_fob_usd"]
    * df["usd_rub"]
  )
  return df[
    [
      "date",
      "billet_fob_usd",
      "usd_rub",
      "billet_fob_rub"
    ]
  ]
def get_monthly_daily_market_price(
  df_daily,
  price_column,
  prefix
):
  df = (
    df_daily[
      [
        "date",
        price_column
      ]
    ]
    .dropna()
    .sort_values("date")
    .copy()
  )
  df["month"] = (
    df["date"]
    .dt.to_period("M")
    .dt.to_timestamp()
  )
  monthly = (
    df
    .groupby(
      "month",
      as_index=False
    )
    .agg(
      price_avg=(price_column, "mean"),
      price_min=(price_column, "min"),
      price_max=(price_column, "max"),
      price_start=(price_column, "first"),
      price_end=(price_column, "last")
    )
    .rename(
      columns={
        "month": "date"
      }
    )
  )
  monthly[f"{prefix}_avg"] = monthly["price_avg"]
  monthly[f"{prefix}_min"] = monthly["price_min"]
  monthly[f"{prefix}_max"] = monthly["price_max"]
  monthly[f"{prefix}_start"] = monthly["price_start"]
  monthly[f"{prefix}_end"] = monthly["price_end"]
  monthly[f"{prefix}_change"] = (
    monthly[f"{prefix}_end"]
    - monthly[f"{prefix}_start"]
  )
  monthly[f"{prefix}_change_pct"] = (
    monthly[f"{prefix}_change"]
    / monthly[f"{prefix}_start"]
    * 100
  )
  monthly[f"{prefix}_range"] = (
    monthly[f"{prefix}_max"]
    - monthly[f"{prefix}_min"]
  )
  monthly[f"{prefix}_mom"] = (
    monthly[f"{prefix}_avg"]
    .diff()
  )
  monthly[f"{prefix}_mom_pct"] = (
    monthly[f"{prefix}_avg"]
    .pct_change()
    * 100
  )
  return monthly[
    [
      "date",
      f"{prefix}_avg",
      f"{prefix}_min",
      f"{prefix}_max",
      f"{prefix}_start",
      f"{prefix}_end",
      f"{prefix}_change",
      f"{prefix}_change_pct",
      f"{prefix}_range",
      f"{prefix}_mom",
      f"{prefix}_mom_pct"
    ]
  ]
def get_scrap_supply_by_region(df):
  df = df.copy()
  # Присваиваем заводам нашу рыночную классификацию
  df["region"] = df["plant"].map(
    PLANT_REGIONS
  )
  # Всё, что не вошло в классификатор,
  # полностью исключаем
  df = df.dropna(
    subset=["region"]
  )
  # Разбираем месяц и год
  df["month_name"] = df["period"].str.extract(
    r"([а-яё]+\.)",
    expand=False
  )
  df["year"] = pd.to_numeric(
    df["period"].str.extract(
      r"(\d{4})",
      expand=False
    ),
    errors="coerce"
  )
  df["month"] = df["month_name"].map(
    MONTH_MAP
  )
  df["date"] = pd.to_datetime(
    dict(
      year=df["year"],
      month=df["month"],
      day=1
    ),
    errors="coerce"
  )
  # Суммируем поставки по месяцу и округу
  monthly = (
    df
    .groupby(
      ["date", "region"],
      as_index=False
    )["supply"]
    .sum()
  )
  # Округа превращаем в отдельные столбцы
  monthly = (
    monthly
    .pivot(
      index="date",
      columns="region",
      values="supply"
    )
    .reset_index()
  )
  monthly.columns.name = None
  monthly = monthly.rename(
    columns={
      "УФО": "scrap_supply_ufo_region",
      "ЦФО": "scrap_supply_cfo",
      "СФО": "scrap_supply_sfo",
      "ЮФО": "scrap_supply_yufo"
    }
  )
  return (
    monthly
    .sort_values("date")
    .reset_index(drop=True)
  )
def get_scrap_price_index_rf(regional_prices, supply_regions):
    df = regional_prices.merge(
        supply_regions,
        on="date",
        how="inner"
    )

    df["scrap_supply_4regions"] = (
        df["scrap_supply_ufo_region"]
        + df["scrap_supply_cfo"]
        + df["scrap_supply_sfo"]
        + df["scrap_supply_yufo"]
    )

    df["scrap_price_index_rf"] = (
        df["scrap_price_ufo"] * df["scrap_supply_ufo_region"]
        + df["scrap_price_cfo"] * df["scrap_supply_cfo"]
        + df["scrap_price_sfo"] * df["scrap_supply_sfo"]
        + df["scrap_price_yufo"] * df["scrap_supply_yufo"]
    ) / df["scrap_supply_4regions"]

    df["scrap_ufo_rf_spread"] = (
        df["scrap_price_ufo"]
        - df["scrap_price_index_rf"]
    )

    df["scrap_ufo_rf_spread_pct"] = (
        df["scrap_ufo_rf_spread"]
        / df["scrap_price_index_rf"]
        * 100
    )

    return df[
        [
            "date",
            "scrap_price_ufo",
            "scrap_price_cfo",
            "scrap_price_sfo",
            "scrap_price_yufo",
            "scrap_price_index_rf",
            "scrap_ufo_rf_spread",
            "scrap_ufo_rf_spread_pct",
            "scrap_supply_4regions"
        ]
    ].copy()






# ======================================================
def load_market_data():

  # ==========================================================
  # 1. АВТОРИЗАЦИЯ
  # ==========================================================
  token = get_metals_token()
  # ==========================================================
  # 2. ЦЕНЫ ЛОМА 3А
  # ==========================================================
  # Загружаем все котировки лома 3А
  raw_prices = load_scrap_prices(
    token
  )
  # Преобразуем ответ API в DataFrame
  df_prices = parse_scrap_prices(
    raw_prices
  )
  # Добавляем признаки:
  # регион, базис поставки, транспорт
  df_prices = add_scrap_attributes(
    df_prices
  )
  # ----------------------------------------------------------
  # ЦЕЛЕВАЯ НЕДЕЛЬНАЯ ЦЕНА УФО
  # ----------------------------------------------------------
  target_ufo = get_target_scrap_ufo(
    df_prices
  )
  # ----------------------------------------------------------
  # МЕСЯЧНАЯ СРЕДНЕВЗВЕШЕННАЯ ЦЕНА УФО
  # ----------------------------------------------------------
  monthly_price = get_monthly_weighted_scrap_price(
    target_ufo
  )
  # ----------------------------------------------------------
  # МЕСЯЧНЫЕ ЦЕНЫ 4 РЕГИОНОВ
  # УФО / ЦФО / СФО / ЮФО
  # ----------------------------------------------------------
  regional_prices = get_monthly_regional_scrap_prices(
    df_prices
  )
  # ==========================================================
  # 3. ПОСТАВКИ ЛОМА В УФО
  # ==========================================================
  print("Загрузка поставок лома...")
  raw_supply = load_scrap_supply(
    token
  )
  df_supply = parse_scrap_supply(
    raw_supply
  )
  supply_ufo = get_scrap_supply_ufo(
    df_supply
  )
  supply_ru = get_scrap_supply_ru(
  df_supply)
  supply_regions = get_scrap_supply_by_region(
    df_supply
  )
  scrap_index_rf = get_scrap_price_index_rf(
    regional_prices,
    supply_regions
)




  supply_regions_for_merge = supply_regions[
  [
    "date",
    "scrap_supply_cfo",
    "scrap_supply_sfo",
    "scrap_supply_yufo"
  ]
]
# ======================================================
# ==========================================================
  # 4. ПРОИЗВОДСТВО ЭЛЕКТРОСТАЛИ В РОССИИ
  # ==========================================================
  print("Загрузка производства электростали...")
  raw_eaf = load_eaf_production(
    token
  )
  df_eaf = parse_eaf_production(
    raw_eaf
  )
  eaf_ru = get_eaf_production_ru(
    df_eaf
  )
  eaf_ufo = get_eaf_production_ufo(
  df_eaf)
  # ==========================================================
  # 5. ЦЕНА ЧУГУНА РФ
  # ==========================================================
  print("Загрузка цены чугуна...")
  raw_pig_iron = load_pig_iron_prices(
    token
  )
  df_pig_iron = parse_pig_iron_prices(
    raw_pig_iron
  )
  pig_iron_monthly = get_monthly_pig_iron_price(
    df_pig_iron
  )
    # ==========================================================
  # 6. ЦЕНА ГБЖ РФ
  # ==========================================================
  print("Загрузка цены ГБЖ...")
  raw_hbi = load_hbi_prices(
    token
  )
  df_hbi = parse_hbi_prices(
    raw_hbi
  )
  hbi_monthly = get_monthly_hbi_price(
    df_hbi
  )
  # ==========================================================
  # АРМАТУРА
  # ==========================================================
  print("Загрузка цены арматуры...")
  df_rebar = prepare_rebar_prices()
  rebar_monthly = get_monthly_daily_market_price(
    df_rebar,
    price_column="rebar_price",
    prefix="rebar_price"
  )
  # ==========================================================
  # ЗАГОТОВКА FOB ТУРЦИЯ
  # ==========================================================
  print("Загрузка цены заготовки...")
  df_billet = prepare_billet_prices()
  billet_monthly = get_monthly_daily_market_price(
    df_billet,
    price_column="billet_fob_rub",
    prefix="billet_fob_rub"
  )
  # ==========================================================
  # 5. ЕДИНЫЙ МЕСЯЧНЫЙ ДАТАСЕТ
  # ==========================================================
  df_monthly = (
    monthly_price
    .merge(
      supply_ufo,
      on="date",
      how="inner"
    )
    .merge(
      supply_ru,
      on="date",
      how="left"
    )
    .merge(
      eaf_ru,
      on="date",
      how="left"
    )
    .merge(
      eaf_ufo,
      on="date",
      how="left"
    )
   .merge(
      pig_iron_monthly,
      on="date",
      how="left"
    )
    .merge(
      hbi_monthly,
      on="date",
      how="left"
    )
     .merge(
      rebar_monthly,
      on="date",
      how="left"
    )
    .merge(
      billet_monthly,
      on="date",
      how="left"
    )
    .merge(
      supply_regions_for_merge,
      on="date",
      how="left"
    )
    .merge(
    scrap_index_rf[
        [
            "date",
            "scrap_price_index_rf",
            "scrap_ufo_rf_spread",
            "scrap_ufo_rf_spread_pct"
        ]
    ],
    on="date",
    how="left"
)


  )
  # Изменение поставок лома месяц к месяцу
  df_monthly["scrap_supply_mom"] = (
    df_monthly["scrap_supply_ufo"]
    .diff()
  )
  df_monthly["scrap_supply_mom_pct"] = (
    df_monthly["scrap_supply_ufo"]
    .pct_change()
    * 100
  )
  return df_monthly

def load_price_indicators():

    token = get_metals_token()

    # ==================================================
    # ЛОМ
    # ==================================================

    raw_prices = load_scrap_prices(token)

    scrap_all = parse_scrap_prices(
        raw_prices
    )

    scrap_all = add_scrap_attributes(
        scrap_all
    )

    # Лом 3А УФО
    scrap = get_target_scrap_ufo(
        scrap_all
    )


    # ==================================================
    # АРМАТУРА
    # ==================================================

    rebar = prepare_rebar_prices()


    # ==================================================
    # ГБЖ
    # ==================================================

    raw_hbi = load_hbi_prices(token)

    hbi = parse_hbi_prices(
        raw_hbi
    )


    # ==================================================
    # ЧУГУН
    # ==================================================

    raw_pig = load_pig_iron_prices(token)

    pig = parse_pig_iron_prices(
        raw_pig
    )


    # ==================================================
    # ЗАГОТОВКА
    # ==================================================

    billet = prepare_billet_prices()


    # ==================================================
    # ПОСТАВКИ ЛОМА ПО РЕГИОНАМ
    # для расчёта индекса РФ
    # ==================================================

    raw_supply = load_scrap_supply(
        token
    )

    df_supply = parse_scrap_supply(
        raw_supply
    )

    supply_regions = get_scrap_supply_by_region(
        df_supply
    )


    # ==================================================
    # ИНДЕКС ЦЕН ЛОМА РФ
    # ==================================================

    scrap_index = get_current_scrap_index_rf(
        scrap_all,
        supply_regions
    )


    # ==================================================
    # РЕЗУЛЬТАТ
    # ==================================================

    return {
        "scrap": scrap,
        "scrap_index": scrap_index,
        "rebar": rebar,
        "hbi": hbi,
        "pig": pig,
        "billet": billet
    }
def get_current_scrap_index_rf(
    scrap_all,
    supply_regions
):

    # --------------------------------------------------
    # ЦЕНЫ ЛОМА 4 РЕГИОНОВ
    # --------------------------------------------------

    prices = scrap_all[
        (scrap_all["basis"] == "CPT")
        & (scrap_all["transport"] == "ж/д")
        & (scrap_all["region"].isin([
            "Уральский ФО",
            "Центральный ФО",
            "Сибирский ФО",
            "Южный ФО"
        ]))
    ][
        ["date", "region", "price"]
    ].copy()

    prices["date"] = pd.to_datetime(
        prices["date"]
    )

    prices["month"] = (
        prices["date"]
        .dt.to_period("M")
    )

    # Последняя котировка каждого региона
    # в каждом месяце
    prices = (
        prices
        .sort_values("date")
        .groupby(
            ["month", "region"],
            as_index=False
        )
        .tail(1)
    )

    # Регионы -> столбцы
    prices = (
        prices
        .pivot(
            index="month",
            columns="region",
            values="price"
        )
        .reset_index()
    )

    prices.columns.name = None

    prices = prices.rename(
        columns={
            "Уральский ФО": "price_ufo",
            "Центральный ФО": "price_cfo",
            "Сибирский ФО": "price_sfo",
            "Южный ФО": "price_yufo"
        }
    )


    # --------------------------------------------------
    # ПОСТАВКИ
    # --------------------------------------------------

    supply = supply_regions.copy()

    supply["date"] = pd.to_datetime(
        supply["date"]
    )

    supply["month"] = (
        supply["date"]
        .dt.to_period("M")
    )

    supply = supply[
        [
            "month",
            "scrap_supply_ufo_region",
            "scrap_supply_cfo",
            "scrap_supply_sfo",
            "scrap_supply_yufo"
        ]
    ]


    # --------------------------------------------------
    # ОБЪЕДИНЯЕМ
    # --------------------------------------------------

    result = prices.merge(
        supply,
        on="month",
        how="left"
    )

    # Поставки публикуются с лагом.
    # Для более свежих цен используем
    # последние доступные веса.
    supply_cols = [
        "scrap_supply_ufo_region",
        "scrap_supply_cfo",
        "scrap_supply_sfo",
        "scrap_supply_yufo"
    ]

    result[supply_cols] = (
        result[supply_cols]
        .ffill()
    )


    # --------------------------------------------------
    # ИНДЕКС РФ
    # --------------------------------------------------

    total_supply = (
        result["scrap_supply_ufo_region"]
        + result["scrap_supply_cfo"]
        + result["scrap_supply_sfo"]
        + result["scrap_supply_yufo"]
    )

    result["scrap_index_current"] = (
        result["price_ufo"]
        * result["scrap_supply_ufo_region"]

        + result["price_cfo"]
        * result["scrap_supply_cfo"]

        + result["price_sfo"]
        * result["scrap_supply_sfo"]

        + result["price_yufo"]
        * result["scrap_supply_yufo"]
    ) / total_supply


    # --------------------------------------------------
    # ДАТА ДЛЯ APP
    # --------------------------------------------------

    result["date"] = (
        result["month"]
        .dt.to_timestamp("M")
    )


    return (
        result[
            [
                "date",
                "scrap_index_current"
            ]
        ]
        .dropna(
            subset=["scrap_index_current"]
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
def load_fair_value_data():

    # ==========================================================
    # АВТОРИЗАЦИЯ
    # ==========================================================

    token = get_metals_token()

    # ==========================================================
    # ЛОМ 3А УФО
    # ==========================================================

    raw_prices = load_scrap_prices(token)

    df_prices = parse_scrap_prices(raw_prices)

    df_prices = add_scrap_attributes(df_prices)

    target_ufo = get_target_scrap_ufo(df_prices)

    monthly_price = get_monthly_weighted_scrap_price(
        target_ufo
    )

    # ==========================================================
    # ГБЖ
    # ==========================================================

    raw_hbi = load_hbi_prices(token)

    df_hbi = parse_hbi_prices(raw_hbi)

    hbi_monthly = get_monthly_hbi_price(
        df_hbi
    )

    # ==========================================================
    # АРМАТУРА
    # ==========================================================

    df_rebar = prepare_rebar_prices()

    rebar_monthly = get_monthly_daily_market_price(
        df_rebar,
        price_column="rebar_price",
        prefix="rebar_price"
    )

    # ==========================================================
    # ДАТАСЕТ ДЛЯ FAIR VALUE
    # ==========================================================

    fair_value_data = (
        monthly_price[
            [
                "date",
                "scrap_price_wavg"
            ]
        ]
        .merge(
            hbi_monthly[
                [
                    "date",
                    "hbi_price_wavg"
                ]
            ],
            on="date",
            how="inner"
        )
        .merge(
            rebar_monthly[
                [
                    "date",
                    "rebar_price_avg"
                ]
            ],
            on="date",
            how="inner"
        )
        .sort_values("date")
        .reset_index(drop=True)
    )

    return fair_value_data