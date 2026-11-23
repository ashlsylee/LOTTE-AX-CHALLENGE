"""LLM 호출 래퍼: 캐시 + mock 모드 + JSON 스키마 강제 출력.

- 캐시: 같은 (모델, 프롬프트, 스키마) 요청은 outputs/llm_cache.jsonl 에서 재사용한다.
  비용을 아끼고, 다시 돌려도 같은 결과가 나오게(재현성) 하기 위함.
- mock: API 키 없이 파이프라인을 시험할 때 쓰는 가짜 응답.
"""
import hashlib
import json
import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

from .config import DEFAULT_MODEL, OUT_DIR


class LLM:
    def __init__(self, model: str | None = None, mock: bool = False,
                 cache_path: Path = OUT_DIR / "llm_cache.jsonl", api_key: str | None = None):
        """api_key: 화면에서 사용자가 입력한 키(이번 실행에만 사용, 저장하지 않음). 없으면 .env/환경변수."""
        load_dotenv()
        self.model = model or os.getenv("VM_MODEL") or DEFAULT_MODEL
        self.mock = mock
        self.cache_path = cache_path
        self.cache: dict[str, str] = {}
        self.lock = Lock()
        self.api_calls = 0
        self.cache_hits = 0
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                self.cache[rec["key"]] = rec["text"]
        if not mock:
            key = api_key or os.getenv("OPENAI_API_KEY")
            if not key:
                raise RuntimeError(
                    "OpenAI API 키가 없습니다. 화면 왼쪽에 키를 입력하거나, .env에 OPENAI_API_KEY를 넣거나, mock으로 실행하세요.")
            from openai import OpenAI
            self.client = OpenAI(api_key=key)

    def ask_json(self, system: str, user: str, schema: dict, mock_fn, tag: str = "") -> dict:
        """JSON 스키마에 맞는 응답을 dict로 돌려준다. tag는 반복 샘플링 구분용."""
        name = "mock" if self.mock else self.model
        raw = f"{name}|{tag}|{system}|{user}|{json.dumps(schema, sort_keys=True)}"
        key = hashlib.sha1(raw.encode()).hexdigest()
        with self.lock:
            if key in self.cache:
                self.cache_hits += 1
                return json.loads(self.cache[key])
        if self.mock:
            text = json.dumps(mock_fn(), ensure_ascii=False)
        else:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "response", "strict": True, "schema": schema}},
            )
            text = resp.choices[0].message.content or "{}"
        data = json.loads(text)  # 형식이 깨지면 여기서 예외 → 호출한 쪽에서 실패로 기록
        with self.lock:
            self.api_calls += 1
            self.cache[key] = text
            with self.cache_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "text": text}, ensure_ascii=False) + "\n")
        return data
