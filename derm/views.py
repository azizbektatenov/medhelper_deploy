from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
import re

from .models import DermCase
from .inference import (
    predict_image_topk,
    get_treatment_plan,
    _LABEL_NAME,          # оставляем, так как используем в шаблоне
)


def _parse_treatment_plan(text: str):
    """
    Разбирает текст плана лечения от LLM по номерам и заголовкам.
    """
    res = {
        "syndrome": "",
        "diseases": "",
        "actions": {"exam": "", "doctor": "", "treatment": ""},
        "red_flags": "",
        "donts": "",
    }
    section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Основные разделы
        m = re.match(r"^1\)\s*Синдром:\s*(.*)", line, re.I)
        if m:
            section = "syndrome"
            res["syndrome"] = m.group(1).strip()
            continue

        m = re.match(r"^2\)\s*Возможные заболевания:\s*(.*)", line, re.I)
        if m:
            section = "diseases"
            res["diseases"] = m.group(1).strip()
            continue

        m = re.match(r"^3\)\s*План действий:", line, re.I)
        if m:
            section = "actions"
            continue

        m = re.match(r"^4\)\s*Красные флаги:\s*(.*)", line, re.I)
        if m:
            section = "red_flags"
            res["red_flags"] = m.group(1).strip()
            continue

        m = re.match(r"^5\)\s*Чего нельзя делать:\s*(.*)", line, re.I)
        if m:
            section = "donts"
            res["donts"] = m.group(1).strip()
            continue

        # Подразделы внутри "План действий"
        if section == "actions":
            m = re.match(r"^-\s*обследования:\s*(.*)", line, re.I)
            if m:
                res["actions"]["exam"] = m.group(1).strip()
                continue

            m = re.match(r"^-\s*к кому обратиться и когда:\s*(.*)", line, re.I)
            if m:
                res["actions"]["doctor"] = m.group(1).strip()
                continue

            m = re.match(r"^-\s*общие подходы к лечению.*:\s*(.*)", line, re.I)
            if m:
                res["actions"]["treatment"] = m.group(1).strip()
                continue

        # Продолжение текста в текущем разделе
        if section in ("syndrome", "diseases", "red_flags", "donts"):
            if res[section]:
                res[section] += " " + line
            else:
                res[section] = line

    return res


@login_required
def derm_form(request):
    """
    Обработка загрузки фото кожи и анализ.
    """
    if request.method == "POST" and request.FILES.get("image"):
        img = request.FILES["image"]

        # Создаём запись в базе
        case = DermCase.objects.create(user=request.user, image=img)

        try:
            # Получаем предсказание (один раз вызываем topk)
            best, top_preds = predict_image_topk(case.image.path, topk=3)

            if best:
                case.result_label = best["label"]
                case.confidence = best["percent"]
                risk_level = best["risk_level"]
                main_name = best["name"]  # используем человекочитаемое название
            else:
                case.result_label = ""
                case.confidence = 0.0
                risk_level = None
                main_name = "Неизвестно"

            # Генерируем план лечения через LLM
            case.treatment_plan = get_treatment_plan(main_name, risk_level)

            case.save()

            return redirect("derm:derm_detail", pk=case.id)

        except Exception as e:
            # Логируем ошибку (будет видно в логах Render)
            print(f">>> Ошибка при анализе изображения: {e}", flush=True)
            # Можно добавить сообщение пользователю через messages framework,
            # но для начала просто возвращаем на форму
            return redirect("derm:derm_form")

    return render(request, "derm/form.html")


@login_required
def derm_history(request):
    items = DermCase.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "derm/history.html", {"items": items})


@login_required
def derm_detail(request, pk):
    case = get_object_or_404(DermCase, pk=pk, user=request.user)

    try:
        best, top_preds = predict_image_topk(case.image.path, topk=3)
    except Exception as e:
        print(f">>> Ошибка при повторном предсказании в detail: {e}")
        best = None
        top_preds = []

    main_name = _LABEL_NAME.get(case.result_label, case.result_label)
    main_conf_percent = round(float(case.confidence), 1) if case.confidence is not None else None

    overall_risk = None
    if best:
        overall_risk = {
            "risk_level": best["risk_level"],
            "risk_label": best["risk_label"],
        }

    treatment_plan = case.treatment_plan
    plan = _parse_treatment_plan(treatment_plan) if treatment_plan else None

    return render(
        request,
        "derm/detail.html",
        {
            "obj": case,
            "top_preds": top_preds,
            "overall_risk": overall_risk,
            "main_conf_percent": main_conf_percent,
            "main_name": main_name,
            "treatment_plan": treatment_plan,
            "plan": plan,
        },
    )


@require_POST
@login_required
def derm_delete(request, pk):
    case = get_object_or_404(DermCase, pk=pk, user=request.user)
    case.delete()
    return redirect("derm:derm_history")
