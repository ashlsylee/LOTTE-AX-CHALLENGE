"""LLM 호출 래퍼: 캐시 + mock 모드 + JSON 스키마 강제 출력.

- 캐시: 같은 (모델, 프롬프트, 스키마) 요청은 outputs/llm_cache.jsonl 에서 재사용한다.
  비용을 아끼고, 다시 돌려도 같은 결과가 나오게(재현성) 하기 위함.
- mock: API 키 없이 파이프라인을 시험할 때 쓰는 가짜 응답.
- 접속 설정(.env): OPENAI_API_KEY(또는 GATEWAY_KEY), OPENAI_BASE_URL(대회 게이트웨이 등), VM_MODEL,
  VM_API = responses(기본, Responses API) | chat(Chat Completions). 대회 게이트웨이 예시가 Responses API라 기본값으로 둔다.
"""
import hashlib
import json
import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

from .config import DEFAULT_MODEL, OUT_DIR, load_env


class LLM:
    def __init__(self, model: str | None = None, mock: bool = False,
                 cache_path: Path = OUT_DIR / "llm_cache.jsonl", api_key: str | None = None):
        """api_key: 화면에서 사용자가 입력한 키(이번 실행에만 사용, 저장하지 않음). 없으면 .env/환경변수."""
        load_env()
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
            key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("GATEWAY_KEY")
            if not key:
                raise RuntimeError(
                    "OpenAI API 키가 없습니다. 화면 왼쪽에 키를 입력하거나, .env에 OPENAI_API_KEY를 넣거나, mock으로 실행하세요.")
            self.client = make_client(key)
        self.api = os.getenv("VM_API", "responses").lower()

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
            if self.api == "chat":
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": "response", "strict": True, "schema": schema}},
                )
                text = resp.choices[0].message.content or "{}"
            else:  # Responses API (대회 게이트웨이 방식)
                extra = {"reasoning": {"effort": os.getenv("VM_REASONING")}} if os.getenv("VM_REASONING") else {}
                resp = self.client.responses.create(
                    model=self.model,
                    instructions=system,
                    input=user,
                    text={"format": {"type": "json_schema", "name": "response", "strict": True, "schema": schema}},
                    **extra,
                )
                text = resp.output_text or "{}"
        data = json.loads(text)  # 형식이 깨지면 여기서 예외 → 호출한 쪽에서 실패로 기록
        with self.lock:
            self.api_calls += 1
            self.cache[key] = text
            with self.cache_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "text": text}, ensure_ascii=False) + "\n")
        return data


def make_client(api_key: str | None = None):
    """키·접속 주소를 .env에서 읽어 OpenAI 호환 클라이언트를 만든다(대회 게이트웨이도 같은 방식)."""
    load_env()
    from openai import OpenAI
    key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("GATEWAY_KEY")
    base = os.getenv("OPENAI_BASE_URL") or None
    return OpenAI(api_key=key, base_url=base) if base else OpenAI(api_key=key)


def check_connection(api_key: str | None = None) -> list[str]:
    """연결 시험: ① 짧은 응답 ② 정해진 형식(JSON 스키마) 응답. 결과를 사람이 읽을 문장으로."""
    load_env()
    out = []
    model = os.getenv("VM_MODEL") or DEFAULT_MODEL
    api = os.getenv("VM_API", "responses").lower()
    out.append(f"주소: {os.getenv('OPENAI_BASE_URL') or 'OpenAI 기본(api.openai.com)'} · 모델: {model} · 방식: {api}")
    try:
        c = make_client(api_key)
        if api == "chat":
            r = c.chat.completions.create(model=model, messages=[{"role": "user", "content": "OK라고만 답해"}])
            out.append("① 기본 응답 성공: " + (r.choices[0].message.content or "")[:30])
        else:
            r = c.responses.create(model=model, input="OK라고만 답해")
            out.append("① 기본 응답 성공: " + (r.output_text or "")[:30])
    except Exception as e:
        out.append(f"① 기본 응답 실패: {type(e).__name__}: {str(e)[:200]}")
        return out
    try:
        llm = LLM(model, api_key=api_key, cache_path=OUT_DIR / "llm_check_cache.jsonl")
        schema = {"type": "object", "additionalProperties": False, "required": ["ok", "n"],
                  "properties": {"ok": {"type": "boolean"}, "n": {"type": "integer"}}}
        data = llm.ask_json("JSON으로만 답하세요.", "ok는 true, n은 3", schema, lambda: {}, tag=f"check-{datetime_tag()}")
        out.append(f"② 형식 응답 성공: {data}")
    except Exception as e:
        out.append(f"② 형식 응답 실패: {type(e).__name__}: {str(e)[:200]} — .env에 VM_API=chat 으로 바꿔 다시 시험해 보세요.")
    return out


def datetime_tag():
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d%H%M%S")
