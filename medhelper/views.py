# medhelper/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from triage.models import Consultation
from derm.models import DermCase
import json


@login_required
def history(request):
    triage_qs = Consultation.objects.filter(user=request.user).order_by('-created_at')[:50]
    derm_qs  = DermCase.objects.filter(user=request.user).order_by('-created_at')[:50]

    triage_items = []
    for c in triage_qs:
        urgency = None
        try:
            data = json.loads(c.llm_answer)
            if isinstance(data, dict):
                urgency = data.get("urgency_level")
        except Exception:
            pass
        triage_items.append({
            "obj": c,
            "urgency_level": urgency,
        })

    derm_items = [{"obj": d} for d in derm_qs]

    return render(request, 'history.html', {
        'triage': triage_items,
        'derm': derm_items,
    })
