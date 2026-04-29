import base64
import json
import re
import requests
from django.conf import settings


# ==================== Названия классов ====================

_LABEL_NAME = {
    "mel": "Меланома",
    "nv": "Меланоцитарный невус (родинка)",
    "bkl": "Кератозоподобное образование",
    "bcc": "Базальноклеточный рак кожи",
    "akiec": "Актинический кератоз",
    "vasc": "Сосудистое поражение",
    "df": "Дерматофиброма",
    "unknown": "Неопределённый результат",
}


RISK_LABELS = {
    "red": "🟥 Высокий риск — возможно злокачественное образование",
    "orange": "🟧 Повышенный риск — требуется очный осмотр",
    "yellow": "🟨 Умеренный риск — желательно наблюдение и консультация врача",
    "green": "🟩 Низкий риск — вероятно доброкачественное образование",
}


# ==================== Вспомогательные функции ====================

def encode_image_to_base64(image_path: str) -> str:
    """Преобразует изображение в base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def _get_human_name(label: str) -> str:
    """Возвращает человекочитаемое название диагноза."""
    if not label:
        return "Неопределённый результат"
    return _LABEL_NAME.get(label.lower(), label)


def _extract_json_from_text(text: str) -> dict:
    """
    Безопасно извлекает JSON из ответа модели.
    Иногда модель может вернуть JSON внутри ```json ... ```.
    """
    if not text:
        return {}

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {}


def _normalize_label(label: str) -> str:
    """Проверяет, входит ли label в допустимые классы."""
    if not label:
        return "unknown"

    label = str(label).lower().strip()

    allowed = {"mel", "nv", "bkl", "bcc", "akiec", "vasc", "df"}
    return label if label in allowed else "unknown"


def _normalize_risk_level(risk_level: str) -> str:
    """Нормализует уровень риска."""
    if not risk_level:
        return "yellow"

    risk_level = str(risk_level).lower().strip()

    allowed = {"red", "orange", "yellow", "green"}
    return risk_level if risk_level in allowed else "yellow"


def _normalize_confidence(confidence) -> float:
    """
    Приводит confidence к формату 0.0–1.0.
    Если модель вернула 87 вместо 0.87, исправляем.
    """
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        return 0.6

    if confidence > 1:
        confidence = confidence / 100

    if confidence < 0:
        confidence = 0.0

    if confidence > 1:
        confidence = 1.0

    return confidence


# ==================== Анализ кожи через OpenRouter Vision ====================

def analyze_skin_image(image_path: str):
    """
    Отправляет фото на OpenRouter Vision и возвращает результат анализа.

    Возвращает:
    label, confidence_percent, risk_level, risk_label, top_list
    """

    try:
        base64_image = encode_image_to_base64(image_path)

        model = getattr(settings, "OPENROUTER_MODEL", None) or "google/gemini-2.0-flash"

        system_prompt = """
Ты — медицинский ассистент для предварительного анализа кожных образований по изображению.

Твоя задача:
- внимательно оценить изображение кожного образования
- выбрать наиболее вероятный класс только из списка
- вернуть результат строго в JSON
- не ставить окончательный диагноз
- обязательно рекомендовать очную консультацию врача при риске

Доступные классы:
- mel — меланома
- nv — меланоцитарный невус / родинка
- bkl — кератозоподобное образование
- bcc — базальноклеточный рак кожи
- akiec — актинический кератоз
- vasc — сосудистое поражение
- df — дерматофиброма

Уровни риска:
- red — высокий риск
- orange — повышенный риск
- yellow — умеренный риск
- green — низкий риск

Верни ответ только в таком JSON-формате:
{
  "label": "nv",
  "confidence": 0.87,
  "risk_level": "green",
  "explanation": "Краткое объяснение результата"
}
"""

        user_prompt = """
