from pathlib import Path


class LayoutLMUnavailable(RuntimeError):
    pass


def load_layoutlm(checkpoint: str):
    if not checkpoint:
        raise LayoutLMUnavailable(
            "LayoutLMv3 is optional. Set LAYOUTLM_MODEL or pass a fine-tuned checkpoint."
        )
    try:
        import torch
        from transformers import AutoModelForTokenClassification, AutoProcessor
    except ImportError as exc:
        raise LayoutLMUnavailable(
            "LayoutLMv3 requires torch and transformers dependencies."
        ) from exc
    if not Path(checkpoint).exists() and "/" not in checkpoint:
        raise LayoutLMUnavailable(
            "No local checkpoint found. This app does not download models at startup."
        )
    processor = AutoProcessor.from_pretrained(checkpoint, apply_ocr=False)
    model = AutoModelForTokenClassification.from_pretrained(checkpoint)
    model.eval()
    return processor, model


def infer_layoutlm(image, words, checkpoint: str):
    processor, model = load_layoutlm(checkpoint)
    import torch

    width, height = image.size
    normalized_boxes = []
    texts = []
    for word in words:
        x1 = max(0, min(1000, int(word["left"] * 1000 / width)))
        y1 = max(0, min(1000, int(word["top"] * 1000 / height)))
        x2 = max(0, min(1000, int((word["left"] + word["width"]) * 1000 / width)))
        y2 = max(0, min(1000, int((word["top"] + word["height"]) * 1000 / height)))
        normalized_boxes.append([x1, y1, x2, y2])
        texts.append(word["text"])
    encoding = processor(
        image, texts, boxes=normalized_boxes, return_tensors="pt",
        truncation=True,
    )
    with torch.no_grad():
        logits = model(**encoding).logits
    predictions = logits.argmax(-1).squeeze().tolist()
    if isinstance(predictions, int):
        predictions = [predictions]
    id_to_label = model.config.id2label
    return [
        {"text": text, "box": box, "label": id_to_label.get(prediction, str(prediction))}
        for text, box, prediction in zip(texts, normalized_boxes, predictions[:len(texts)])
    ]
