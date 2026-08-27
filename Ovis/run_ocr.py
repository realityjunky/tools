from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image
from vllm import LLM, SamplingParams


PROMPT = (
    "Extract all readable content from the image in natural human reading order "
    "and output the result as a single Markdown document. For charts or images, "
    "represent them using an HTML image tag: <img src=\"images/bbox_{left}_{top}_{right}_{bottom}.jpg\" />, "
    "where left, top, right, bottom are bounding box coordinates scaled to [0, 1000). "
    "Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown. Preserve the original text "
    "without translation or paraphrasing."
)


class OvisOCR2Parser:
    def __init__(self, model_path: Path, max_tokens: int) -> None:
        self.model = LLM(
            model=str(model_path),
            tensor_parallel_size=1,
            gpu_memory_utilization=0.8,
            gdn_prefill_backend="triton",
        )
        self.prompt = self.model.get_tokenizer().apply_chat_template(
            [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        self.sampling_params = SamplingParams(max_tokens=max_tokens, temperature=0.0)

    def parse(self, image_path: Path) -> str:
        with Image.open(image_path) as image:
            outputs = self.model.generate(
                [{
                    "prompt": self.prompt,
                    "multi_modal_data": {"image": image.convert("RGB")},
                    "mm_processor_kwargs": {
                        "images_kwargs": {"min_pixels": 448 * 448, "max_pixels": 2880 * 2880}
                    },
                }],
                self.sampling_params,
            )
        text = outputs[0].outputs[0].text.strip()
        text = "\n\n".join(
            block
            for block in text.split("\n\n")
            if not block.strip().startswith('<img src="images/bbox_')
        )
        return self._clean_truncated_repeats(text)

    @staticmethod
    def _clean_truncated_repeats(
        text: str,
        min_text_len: int = 8000,
        max_period: int = 200,
        min_period: int = 1,
        min_repeat_chars: int = 100,
        min_repeat_times: int = 5,
    ) -> str:
        n = len(text)
        if n < min_text_len:
            return text

        max_period = min(max_period, n - 1)
        for unit_len in range(min_period, max_period + 1):
            if text[n - 1] != text[n - 1 - unit_len]:
                continue

            match_len = 1
            index = n - 2
            while index >= unit_len and text[index] == text[index - unit_len]:
                match_len += 1
                index -= 1

            total_len = match_len + unit_len
            repeat_times = total_len // unit_len
            tail_len = total_len % unit_len
            if repeat_times >= min_repeat_times and total_len >= min_repeat_chars:
                return text[: n - total_len + unit_len] + text[n - tail_len:]

        return text


def main() -> None:
    project_path = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--model", type=Path, default=project_path / "model" / "OvisOCR2")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-tokens", type=int, default=16384)
    args = parser.parse_args()

    markdown = OvisOCR2Parser(args.model, args.max_tokens).parse(args.image)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown + "\n", encoding="utf-8")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
