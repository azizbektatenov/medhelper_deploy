import os
import base64
import requests
from django.conf import settings

# ==================== Анализ кожи через OpenRouter Vision ====================

def encode_image_to_base64(image_path: str) -> str:
    """Преобразует изображение в base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def analyze_skin_image(image_path: str):
    """
    Отправляет фото на OpenRouter и возвращает результат анализа.
    Возвращает: (label, confidence, risk_level, risk_label, top_list)
    """
    try:
        base64_image = encode_image_to_base64(image_path)

        # Выбираем мощную vision-модель
        model = settings.OPENROUTER_MODEL or "google/gemini-2.0-flash"   # можно поменять

        system_prompt = """
        Ты — опытный дерматолог. Проанализируй изображение кожного образования.
        Определи наиболее вероятный диагноз из следующих классов:
        - mel (Меланома)
        - nv (Меланоцитарный невус / родинка)
        - bkl (Кератозоподобное образование)
        - bcc (Базальноклеточный рак)
        - akiec (Актинический кератоз)
        - vasc (Сосудистое поражение)
        - df (Дерматофиброма)

        Верни ответ **только в формате JSON**:
        {
          "label": "nv",
          "confidence": 0.87,
          "risk_level": "green",
          "explanation": "Краткое объяснение"
        }
        """

        user_prompt = "Проанализируй это изображение кожного образования и дай наиболее вероятный диагноз."

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 300,
            "temperature": 0.3,
        }

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://medhelper-deploy.onrender.com",
            "X-Title": "MedHelper",
        }

        print(">>> Отправка изображения на OpenRouter Vision...")

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=45
        )

        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]

        # Пытаемся распарсить JSON из ответа
        import json
        try:
            result = json.loads(content)
        except:
            # Если модель вернула не чистый JSON — берём текст
            result = {"label": "unknown", "confidence": 0.6, "risk_level": "yellow", "explanation": content}

        label = result.get("label", "unknown")
        confidence = float(result.get("confidence", 0.6))
        risk_level = result.get("risk_level", "yellow")

        risk_labels = {
            "red": "🟥 Высокий риск — возможно злокачественное образование",
            "orange": "🟧 Повышенный риск — требуется очный осмотр",
            "yellow": "🟨 Умеренный риск",
            "green": "🟩 Низкий риск"
        }

        top_list = [{
            "label": label,
            "name": _get_human_name(label),
            "confidence": confidence,
            "percent": round(confidence * 100, 2),
            "risk_level": risk_level,
            "risk_label": risk_labels.get(risk_level, risk_labels["yellow"])
        }]

        return label, confidence * 100, risk_level, risk_labels.get(risk_level, ""), top_list

    except Exception as e:
        print(f">>> Ошибка при анализе через OpenRouter: {e}")
        # Заглушка при ошибке
        return "unknown", 50.0, "yellow", "Не удалось проанализировать изображение", []


def _get_human_name(label: str) -> str:
    names = {
        "mel": "Меланома",
        "nv": "Меланоцитарный невус (родинка)",
        "bkl": "Кератозоподобное образование",
        "bcc": "Базальноклеточный рак кожи",
        "akiec": "Актинический кератоз",
        "vasc": "Сосудистое поражение",
        "df": "Дерматофиброма",
    }
    return names.get(label.lower(), label)


# Для совместимости со старым кодом
def predict_image_topk(path: str, topk: int = 3):
    label, conf, risk_level, risk_label, top_list = analyze_skin_image(path)
    best = top_list[0] if top_list else None
    return best, top_list


def predict_image(path: str):
    label, conf, _, _, _ = analyze_skin_image(path)
    return label, conf


def get_treatment_plan(label: str):
    plans = {
        "mel": {
            "title": "Меланома",
            "description": "Образование требует срочной очной консультации дерматолога или онколога.",
            "recommendations": [
                "Не откладывать визит к врачу",
                "Не травмировать и не пытаться удалять образование самостоятельно",
                "Провести дерматоскопию и дальнейшее обследование по назначению врача"
            ]
        },
        "bcc": {
            "title": "Базальноклеточный рак кожи",
            "description": "Возможное злокачественное образование кожи, требуется очная диагностика.",
            "recommendations": [
                "Обратиться к дерматологу или онкологу",
                "Провести дерматоскопию",
                "Не применять самостоятельное лечение"
            ]
        },
        "akiec": {
            "title": "Актинический кератоз",
            "description": "Предраковое состояние кожи, связанное с воздействием ультрафиолета.",
            "recommendations": [
                "Обратиться к дерматологу",
                "Использовать солнцезащиту",
                "Контролировать изменения образования"
            ]
        },
        "nv": {
            "title": "Меланоцитарный невус",
            "description": "Чаще всего доброкачественная родинка, но важно наблюдать за изменениями.",
            "recommendations": [
                "Следить за размером, цветом и формой",
                "При росте, кровоточивости или изменении цвета обратиться к врачу",
                "Не травмировать образование"
            ]
        },
        "bkl": {
            "title": "Кератозоподобное образование",
            "description": "Чаще всего доброкачественное образование кожи.",
            "recommendations": [
                "Планово обратиться к дерматологу",
                "Не удалять самостоятельно",
                "Наблюдать за изменениями"
            ]
        },
        "vasc": {
            "title": "Сосудистое поражение",
            "description": "Может соответствовать сосудистому образованию кожи.",
            "recommendations": [
                "Проконсультироваться с дерматологом",
                "Избегать травмирования",
                "При кровоточивости обратиться к врачу"
            ]
        },
        "df": {
            "title": "Дерматофиброма",
            "description": "Обычно доброкачественное плотное образование кожи.",
            "recommendations": [
                "Плановый осмотр дерматолога",
                "Наблюдение при отсутствии жалоб",
                "Обращение к врачу при росте или боли"
            ]
        },
    }

    return plans.get(label, {
        "title": "Неопределённый результат",
        "description": "Не удалось точно определить тип кожного образования.",
        "recommendations": [
            "Повторить анализ с более качественным фото",
            "Обратиться к дерматологу для очного осмотра",
            "Не использовать результат как окончательный диагноз"
        ]
    })
