import os

import json

from datetime import datetime, timedelta



import streamlit as st

from dotenv import load_dotenv

from openai import (

    OpenAI,

    RateLimitError,

    APITimeoutError,

    APIConnectionError,

    APIError,

)





# ======================================================

# OPENAI CLIENT

# ======================================================



load_dotenv()





@st.cache_resource

def get_openai_client():

    api_key = os.getenv("OPENAI_API_KEY")



    if not api_key:

        api_key = st.secrets["OPENAI_API_KEY"]



    return OpenAI(api_key=api_key)





client = get_openai_client()





# ======================================================

# FALLBACKS

# ======================================================



def get_ai_fallback(message):

    return {

        "current_assessment": message,

        "next_month": "",

        "market_factors": "",

        "structural_outlook": "",

        "procurement_conclusion": "",

        "sources": [],

    }





def get_search_fallback(message):

    return {

        "status": "unavailable",

        "message": message,

        "factors": [],

    }





# ======================================================

# HELPERS

# ======================================================



def _parse_json_response(response):

    text = getattr(response, "output_text", None)



    if not text:

        raise ValueError("OpenAI вернул пустой ответ")



    return json.loads(text)





def _validate_factors(factors, start_date, end_date):
    valid = []
    for factor in factors:
        try:
            publication_date = datetime.strptime(factor["publication_date"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        if not (start_date <= publication_date <= end_date):
            continue
        haystack = " ".join([
            str(factor.get("source_url", "")).lower(),
            str(factor.get("source_name", "")).lower(),
            str(factor.get("event", "")).lower(),
        ])
        if any(x in haystack for x in ("bidzaar", "тендер", "объявлен", "каталог", "агрегатор")):
            continue
        valid.append(factor)
    return valid[:2]


def _factor_lines(title, factors):
    lines = [title]
    for i, f in enumerate(factors, 1):
        lines.append(
            f"{i}. Событие: {f['event']}\n"
            f"   Дата публикации: {f['publication_date']}\n"
            f"   Источник: {f['source_name']}\n"
            f"   Ссылка: {f['source_url']}\n"
            f"   Механизм: {f['mechanism']}\n"
            f"   Сигнал для цены лома: {f['price_effect']}"
        )
    return "\n\n".join(lines)


def _external_context_text(market_context):
    if market_context.get("status") != "ok":
        return (
            "WEB SEARCH НЕ УДАЛОСЬ ВЫПОЛНИТЬ. Не делай вывод, что факторов нет. "
            "Не придумывай внешние факты. Для краткосрочного раздела укажи, что "
            "свежий фон не удалось проверить. Для структурного раздела дай только "
            "осторожный сценарный вывод из внутренних данных и отметь отсутствие "
            "внешнего подтверждения."
        )
    current = market_context.get("current_factors", [])
    structural = market_context.get("structural_factors", [])
    parts = []
    parts.append(_factor_lines("СВЕЖИЕ ФАКТОРЫ — текущий рынок / следующий месяц:", current)
                 if current else "СВЕЖИЕ ФАКТОРЫ: подходящих подтверждённых публикаций за последние 30 дней не найдено.")
    parts.append(_factor_lines("СТРУКТУРНЫЕ ФАКТОРЫ — горизонт 6–12 месяцев:", structural)
                 if structural else "СТРУКТУРНЫЕ ФАКТОРЫ: отдельного подходящего структурного подтверждения за последние 12 месяцев не найдено.")
    parts.append("Используй только перечисленные внешние факты. Не добавляй новости, даты или источники от себя.")
    return "\n\n".join(parts)


def _sources_from_context(market_context):
    if market_context.get("status") != "ok":
        return []
    sources, seen = [], set()
    factors = market_context.get("current_factors", []) + market_context.get("structural_factors", [])
    for factor in factors:
        name = str(factor.get("source_name", "")).strip()
        url = str(factor.get("source_url", "")).strip()
        if not name:
            continue
        item = f"{name} — {url}" if url else name
        if item not in seen:
            seen.add(item)
            sources.append(item)
    return sources


# ======================================================
# STAGE 1 — SHORT WEB SEARCH

# ======================================================



@st.cache_data(ttl=21600)
def search_scrap_market_factors():
    """Один короткий web search: свежие 30 дней + структурные 12 месяцев."""
    today = datetime.now().date()
    current_start = today - timedelta(days=30)
    structural_start = today - timedelta(days=365)

    prompt = f"""
Ты выполняешь ОДИН короткий поиск фундаментального фона российского рынка стального лома.
Приоритет — Россия и УФО. Текущая дата: {today.strftime('%d.%m.%Y')}.

Верни ДВА РАЗНЫХ набора факторов.

current_factors — максимум 2 фактора с датой публикации от
{current_start.strftime('%d.%m.%Y')} до {today.strftime('%d.%m.%Y')}.
Они должны объяснять рынок сейчас и возможное движение в следующем месяце.

structural_factors — максимум 2 фактора с датой публикации от
{structural_start.strftime('%d.%m.%Y')} до {today.strftime('%d.%m.%Y')}.
Они должны быть пригодны для горизонта 6–12 месяцев: устойчивое изменение
ломозаготовки или потребления лома, загрузка/ввод/остановка ЭСП-мощностей,
изменение производства стали или структуры шихты, регулирование оборота/экспорта,
крупное изменение логистики или регионального баланса.

Для каждого фактора нужна цепочка:
событие -> предложение/потребление лома -> направление цены лома.

Приоритет: INFOLOM, Rusmet, официальные ведомства и РЖД, металлургические компании,
отраслевые ассоциации, специализированные металлургические СМИ.

Не используй тендеры, Bidzaar, объявления, коммерческие предложения, каталоги,
агрегаторы, сайты продавцов, недатированные публикации и общие макроновости без
прямой связи с российским рынком лома.

Не продолжай поиск ради количества. Один сильный фактор лучше двух слабых.
Если подходящего фактора нет — верни пустой список. Не подменяй structural_factors
обычными краткосрочными новостями.
"""

    factor_schema = {
        "type": "object",
        "properties": {
            "event": {"type": "string"},
            "publication_date": {"type": "string"},
            "source_name": {"type": "string"},
            "source_url": {"type": "string"},
            "mechanism": {"type": "string"},
            "price_effect": {"type": "string", "enum": ["РОСТ", "СНИЖЕНИЕ", "НЕЙТРАЛЬНО"]},
        },
        "required": ["event", "publication_date", "source_name", "source_url", "mechanism", "price_effect"],
        "additionalProperties": False,
    }
    response_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["ok"]},
            "current_factors": {"type": "array", "maxItems": 2, "items": factor_schema},
            "structural_factors": {"type": "array", "maxItems": 2, "items": factor_schema},
        },
        "required": ["status", "current_factors", "structural_factors"],
        "additionalProperties": False,
    }

    try:
        print("SCRAP WEB SEARCH: START", flush=True)
        response = client.with_options(timeout=30.0, max_retries=0).responses.create(
            model="gpt-5-mini",
            tools=[{"type": "web_search", "search_context_size": "low"}],
            input=prompt,
            text={"format": {"type": "json_schema", "name": "scrap_market_context", "strict": True, "schema": response_schema}},
        )
        print("SCRAP WEB SEARCH: FINISH", flush=True)
        result = _parse_json_response(response)
        result["current_factors"] = _validate_factors(result.get("current_factors", []), current_start, today)
        result["structural_factors"] = _validate_factors(result.get("structural_factors", []), structural_start, today)
        result["status"] = "ok"
        return result
    except APITimeoutError:
        print("SCRAP WEB SEARCH: TIMEOUT after 30 seconds", flush=True)
        return get_search_fallback("OpenAI web search не ответил за 30 секунд")
    except RateLimitError:
        return get_search_fallback("Лимит OpenAI API")
    except APIConnectionError:
        return get_search_fallback("Ошибка соединения с OpenAI API")
    except APIError as exc:
        print(f"SCRAP WEB SEARCH: APIError: {exc}", flush=True)
        return get_search_fallback("Ошибка OpenAI API")
    except Exception as exc:
        print(f"SCRAP WEB SEARCH: OTHER ERROR: {type(exc).__name__}: {exc}", flush=True)
        return get_search_fallback("Ошибка при проверке внешнего фона")


