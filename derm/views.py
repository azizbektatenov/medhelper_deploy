from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
import re

from .models import DermCase
from .inference import (
    predict_image_topk,
    get_treatment_plan,
    _LABEL_NAME,
)


def _parse_treatment_plan(text: str):
    res = {
        "syndrome": "",
        "diseases": "",
        "actions": {
            "exam": "",
            "doctor": "",
            "treatment": "",
        },
        "red_flags": "",
        "donts": "",
    }

    if not text:
        return res

    section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

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

        if section in ("syndrome", "diseases", "red_flags", "donts"):
            if res[section]:
                res[section] += " " + line
            else:
                res[section] = line

    return res


@login_required
def derm_form(request):
    """
    Загрузка фото кожи и первичный анализ через OpenRouter Vision.
    Анализ выполняется только один раз при POST-загрузке изображения.
    """

    if request.method == "POST" and request.FILES.get("image"):
        img = request.FILES["image"]

        case = DermCase.objects.create(
            user=request.user,
            image=img,
        )

        try:
            best, top_preds = predict_image_topk(case.image.path, topk=3)

            if best:
                case.result_label = best.get("label", "unknown")
                case.confidence = best.get("percent", 0.0)
                risk_level = best.get("risk_level", "yellow")
            else:
                case.result_label = "unknown"
                case.confidence = 0.0
                risk_level = "yellow"

            case.treatment_plan = get_treatment_plan(case.result_label, risk_level)
            case.save()

            return redirect("derm:derm_detail", pk=case.id)

        except Exception as e:
            print(f">>> Ошибка при анализе изображения: {e}", flush=True)

            case.result_label = "unknown"
            case.confidence = 0.0
            case.treatment_plan = get_treatment_plan("unknown", "yellow")
            case.save()

            return redirect("derm:derm_detail", pk=case.id)

    return render(request, "derm/form.html")


@login_required
def derm_history(request):
    items = DermCase.objects.filter(user=request.user).order_by("-created_at")

    return render(
        request,
        "derm/history.html",
        {
            "items": items,
        },
    )


@login_required
def derm_detail(request, pk):
    """
    Страница результата.
    Важно: здесь НЕ вызываем predict_image_topk повторно,
    чтобы не отправлять изображение в OpenRouter каждый раз.
    """

    case = get_object_or_404(DermCase, pk=pk, user=request.user)

    main_name = _LABEL_NAME.get(case.result_label, case.result_label or "Неопределённый результат")

    main_conf_percent = (
        round(float(case.confidence), 1)
        if case.confidence is not None
        else 0.0
    )

    treatment_plan = case.treatment_plan
    plan = _parse_treatment_plan(treatment_plan) if treatment_plan else None

    risk_level = "yellow"

    if treatment_plan:
        lowered = treatment_plan.lower()

        if "высокий риск" in lowered or "меланома" in lowered:
            risk_level = "red"
        elif "повышенный риск" in lowered or "базальноклеточный" in lowered or "актинический" in lowered:
            risk_level = "orange"
        elif "низкий риск" in lowered or "доброкачествен" in lowered:
            risk_level = "green"

    risk_labels = {
        "red": "🟥 Высокий риск — требуется срочная очная консультация",
        "orange": "🟧 Повышенный риск — требуется очный осмотр",
        "yellow": "🟨 Умеренный риск — желательно наблюдение и консультация врача",
        "green": "🟩 Низкий риск — вероятно доброкачественное образование",
    }

    overall_risk = {
        "risk_level": risk_level,
        "risk_label": risk_labels.get(risk_level, risk_labels["yellow"]),
    }

    top_preds = [
        {
            "label": case.result_label,
            "name": main_name,
            "percent": main_conf_percent,
            "risk_level": risk_level,
            "risk_label": overall_risk["risk_label"],
        }
    ]

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
