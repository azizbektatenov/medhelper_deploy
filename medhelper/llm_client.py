# medhelper/llm_client.py
import requests
from django.conf import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"



def ask_treatment_for_diagnosis(disease_name: str, risk_level: str | None = None) -> dict:
    """
    Возвращает структурированный план действий при данном диагнозе:
    { "summary": "...",
      "syndrome": "...",
      "plan": "...",
      "red_flags": "...",
      "what_not_to_do": "..."
    }
    """

    risk_text = ""
    if risk_level == "red":
        risk_text = "Это потенциально опасное состояние высокого риска."
    elif risk_level == "orange":
        risk_text = "Это состояние среднего онкологического риска."
    elif risk_level == "green":
        risk_text = "Это, как правило, доброкачественное состояние."

    system_prompt = (
        "Ты — клинический врач-дерматолог. Отвечай кратко, структурировано и понятным языком. "
        "Не ставь окончательный диагноз, а говори 'предположительно' и всегда добавляй, "
        "что очная консультация врача обязательна. Не упоминай про ИИ."
    )

    user_prompt = f"""
    Пациент прислал фотографию кожного образования. Алгоритм дерматоскопии предположительно
    классифицировал его как: «{disease_name}». {risk_text}

    Сформируй структурированный ответ в формате:

    1) Предполагаемый синдром / клиническая ситуация (1–2 предложения).
    2) Предполагаемое заболевание (1–2 варианта, очень кратко).
    3) План действий:
       - какие обследования нужны в первую очередь;
       - к какому врачу обратиться и в какие сроки (срочно / в ближайшие дни / планово);
       - возможные варианты лечения (общими словами, без дозировок).
    4) Красные флаги — при каких симптомах нужно срочно вызвать скорую или обратиться в стационар.
    5) Чего точно НЕ делать пациенту (например, не прижигать дома, не откладывать визит и т.п.).

    Пиши на русском, максимум 15–20 строк. Не указывай дозы и названия конкретных препаратов.
    """

    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": settings.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    resp = requests.post(OPENROUTER_URL, json=data, headers=headers, timeout=120)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    return {
        "raw_text": content,
        # можно потом распарсить по заголовкам, но на первом этапе достаточно сырого
    }