# ======================================================
# STAGE 2 — MAIN AI COMMENTARY WITHOUT WEB SEARCH

# ======================================================



@st.cache_data(ttl=21600)

def _generate_scrap_ai_commentary_cached(

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

    market_context_json,

):

    market_context = json.loads(market_context_json)

    external_context = _external_context_text(market_context)



    prompt = f"""

Ты — аналитик российского рынка стального лома.



Подготовь краткий профессиональный комментарий по рынку стального лома 3А

в Уральском федеральном округе (УФО).



Ты НЕ выполняешь web search в этом запросе.

Внешний фундаментальный фон уже подготовлен отдельно и приведён ниже.

Используй только его. Не придумывай новости, события, даты и источники.



Анализ объединяет:

1\. фактическую динамику цены и расчёт справедливой стоимости;

2\. внутренние количественные индикаторы — два спреда;

3\. отдельно проверенный свежий фундаментальный фон.



Математический прогноз является базовым прогнозом системы.

Не заменяй его собственным числовым прогнозом.

Определи, подтверждают ли внутренние индикаторы и внешний фон математический

прогноз или создают риск отклонения от него.



==================================================

ИСХОДНЫЕ ДАННЫЕ

==================================================



Текущая цена лома:

{current_price:,.0f} руб./т



Расчётная справедливая стоимость:

{fair_value:,.0f} руб./т



Отклонение текущей цены от справедливой стоимости:

{fair_value_diff_pct:+.1f}%



Текущий ценовой тренд:

{price_trend}



Изменение цены за рассматриваемый период:

{trend_change_pct:+.1f}%



Период:

{trend_start_date} — {trend_end_date}



Математический прогноз на следующий месяц:

{forecast_next_month:,.0f} руб./т



Изменение относительно текущей цены:

{forecast_change_pct:+.1f}%



==================================================

1\. СПРЕД АРМАТУРА − ЛОМ

==================================================



Текущее значение: {rebar_scrap_current:,.0f} руб./т

25-й перцентиль: {rebar_scrap_p25:,.0f} руб./т

75-й перцентиль: {rebar_scrap_p75:,.0f} руб./т

Состояние: {rebar_scrap_status}



Этот индикатор используется для оценки вероятного направления цены лома.



ПРАВИЛА:

- если значение ВЫШЕ 75-го перцентиля: сигнал на СНИЖЕНИЕ цены лома;

  текущий уровень цены арматуры допускает дальнейшее снижение цены лома;

- если значение НИЖЕ 25-го перцентиля: сигнал на РОСТ цены лома;

  потенциал дальнейшего снижения цены лома ограничен;

- между 25-м и 75-м перцентилями: НЕЙТРАЛЬНЫЙ сигнал.



Формулируй вывод прямо:

"спред указывает на снижение цены лома",

"спред указывает на рост цены лома"

или

"спред не даёт выраженного сигнала".



==================================================

2\. СПРЕД ЛОМ − ГБЖ

==================================================



Текущее значение: {scrap_hbi_current:,.0f} руб./т

25-й перцентиль: {scrap_hbi_p25:,.0f} руб./т

75-й перцентиль: {scrap_hbi_p75:,.0f} руб./т

Состояние: {scrap_hbi_status}



Этот индикатор показывает положение цены лома относительно альтернативной

металлической шихты — ГБЖ.



ПРАВИЛА:

- если значение ВЫШЕ 75-го перцентиля: лом дорог относительно ГБЖ,

  сигнал на СНИЖЕНИЕ цены лома;

- если значение НИЖЕ 25-го перцентиля: лом дешёв относительно ГБЖ,

  сигнал на РОСТ цены лома;

- между 25-м и 75-м перцентилями: НЕЙТРАЛЬНЫЙ сигнал.



Формулируй вывод прямо:

"лом дорог относительно ГБЖ — индикатор указывает на снижение цены лома",

"лом дешёв относительно ГБЖ — индикатор указывает на рост цены лома"

или

"соотношение лом/ГБЖ находится в нейтральной зоне".



==================================================

КАК ОБЪЕДИНЯТЬ СПРЕДЫ

==================================================



Главная задача спредов — определить направление сигнала для цены лома.



Сначала классифицируй каждый спред:

РОСТ / СНИЖЕНИЕ / НЕЙТРАЛЬНО.



Затем сформируй общий внутренний сигнал:

- оба указывают на рост -> РОСТ;

- оба указывают на снижение -> СНИЖЕНИЕ;

- один на рост, другой на снижение -> ПРОТИВОРЕЧИВЫЙ сигнал;

- оба нейтральны -> выраженного сигнала НЕТ;

- один нейтрален -> направление определяется вторым, но сигнал СЛАБЫЙ.



Не перечисляй механически значения и перцентили в итоговом тексте.

Главное — прямо сказать, что спреды означают для направления цены лома.



Обязательно сопоставь внутренний сигнал с математическим прогнозом.

Если он противоречит прогнозу — прямо укажи риск отклонения.

Если согласуется — скажи об этом прямо.



Не используй термин Z-score и не показывай значение spread_z.



==================================================

СВЕЖИЙ ВНЕШНИЙ ФУНДАМЕНТАЛЬНЫЙ ФОН

==================================================



{external_context}



Правила:

- если поиск недоступен, НЕ утверждай, что свежих факторов нет;

- если поиск выполнен и factors пуст, можно сказать, что подходящих свежих

  подтверждённых факторов за последние 30 дней не найдено;

- если факторы есть, используй максимум два;

- для каждого фактора покажи цепочку:

  событие -> предложение/потребление лома -> направление цены;

- не придумывай дополнительные новости или источники.



==================================================

СТРУКТУРНЫЙ ГОРИЗОНТ 6–12 МЕСЯЦЕВ

==================================================



Оцени только общий структурный баланс:

- предложение лома;

- потребность металлургии;

- загрузку электросталеплавильных мощностей;

- структуру металлической шихты;

- сезонность;

- регулирование;

- логистику.



Если предоставленных данных недостаточно для уверенного структурного вывода,

скажи об этом кратко. Не придумывай долгосрочные факты.

Не называй точную цену лома через 6–12 месяцев.



==================================================

ЗАКУПОЧНАЯ РЕКОМЕНДАЦИЯ СИСТЕМЫ

==================================================



Сигнал системы:

{purchase_title}



Рекомендация системы:

{recommendation}



НЕ меняй направление рекомендации системы.

Объясни её через текущий тренд, fair value, математический прогноз,

два спреда и доступный фундаментальный фон.



Если какой-либо показатель противоречит рекомендации,

не меняй рекомендацию, а прямо укажи этот фактор как риск.



==================================================

СТИЛЬ

==================================================



Пиши для закупочного подразделения металлургической компании.



Текст должен быть:

- коротким;

- конкретным;

- причинно-следственным;

- профессиональным;

- без журналистских оборотов;

- без эмоциональных оценок;

- без канцеляризмов;

- понятным без дополнительной расшифровки.



Главное правило: если индикатор означает рост, снижение или отсутствие

направленного сигнала для цены лома — назови это прямо.



НЕ используй расплывчатые формулировки без прямого вывода, например:

- "ценовое пространство";

- "ценовой запас";

- "относительная привлекательность";

- "поддерживающий фактор";

- "ограничивающий фактор";

- "экономический смысл отложения закупки";

- "отложение закупки";

- "осуществление закупки";

- "фиксация больших объёмов";

- "наблюдается ситуация";

- "имеет место";

- "в рамках текущей конъюнктуры".



Используй прямые формулировки:

- "спред указывает на рост цены лома";

- "спред указывает на снижение цены лома";

- "спред не даёт выраженного сигнала";

- "спреды дают противоречивые сигналы";

- "закупку целесообразно отложить";

- "закупать поэтапно";

- "дождаться стабилизации котировок".



==================================================

ТРЕБОВАНИЯ К РАЗДЕЛАМ

==================================================



current_assessment:

2–3 коротких предложения.

Фактический тренд + положение относительно fair value + общий сигнал спредов.

Новости сюда не добавляй.



next_month:

2–3 коротких предложения.

Назови математический прогноз и изменение к текущей цене.

Скажи, согласуются ли с ним внутренние спреды.

Отдельно скажи, подтверждает ли его свежий фундаментальный фон,

либо что внешний фон не удалось проверить.

Не создавай собственный числовой прогноз.



market_factors:

Если свежие факторы найдены — максимум два и только из предоставленного

внешнего контекста. Для каждого укажи механизм влияния на цену лома.

Если поиск выполнен, но факторов нет — скажи об этом одной фразой.

Если поиск недоступен — напиши:

"Свежий фундаментальный фон не удалось проверить."



structural_outlook:

2–3 коротких предложения.

Только структурный горизонт 6–12 месяцев.

Без точного прогноза цены и без придуманных фактов.



procurement_conclusion:

Не более 2–3 коротких предложений.

Сохрани направление рекомендации системы.

Не повторяй дословно purchase_title или recommendation.



sources:

В этом поле верни пустой список [].

Источники будут добавлены программно из результатов отдельного web search.

"""



    response_schema = {

        "type": "object",

        "properties": {

            "current_assessment": {"type": "string"},

            "next_month": {"type": "string"},

            "market_factors": {"type": "string"},

            "structural_outlook": {"type": "string"},

            "procurement_conclusion": {"type": "string"},

            "sources": {

                "type": "array",

                "items": {"type": "string"},

            },

        },

        "required": [

            "current_assessment",

            "next_month",

            "market_factors",

            "structural_outlook",

            "procurement_conclusion",

            "sources",

        ],

        "additionalProperties": False,

    }



    try:

        print("SCRAP AI: MAIN COMMENTARY START", flush=True)



        # ВАЖНО: здесь НЕТ tools=[web_search].

        response = client.with_options(

            timeout=60.0,

            max_retries=0,

        ).responses.create(

            model="gpt-5-mini",

            input=prompt,

            text={

                "format": {

                    "type": "json_schema",

                    "name": "scrap_3a_ufo_commentary",

                    "strict": True,

                    "schema": response_schema,

                }

            },

        )



        print("SCRAP AI: MAIN COMMENTARY FINISH", flush=True)



        result = _parse_json_response(response)



        # Источники берём только из реально выполненного отдельного поиска.

        result["sources"] = _sources_from_context(market_context)



        return result



    except RateLimitError:

        print("SCRAP AI: RateLimitError", flush=True)

        return get_ai_fallback(

            "AI-комментарий временно недоступен: превышен лимит OpenAI API."

        )



    except APITimeoutError:

        print("SCRAP AI: APITimeoutError after 60 seconds", flush=True)

        return get_ai_fallback(

            "AI-комментарий временно недоступен: OpenAI API не ответил за 60 секунд."

        )



    except APIConnectionError:

        print("SCRAP AI: APIConnectionError", flush=True)

        return get_ai_fallback(

            "AI-комментарий временно недоступен: ошибка соединения с OpenAI API."

        )



    except APIError as exc:

        print(f"SCRAP AI: APIError: {exc}", flush=True)

        return get_ai_fallback(

            "AI-комментарий временно недоступен: ошибка OpenAI API."

        )



    except Exception as exc:

        print(

            f"SCRAP AI: OTHER ERROR: {type(exc).__name__}: {exc}",

            flush=True,

        )

        return get_ai_fallback(

            "AI-комментарий временно недоступен из-за технической ошибки."

        )





# ======================================================

# PUBLIC FUNCTION — SIGNATURE PRESERVED FOR app.py

# ======================================================



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

    """

    Сохраняет прежний интерфейс для app.py.



    1. Берёт короткий web search (кэш 6 часов, timeout 25 сек).

    2. Передаёт найденный контекст в основной AI без web search.

    """



    market_context = search_scrap_market_factors()



    market_context_json = json.dumps(

        market_context,

        ensure_ascii=False,

        sort_keys=True,

    )



    return _generate_scrap_ai_commentary_cached(

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

        market_context_json=market_context_json,

    )