Проанализируй это изображение кожного образования.
Выбери наиболее вероятный класс из списка.
Ответ верни только в JSON.
"""

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            },
                        },
                    ],
                },
            ],
            "max_tokens": 500,
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://medhelper-deploy.onrender.com",
            "X-Title": "MedHelper",
        }

        print(">>> Отправка изображения на OpenRouter Vision...", flush=True)

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60,
        )

        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        result = _extract_json_from_text(content)

        label = _normalize_label(result.get("label"))
        confidence = _normalize_confidence(result.get("confidence", 0.6))
        risk_level = _normalize_risk_level(result.get("risk_level", "yellow"))
        explanation = result.get("explanation", "")

        risk_label = RISK_LABELS.get(risk_level, RISK_LABELS["yellow"])

        top_list = [
            {
                "label": label,
                "name": _get_human_name(label),
                "confidence": confidence,
                "percent": round(confidence * 100, 2),
                "risk_level": risk_level,
                "risk_label": risk_label,
                "explanation": explanation,
            }
        ]

        return label, round(confidence * 100, 2), risk_level, risk_label, top_list

    except Exception as e:
        print(f">>> Ошибка при анализе через OpenRouter: {e}", flush=True)

        label = "unknown"
        confidence = 0.5
        risk_level = "yellow"
        risk_label = "Не удалось проанализировать изображение"

        top_list = [
            {
                "label": label,
                "name": _get_human_name(label),
                "confidence": confidence,
                "percent": 50.0,
                "risk_level": risk_level,
                "risk_label": risk_label,
                "explanation": "Произошла ошибка при анализе изображения через OpenRouter.",
            }
        ]

        return label, 50.0, risk_level, risk_label, top_list


# ==================== Совместимость со старым кодом ====================

def predict_image_topk(path: str, topk: int = 3):
    """
    Совместимость со старым views.py.

    Раньше функция возвращала top-3 от ResNet.
    Сейчас OpenRouter Vision возвращает один основной результат.
    """
    label, conf_percent, risk_level, risk_label, top_list = analyze_skin_image(path)

    best = top_list[0] if top_list else {
        "label": label,
        "name": _get_human_name(label),
        "confidence": conf_percent / 100,
        "percent": conf_percent,
        "risk_level": risk_level,
        "risk_label": risk_label,
    }

    return best, top_list


def predict_image(path: str):
    """
    Совместимость со старой логикой.
    Возвращает label и confidence в процентах.
    """
    label, conf_percent, _, _, _ = analyze_skin_image(path)
    return label, conf_percent


# ==================== План рекомендаций ====================

def get_treatment_plan(label: str, risk_level: str = None):
    """
    Возвращает текстовый план рекомендаций.

    Сделано так, чтобы работало и со старым views.py:
    get_treatment_plan(label)
    get_treatment_plan(label, risk_level)
    """

    label = _normalize_label(label)
    risk_level = _normalize_risk_level(risk_level)

    disease_name = _get_human_name(label)

    plans = {
        "mel": {
            "syndrome": "Подозрительное пигментное образование кожи с высоким онкологическим риском.",
            "diseases": "Меланома или другое злокачественное пигментное образование кожи.",
            "exam": "Дерматоскопия, очный осмотр дерматолога или онкодерматолога, при необходимости биопсия по назначению врача.",
            "doctor": "Обратиться к дерматологу или онкологу как можно быстрее.",
            "treatment": "Тактика лечения определяется только врачом после очного осмотра и подтверждающей диагностики.",
            "red_flags": "Быстрый рост, асимметрия, неровные края, изменение цвета, кровоточивость, зуд, боль.",
            "donts": "Нельзя удалять, прижигать, травмировать или лечить образование самостоятельно.",
        },
        "bcc": {
            "syndrome": "Подозрительное образование кожи с возможным злокачественным характером.",
            "diseases": "Базальноклеточный рак кожи.",
            "exam": "Дерматоскопия, очная консультация дерматолога или онколога, при необходимости морфологическое исследование.",
            "doctor": "Обратиться к дерматологу или онкологу в ближайшее время.",
            "treatment": "Метод лечения подбирается врачом индивидуально после подтверждения диагноза.",
            "red_flags": "Рост образования, язвочка, кровоточивость, корочка, незаживающий участок кожи.",
            "donts": "Нельзя заниматься самолечением, использовать агрессивные мази или удалять образование самостоятельно.",
        },
        "akiec": {
            "syndrome": "Изменение кожи, связанное с хроническим воздействием ультрафиолета.",
            "diseases": "Актинический кератоз, предраковое изменение кожи.",
            "exam": "Осмотр дерматолога, дерматоскопия, оценка других участков кожи.",
            "doctor": "Планово обратиться к дерматологу, особенно при росте или воспалении образования.",
            "treatment": "Лечение определяется врачом и может включать местную терапию или удаление изменённого участка.",
            "red_flags": "Уплотнение, быстрый рост, болезненность, кровоточивость, появление язвочки.",
            "donts": "Нельзя сдирать корочки, прижигать образование или долго находиться на солнце без защиты.",
        },
        "nv": {
            "syndrome": "Пигментное образование кожи, вероятно доброкачественного характера.",
            "diseases": "Меланоцитарный невус или обычная родинка.",
            "exam": "Плановая дерматоскопия, наблюдение за размером, формой и цветом образования.",
            "doctor": "Обратиться к дерматологу планово, срочно — при изменении родинки.",
            "treatment": "Обычно требуется наблюдение, удаление проводится только по медицинским или эстетическим показаниям после консультации врача.",
            "red_flags": "Асимметрия, изменение цвета, быстрый рост, зуд, боль, кровоточивость.",
            "donts": "Нельзя травмировать родинку, срезать, прижигать или удалять её самостоятельно.",
        },
        "bkl": {
            "syndrome": "Кератозоподобное образование кожи, чаще доброкачественного характера.",
            "diseases": "Себорейный кератоз или другое доброкачественное кератозное образование.",
            "exam": "Осмотр дерматолога, дерматоскопия для исключения злокачественного процесса.",
            "doctor": "Планово обратиться к дерматологу.",
            "treatment": "При подтверждении доброкачественного характера может быть рекомендовано наблюдение или удаление по показаниям.",
            "red_flags": "Резкий рост, воспаление, кровоточивость, изменение цвета, боль.",
            "donts": "Нельзя сдирать, царапать, прижигать или удалять образование самостоятельно.",
        },
        "vasc": {
            "syndrome": "Сосудистое образование кожи.",
            "diseases": "Ангиома, гемангиома или другое сосудистое поражение кожи.",
            "exam": "Осмотр дерматолога, дерматоскопия, при необходимости дополнительная сосудистая оценка.",
            "doctor": "Планово обратиться к дерматологу, срочно — при кровоточивости или быстром росте.",
            "treatment": "Часто требуется наблюдение, метод удаления или лечения выбирает врач при наличии показаний.",
            "red_flags": "Кровоточивость, быстрый рост, травматизация, боль, изменение внешнего вида.",
            "donts": "Нельзя прокалывать, срезать или травмировать сосудистое образование.",
        },
        "df": {
            "syndrome": "Плотное доброкачественное образование кожи.",
            "diseases": "Дерматофиброма.",
            "exam": "Плановый осмотр дерматолога, дерматоскопия при необходимости.",
            "doctor": "Обратиться к дерматологу планово.",
            "treatment": "Обычно достаточно наблюдения, удаление возможно при боли, росте или косметическом дискомфорте.",
            "red_flags": "Быстрый рост, боль, кровоточивость, изменение цвета или формы.",
            "donts": "Нельзя самостоятельно выдавливать, разрезать или прижигать образование.",
        },
        "unknown": {
            "syndrome": "Неопределённое кожное образование.",
            "diseases": "По изображению не удалось достоверно определить тип образования.",
            "exam": "Повторить фото при хорошем освещении, пройти очный осмотр дерматолога и дерматоскопию.",
            "doctor": "Обратиться к дерматологу для уточнения диагноза.",
            "treatment": "Тактика зависит от результата очного осмотра.",
            "red_flags": "Рост, боль, зуд, кровоточивость, изменение цвета, появление язвочки.",
            "donts": "Нельзя лечить или удалять образование самостоятельно.",
        },
    }

    plan = plans.get(label, plans["unknown"])

    text = f"""1) Синдром: {plan["syndrome"]}

2) Возможные заболевания: {disease_name}. {plan["diseases"]}

3) План действий:
- обследования: {plan["exam"]}
- к кому обратиться и когда: {plan["doctor"]}
- общие подходы к лечению: {plan["treatment"]}

4) Красные флаги: {plan["red_flags"]}

5) Чего нельзя делать: {plan["donts"]}

Важно: результат анализа изображения является предварительным и не заменяет очный осмотр врача."""

    return text
