import os
import json
import re

import requests
import streamlit as st
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError, APIError

# Раз в месяц меняем только эту ссылку.
INFOLOM_ZVER_URL = "https://infolom.su/zver08102026/"

load_dotenv()


@st.cache_resource
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        api_key = st.secrets["OPENAI_API_KEY"]
    return OpenAI(api_key=api_key)


client = get_openai_client()


def _clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _fallback(message):
    return {
        "current_assessment": message,
        "next_month": "",
        "market_factors": "",
        "structural_outlook": "",
        "procurement_conclusion": "",
        "sources": [],
    }


def _parse_json_response(response):
    text = getattr(response, "output_text", None)
    if not text:
        raise ValueError("OpenAI вернул пустой ответ")
    return json.loads(text)


@st.cache_data(ttl=86400)
def load_infolom_zver():
    """Загружает текущий обзор INFOLOM «ЗВЁР». Кэш — 24 часа."""
    try:
        print("INFOLOM ZVER: START", flush=True)
        response = requests.get(
            INFOLOM_ZVER_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                )
            },
            timeout=10,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()

        article = (
            soup.find("article")
            or soup.find(class_="entry-content")
            or soup.find(class_="post-content")
            or soup.find("main")
        )
        if article is None:
            raise ValueError("Не найден текст статьи INFOLOM")

        text = _clean_text(article.get_text(" ", strip=True))
        if len(text) < 500:
            raise ValueError("Текст обзора INFOLOM слишком короткий")

        text = text[:30000]
        print(f"INFOLOM ZVER: FINISH ({len(text)} chars)", flush=True)
        return {"status": "ok", "url": INFOLOM_ZVER_URL, "text": text}

    except requests.Timeout:
        print("INFOLOM ZVER: TIMEOUT", flush=True)
    except requests.RequestException as exc:
        print(f"INFOLOM ZVER: REQUEST ERROR: {type(exc).__name__}: {exc}", flush=True)
    except Exception as exc:
        print(f"INFOLOM ZVER: ERROR: {type(exc).__name__}: {exc}", flush=True)

    return {"status": "unavailable", "url": INFOLOM_ZVER_URL, "text": ""}


def _infolom_prompt(context):
    if context.get("status") != "ok":
        return (
            "Обзор INFOLOM «ЗВЁР» загрузить не удалось. "
            "Не утверждай, что фундаментальных факторов нет, и не придумывай внешние новости. "
            "В market_factors напиши только: «Обзор INFOLOM не удалось загрузить.»"
        )
    return f"""
Ниже текст текущего ежемесячного обзора INFOLOM «ЗВЁР».
Источник: {context['url']}

ТЕКСТ ОБЗОРА:
{context['text']}

Используй только факты из этого текста. Не добавляй внешние новости и сведения из собственных знаний.
""".strip()


