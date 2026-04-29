# derm/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
import re

from .models import DermCase
from .inference import (
    predict_image,
    predict_image_topk,
    _LABEL_NAME,
    get_treatment_plan,
)


def _parse_treatment_plan(text: str):
    """
    Разбирает текст вида:
    1) Синдром: ...
    2) Возможные заболевания: ...
    3) План действий:
       - обследования: ...
       - к кому обратиться и когда: ...
       - общие подходы к лечению (без названий препаратов): ...
    4) Красные флаги: ...
    5) Чего нельзя делать: ...
    """
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
    Форма загрузки изображения кожи.
    ВАЖНО: LLM вызывается только здесь, при POST.
    """
    if request.method == "POST" and request.FILES.get("image"):
        img = request.FILES["image"]
        case = DermCase.objects.create(user=request.user, image=img)

        # локальный прогноз
        label, conf = predict_image(case.image.path)
        case.result_label = label
        case.confidence = conf

        # топ-3, чтобы достать риск
        best, _ = predict_image_topk(case.image.path, topk=3)
        risk_level = best["risk_level"] if best else None

        main_name = _LABEL_NAME.get(label, label)

        # 🔥 один-единственный запрос в OpenRouter
        case.treatment_plan = get_treatment_plan(main_name, risk_level)

        case.save()

        return redirect("derm:derm_detail", pk=case.id)

    return render(request, "derm/form.html")


@login_required
def derm_history(request):
    items = DermCase.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "derm/history.html", {"items": items})


@login_required
def derm_detail(request, pk):
    case = get_object_or_404(DermCase, pk=pk, user=request.user)

    best, top_preds = predict_image_topk(case.image.path, topk=3)

    main_name = _LABEL_NAME.get(case.result_label, case.result_label)
    main_conf_percent = (
        round(float(case.confidence), 1) if case.confidence is not None else None
    )

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
