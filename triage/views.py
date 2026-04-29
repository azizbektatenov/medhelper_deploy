# triage/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import Consultation
from django.views.decorators.http import require_POST
import os, requests, json

# модель по умолчанию можно переопределить в .env: OPENROUTER_MODEL=...
MODEL_NAME = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def call_openrouter_llm(sex: str, age: int, symptoms: str) -> str:
    """
    Реальный вызов OpenRouter. Возвращает JSON-строку с результатом
    или человекочитаемую ошибку.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",   # поменять на прод-URL при деплое
        "X-Title": "MedHelper",
    }

    # Системное сообщение: чётко описываем схему JSON
    system_msg = (
        "Ты медицинский ассистент по неотложным состояниям. "
        "Оцени жалобы, уровень риска и срочность, но НЕ ставь окончательный диагноз "
        "и НЕ назначай конкретные лекарства и дозировки. "
        "Не указывай названия препаратов, кроме общих классов (например, 'обезболивающее', 'жаропонижающее'). "
        "Ответь СТРОГО в формате JSON БЕЗ текста до или после JSON. "
        "Структура JSON:\n"
        "{\n"
        '  \"urgency_level\": \"emergency | urgent | routine\",  // срочность обращения\n'
        '  \"urgency_explanation\": \"Короткое объяснение выбранного уровня срочности.\",\n'
        '  \"risk_level\": \"red | orange | yellow | green\",    // уровень риска\n'
        '  \"risk_label\": \"Краткое описание уровня риска для пациента.\",\n'
        '  \"reasoning\": \"Краткое клиническое обоснование: какие симптомы настораживают, какие нет.\",\n'
        '  \"possible_diagnoses\": [\n'
        '    {\"name\": \"Ориентировочный диагноз 1\", \"probability\": 0.6},\n'
        '    {\"name\": \"Ориентировочный диагноз 2\", \"probability\": 0.3}\n'
        "  ],\n"
        '  \"red_flags\": [\"Перечень тревожных признаков, если есть\"],\n'
        '  \"recommendations\": \"Что делать пациенту сейчас, в каких случаях срочно вызывать скорую или идти к врачу.\",\n'
        '  \"tests_to_do\": [\"Какие исследования/анализы целесообразно обсудить с врачом\"],\n'
        '  \"self_care_allowed\": [\"Что допустимо делать дома до осмотра\"],\n'
        '  \"self_care_forbidden\": [\"Чего делать НЕ стоит до осмотра\"],\n'
        '  \"specialist\": \"Какой врач наиболее уместен (терапевт, педиатр, невролог и т.п.).\",\n'
        '  \"note_for_doctor\": \"Краткая подсказка, на что врачу обратить внимание.\",\n'
        '  \"disclaimer\": \"Явный дисклеймер, что это не диагноз и не замена очному приёму.\"\n'
        "}\n"
        "Если данных мало, честно укажи низкую уверенность и подчеркни необходимость очного осмотра."
    )

    user_msg = (
        f"Пациент:\n"
        f"- Пол: {sex}\n"
        f"- Возраст: {age}\n"
        f"- Жалобы и симптомы: {symptoms}\n"
        "Сформируй отчёт строго по указанной JSON-схеме на русском языке."
    )

    data = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
    }

    try:
        r = requests.post(url, headers=headers, json=data, timeout=30)
        if r.status_code != 200:
            return f"Не удалось получить ответ ИИ ({r.status_code}): {r.text[:300]}"

        content = r.json()["choices"][0]["message"]["content"].strip()

        # Пытаемся распарсить JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return f"Модель вернула невалидный JSON. Сырой ответ:\n{content}"

        # Возвращаем красивую JSON-строку, которую будем хранить в llm_answer
        return json.dumps(parsed, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"Ошибка запроса ИИ: {e}"


@login_required
def triage_form(request):
    if request.method == 'POST':
        sex = request.POST.get('sex', '').strip()
        age = int(request.POST.get('age') or 0)
        symptoms = (request.POST.get('symptoms') or '').strip()

        c = Consultation.objects.create(
            user=request.user, sex=sex, age=age, symptoms=symptoms
        )

        # если ключа нет — вернём аккуратную заглушку
        if not OPENROUTER_API_KEY:
            answer = ("Ключ OpenRouter не найден. Добавьте OPENROUTER_API_KEY в .env. "
                      "Временно: ориентируйтесь на состояние и обратитесь к врачу при ухудшении.")
        else:
            answer = call_openrouter_llm(sex, age, symptoms)

        c.llm_answer = answer
        c.save()
        return redirect('triage:triage_detail', pk=c.id)

    return render(request, 'triage/form.html')

@login_required
def triage_history(request):
    qs = Consultation.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'triage/history.html', {'items': qs})

@login_required
def triage_detail(request, pk: int):
    obj = get_object_or_404(Consultation, pk=pk, user=request.user)

    triage = None

    try:
        data = json.loads(obj.llm_answer)
        if isinstance(data, dict) and data.get("urgency_level"):
            diagnoses = []
            for d in data.get("possible_diagnoses") or []:
                name = d.get("name")
                prob = d.get("probability")
                percent = None
                try:
                    if prob is not None:
                        percent = round(float(prob) * 100)
                except Exception:
                    percent = None
                diagnoses.append(
                    {
                        "name": name,
                        "probability": prob,
                        "percent": percent,
                    }
                )

            triage = {
                "urgency_level": data.get("urgency_level"),
                "urgency_explanation": data.get("urgency_explanation"),
                "risk_level": data.get("risk_level"),
                "risk_label": data.get("risk_label"),
                "reasoning": data.get("reasoning"),
                "diagnoses": diagnoses,
                "red_flags": data.get("red_flags") or [],
                "recommendations": data.get("recommendations"),
                "tests_to_do": data.get("tests_to_do") or [],
                "self_care_allowed": data.get("self_care_allowed") or [],
                "self_care_forbidden": data.get("self_care_forbidden") or [],
                "specialist": data.get("specialist"),
                "note_for_doctor": data.get("note_for_doctor"),
                "disclaimer": data.get("disclaimer"),
            }
    except Exception:
        triage = None

    return render(request, 'triage/detail.html', {
        'obj': obj,
        'triage': triage,
    })


@require_POST
@login_required
def triage_delete(request, pk: int):
    """
    Удаление одной записи симптом-чекера текущего пользователя.
    """
    obj = get_object_or_404(Consultation, pk=pk, user=request.user)
    obj.delete()
    return redirect('history')


