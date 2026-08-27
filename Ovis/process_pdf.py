from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from run_ocr import OvisOCR2Parser


def render_pages(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    prefix = output_dir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return sorted(
        output_dir.glob("page-*.png"),
        key=lambda path: int(path.stem.rsplit("-", 1)[1]),
    )


def main() -> None:
    project_path = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--model", type=Path, default=project_path / "model" / "OvisOCR2")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--max-tokens", type=int, default=16384)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    total_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ovisocr2-pdf-") as temporary_dir:
        render_started = time.perf_counter()
        page_paths = render_pages(args.pdf, Path(temporary_dir), args.dpi)
        render_seconds = time.perf_counter() - render_started

        engine_started = time.perf_counter()
        ocr_parser = OvisOCR2Parser(args.model, args.max_tokens)
        engine_init_seconds = time.perf_counter() - engine_started

        page_metrics = []
        page_outputs = []
        inference_started = time.perf_counter()
        for page_number, page_path in enumerate(page_paths, start=1):
            page_started = time.perf_counter()
            markdown = ocr_parser.parse(page_path)
            page_seconds = time.perf_counter() - page_started
            page_output_path = args.output_dir / f"page-{page_number:03d}.md"
            page_output_path.write_text(markdown + "\n", encoding="utf-8")
            page_metrics.append({
                "page": page_number,
                "seconds": round(page_seconds, 3),
                "characters": len(markdown),
                "words": len(markdown.split()),
            })
            page_outputs.append(f"# Page {page_number}\n\n{markdown}")
        inference_seconds = time.perf_counter() - inference_started

    total_seconds = time.perf_counter() - total_started
    page_count = len(page_paths)
    metrics = {
        "pdf": str(args.pdf.resolve()),
        "model": str(args.model.resolve()),
        "dpi": args.dpi,
        "max_tokens": args.max_tokens,
        "page_count": page_count,
        "render_seconds": round(render_seconds, 3),
        "engine_init_seconds": round(engine_init_seconds, 3),
        "inference_seconds": round(inference_seconds, 3),
        "total_seconds": round(total_seconds, 3),
        "inference_pages_per_minute": round(page_count / inference_seconds * 60, 3) if inference_seconds else None,
        "end_to_end_pages_per_minute": round(page_count / total_seconds * 60, 3) if total_seconds else None,
        "pages": page_metrics,
    }
    (args.output_dir / "ocr.md").write_text("\n\n".join(page_outputs) + "\n", encoding="utf-8")
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
