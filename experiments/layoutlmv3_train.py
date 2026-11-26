"""Optional LayoutLMv3 fine-tuning template.

This script does not download or claim a pretrained GST checkpoint.
It is intended for a labelled dataset of OCR words and BIO/field labels.
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Fine-tune LayoutLMv3 on labelled invoices.")
    parser.add_argument("--train-json", required=True)
    parser.add_argument("--output-dir", default="models/layoutlmv3-invoice")
    parser.add_argument("--base-model", default="microsoft/layoutlmv3-base")
    args = parser.parse_args()
    raise SystemExit(
        "Training scaffold is ready. Implement labeled JSON loading and Trainer "
        "configuration for your dataset before training."
    )


if __name__ == "__main__":
    main()
