import cv2
from pathlib import Path
from backend.preprocessing.image_processor import preprocess_image


INPUT_FOLDER = Path("inputocrimage")
OUTPUT_FOLDER = Path("outputocrimage")


def image_cleaning(input_folder=INPUT_FOLDER, output_folder=OUTPUT_FOLDER):
    input_folder = Path(input_folder)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    converted = 0
    for path in sorted(input_folder.iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        try:
            processed = preprocess_image(path)
            cv2.imwrite(str(output_folder / path.name), processed)
            converted += 1
            print(f"Converted {path.name}")
        except Exception as exc:
            print(f"Failed to convert {path.name}: {exc}")
    return converted


if __name__ == "__main__":
    image_cleaning()









