import os
import json
import gc
import requests

import torch
import torch.nn.functional as F
from PIL import Image
from django.conf import settings
from torch import nn
from torchvision import models, transforms

# Глобальные переменные
_MODEL = None
_IDX2LABEL = None
_DEVICE = "cpu"

# ====================== Настройки ======================
_CLASS_RISK = {
    "mel": "red", "akiec": "red", "bcc": "orange",
    "bkl": "yellow", "df": "yellow", "vasc": "yellow", "nv": "green",
}

_RISK_LABEL = {
    "red":    "🟥 Высокий риск — возможно злокачественное образование",
    "orange": "🟧 Повышенный риск — требуется очный осмотр",
    "yellow": "🟨 Умеренный риск",
    "green":  "🟩 Низкий риск",
}

_LABEL_NAME = {
    "mel":  "Меланома",
    "nv":   "Меланоцитарный невус (родинка)",
    "bkl":  "Кератозоподобное образование",
    "bcc":  "Базальноклеточный рак кожи",
    "akiec": "Актинический кератоз",
    "vasc": "Сосудистое поражение",
    "df":   "Дерматофиброма",
}


def _risk_from_label(label: str):
    if not label:
        return "yellow", _RISK_LABEL["yellow"]
    l = label.lower()
    for key, lvl in _CLASS_RISK.items():
        if key in l:
            return lvl, _RISK_LABEL[lvl]
    return "yellow", _RISK_LABEL["yellow"]


def _abs(path_or_none, default_rel):
    if path_or_none:
        return path_or_none if os.path.isabs(path_or_none) else os.path.join(settings.BASE_DIR, path_or_none)
    return os.path.join(settings.BASE_DIR, default_rel)


def _load_class_map(path):
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    idx2dx = mapping.get("label_to_dx", {})
    max_idx = max(int(k) for k in idx2dx.keys())
    arr = [None] * (max_idx + 1)
    for k, v in idx2dx.items():
        arr[int(k)] = v
    return arr


def _build_resnet50(num_classes: int):
    """Создаём ResNet50 с правильной структурой"""
    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, num_classes)
    return model


def _get_model():
    global _MODEL, _IDX2LABEL

    if _MODEL is not None:
        return _MODEL, _IDX2LABEL

    try:
        model_path = _abs(os.getenv("MODEL_PATH"), "models/skin_model.pth")
        class_map_path = _abs(os.getenv("CLASS_MAP_PATH"), "models/class_mapping.json")

        _IDX2LABEL = _load_class_map(class_map_path)
        num_classes = len([x for x in _IDX2LABEL if x is not None])

        print(">>> Загрузка модели дерматологии (ResNet50 + float16)...")

        # Загружаем веса
        state = torch.load(model_path, map_location=_DEVICE)

        if isinstance(state, dict) and not isinstance(state, nn.Module):
            model = _build_resnet50(num_classes)
            if any(k.startswith("module.") for k in state.keys()):
                state = {k.replace("module.", "", 1): v for k, v in state.items()}
            model.load_state_dict(state, strict=False)
        else:
            model = state

        # === Максимальная оптимизация памяти ===
        model = model.to(dtype=torch.float16)
        model.eval()

        # Очистка памяти
        gc.collect()

        _MODEL = model
        print(">>> Модель успешно загружена (ResNet50 + float16)")
        return model, _IDX2LABEL

    except Exception as e:
        print(f">>> КРИТИЧЕСКАЯ ОШИБКА загрузки модели: {e}")
        raise


# Трансформации (минимальные)
_PRE = transforms.Compose([
    transforms.Resize(224),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])


@torch.inference_mode()
def predict_image_topk(path: str, topk: int = 3):
    model, idx2label = _get_model()

    img = Image.open(path).convert("RGB")
    x = _PRE(img).unsqueeze(0).to(dtype=torch.float16)

    logits = model(x)
    if isinstance(logits, (tuple, list)):
        logits = logits[0]

    probs = F.softmax(logits, dim=1)[0]

    k = min(topk, probs.shape[0])
    confs, idxs = torch.topk(probs, k)

    top_list = []
    for conf, idx in zip(confs.tolist(), idxs.tolist()):
        label = idx2label[int(idx)]
        risk_level, risk_label = _risk_from_label(label)
        confidence = float(conf)
        percent = round(confidence * 100, 2)
        human_name = _LABEL_NAME.get(label, label)

        top_list.append({
            "label": label,
            "name": human_name,
            "confidence": confidence,
            "percent": percent,
            "risk_level": risk_level,
            "risk_label": risk_label,
        })

    best = top_list[0] if top_list else None
    return best, top_list


@torch.inference_mode()
def predict_image(path: str):
    best, _ = predict_image_topk(path, topk=3)
    if best is None:
        return "", 0.0
    return best["label"], best["percent"]


def get_treatment_plan(disease_name: str, risk_level: str | None = None) -> str:
    system_prompt = (
        "Ты медицинский ИИ Medora. "
        "На основе названия дерматологического диагноза и уровня риска "
        "составь структурированный план для пациента."
    )

    user_prompt = f"Диагноз по модели: {disease_name}.\nУровень риска: {risk_level or 'не указан'}."

    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": settings.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 350,
        "temperature": 0.3,
    }

    print(">>> CALL get_treatment_plan", disease_name, risk_level, flush=True)

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=35,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(">>> ERROR get_treatment_plan:", e, flush=True)
        return "Не удалось получить план действий от AI."