@st.cache_data(ttl=21600)
def _generate_cached(
    current_price,
    fair_value,
    fair_value_diff_pct,
    spread_z,
    forecast_next_month,
    forecast_change_pct,
    price_trend,
    trend_change_pct,
    trend_start_date,
    trend_end_date,
    purchase_title,
    recommendation,
    rebar_scrap_status,
    rebar_scrap_current,
    rebar_scrap_p25,
    rebar_scrap_p75,
    scrap_hbi_status,
    scrap_hbi_current,
    scrap_hbi_p25,
    scrap_hbi_p75,
    infolom_context_json,
):
    context = json.loads(infolom_context_json)

    prompt = f"""
Ты — аналитик российского рынка стального лома. Подготовь краткий профессиональный комментарий
по рынку лома 3А в Уральском федеральном округе (УФО).

Web search НЕ используй. Анализ строится на трех независимых блоках:
1) математический прогноз системы;
2) внутренние ценовые индикаторы — два спреда;
3) ежемесячный отраслевой обзор INFOLOM «ЗВЁР».

Главная задача — сопоставить три сигнала и объяснить их значение для цены лома и закупок.
Не создавай собственного числового прогноза: прогноз системы является базовым.

ИСХОДНЫЕ ДАННЫЕ
Текущая цена: {current_price:,.0f} руб./т.
Fair value: {fair_value:,.0f} руб./т.
Отклонение от fair value: {fair_value_diff_pct:+.1f}%.
Тренд: {price_trend}.
Изменение за период {trend_start_date} — {trend_end_date}: {trend_change_pct:+.1f}%.
Прогноз на следующий месяц: {forecast_next_month:,.0f} руб./т ({forecast_change_pct:+.1f}% к текущей цене).

СПРЕД АРМАТУРА − ЛОМ
Текущее значение: {rebar_scrap_current:,.0f} руб./т; P25: {rebar_scrap_p25:,.0f}; P75: {rebar_scrap_p75:,.0f}; статус: {rebar_scrap_status}.
Правила: выше P75 -> СНИЖЕНИЕ цены лома; ниже P25 -> РОСТ цены лома; между P25 и P75 -> НЕЙТРАЛЬНО.
Экономический смысл: высокий спред означает, что текущий уровень цены арматуры допускает дальнейшее снижение лома;
низкий спред означает, что потенциал дальнейшего снижения лома ограничен.

СПРЕД ЛОМ − ГБЖ
Текущее значение: {scrap_hbi_current:,.0f} руб./т; P25: {scrap_hbi_p25:,.0f}; P75: {scrap_hbi_p75:,.0f}; статус: {scrap_hbi_status}.
Правила: выше P75 -> лом дорог относительно ГБЖ -> СНИЖЕНИЕ цены лома;
ниже P25 -> лом дешев относительно ГБЖ -> РОСТ цены лома; между P25 и P75 -> НЕЙТРАЛЬНО.

ОБЩИЙ СИГНАЛ СПРЕДОВ
Классифицируй каждый спред как РОСТ / СНИЖЕНИЕ / НЕЙТРАЛЬНО.
Оба рост -> РОСТ; оба снижение -> СНИЖЕНИЕ; противоположные -> ПРОТИВОРЕЧИВЫЙ;
оба нейтральны -> выраженного сигнала НЕТ; один нейтрален -> направление второго, но сигнал СЛАБЫЙ.
В итоговом тексте не перечисляй механически P25/P75. Не используй термин Z-score и значение {spread_z}.

INFOLOM «ЗВЁР»
{_infolom_prompt(context)}

Если обзор доступен:
- не пересказывай его целиком;
- выбери максимум 3 наиболее значимых для цены лома фактора;
- приоритет: ломозаготовка и предложение, выполнение планов и запасы лома, потребность металлургии,
  производство стали/сортового проката, спрос и цены на арматуру, загрузка мощностей, экспорт, регулирование,
  логистика и сезонность;
- показывай причинную цепочку: событие -> предложение/потребление лома -> влияние на цену;
- определи общий сигнал INFOLOM: РОСТ / СНИЖЕНИЕ / СТАБИЛИЗАЦИЯ / СМЕШАННЫЙ;
- сопоставь его с математическим прогнозом и спредами;
- не добавляй фактов, которых нет в обзоре.

РЕКОМЕНДАЦИЯ СИСТЕМЫ
Сигнал: {purchase_title}
Рекомендация: {recommendation}
Направление рекомендации НЕ МЕНЯЙ. Объясни ее через тренд, fair value, прогноз, спреды и INFOLOM.
Если один из сигналов противоречит рекомендации, прямо назови это риском.

СТИЛЬ
Аудитория — закупочное подразделение металлургической компании.
Пиши коротко, конкретно, причинно-следственно, без журналистских оборотов и канцеляризмов.
Используй прямые формулировки: «спред указывает на снижение цены лома», «спред указывает на рост цены лома»,
«спред не дает выраженного сигнала», «INFOLOM подтверждает математический прогноз»,
«INFOLOM не подтверждает математический прогноз», «закупку целесообразно отложить», «закупать поэтапно».

ПОЛЯ ОТВЕТА
current_assessment: 2–3 коротких предложения. Только тренд + fair value + общий сигнал спредов. Без INFOLOM.
next_month: 2–3 предложения. Числовой прогноз + согласованность со спредами + подтверждает ли направление INFOLOM.
market_factors: если INFOLOM доступен — 2–4 предложения, максимум 3 ключевых фактора. Заверши прямым итогом
«В целом обзор INFOLOM указывает на рост/снижение/стабилизацию цены лома» или «В целом сигнал INFOLOM смешанный».
Если INFOLOM недоступен — только «Обзор INFOLOM не удалось загрузить.»
structural_outlook: всегда пустая строка "". Прогноз 6–12 месяцев больше не используется.
procurement_conclusion: не более 2–3 предложений. Сохрани направление рекомендации системы и сопоставь прогноз, спреды и INFOLOM.
sources: всегда пустой список []; источник будет добавлен программно.
"""

    schema = {
        "type": "object",
        "properties": {
            "current_assessment": {"type": "string"},
            "next_month": {"type": "string"},
            "market_factors": {"type": "string"},
            "structural_outlook": {"type": "string"},
            "procurement_conclusion": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "current_assessment", "next_month", "market_factors",
            "structural_outlook", "procurement_conclusion", "sources"
        ],
        "additionalProperties": False,
    }

    try:
        print("SCRAP AI: MAIN COMMENTARY START", flush=True)
        response = client.with_options(timeout=60.0, max_retries=0).responses.create(
            model="gpt-5-mini",
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "scrap_3a_ufo_commentary",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        print("SCRAP AI: MAIN COMMENTARY FINISH", flush=True)

        result = _parse_json_response(response)
        result["structural_outlook"] = ""
        result["sources"] = (
            [f"INFOLOM «ЗВЁР»: {INFOLOM_ZVER_URL}"]
            if context.get("status") == "ok" else []
        )
        return result

    except RateLimitError:
        return _fallback("AI-комментарий временно недоступен: превышен лимит OpenAI API.")
    except APITimeoutError:
        return _fallback("AI-комментарий временно недоступен: OpenAI API не ответил за 60 секунд.")
    except APIConnectionError:
        return _fallback("AI-комментарий временно недоступен: ошибка соединения с OpenAI API.")
    except APIError as exc:
        print(f"SCRAP AI: API ERROR: {exc}", flush=True)
        return _fallback("AI-комментарий временно недоступен: ошибка OpenAI API.")
    except Exception as exc:
        print(f"SCRAP AI: OTHER ERROR: {type(exc).__name__}: {exc}", flush=True)
        return _fallback("AI-комментарий временно недоступен из-за технической ошибки.")


# Публичная функция. Сигнатура сохранена — app.py менять не нужно.
def generate_scrap_ai_commentary(
    current_price,
    fair_value,
    fair_value_diff_pct,
    spread_z,
    forecast_next_month,
    forecast_change_pct,
    price_trend,
    trend_change_pct,
    trend_start_date,
    trend_end_date,
    purchase_title,
    recommendation,
    rebar_scrap_status,
    rebar_scrap_current,
    rebar_scrap_p25,
    rebar_scrap_p75,
    scrap_hbi_status,
    scrap_hbi_current,
    scrap_hbi_p25,
    scrap_hbi_p75,
):
    infolom_context = load_infolom_zver()
    infolom_context_json = json.dumps(infolom_context, ensure_ascii=False, sort_keys=True)

    return _generate_cached(
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
        purchase_title=purchase_title,
        recommendation=recommendation,
        rebar_scrap_status=rebar_scrap_status,
        rebar_scrap_current=rebar_scrap_current,
        rebar_scrap_p25=rebar_scrap_p25,
        rebar_scrap_p75=rebar_scrap_p75,
        scrap_hbi_status=scrap_hbi_status,
        scrap_hbi_current=scrap_hbi_current,
        scrap_hbi_p25=scrap_hbi_p25,
        scrap_hbi_p75=scrap_hbi_p75,
        infolom_context_json=infolom_context_json,
    )
