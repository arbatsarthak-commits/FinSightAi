from pathlib import Path
from backend.ocr.ocr_service import extract_document

INPUT_FOLDER = Path("inputocrimage")
OUTPUT_FOLDER = Path("extracted_text.txt")


def perform(input_folder=INPUT_FOLDER, output_file=OUTPUT_FOLDER):
    all_text = ""
    for path in sorted(Path(input_folder).iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".pdf"}:
            continue
        try:
            result = extract_document(path)
            all_text += f"\n--Text from {path.name}--\n{result['text']}\n"
            print(f"Completed OCR: {path.name}")
        except Exception as exc:
            print(f"Error in {path.name}: {exc}")
    Path(output_file).write_text(all_text, encoding="utf-8")
    print("Completed OCR")


if __name__ == "__main__":
    perform()

