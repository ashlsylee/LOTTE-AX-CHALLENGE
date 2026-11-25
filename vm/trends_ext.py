"""외부 트렌드 자동 수집: 네이버 검색어 트렌드 API(공식).

- 2026-10부터 신규 신청은 NAVER API HUB(네이버 클라우드 플랫폼)에서만 받는다(기본값).
  콘솔 > Application Services > NAVER API HUB > Application 등록 → '검색어 트렌드' 선택 →
  [인증 정보]의 Client ID/Secret 을 .env 의 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 에 넣는다.
  (한시 무료, 월 50,000건, API 키당 50 RPS — 공식 문서 기준, 유료 전환 시 사전 공지)
- 예전 개발자센터(developers.naver.com)에서 받은 키는 .env 에 NAVER_API=devcenter 를 추가하면 그대로 쓴다.
- 한 번에 키워드 그룹 최대 5개. 같은 요청 안의 그룹끼리는 같은 기준(최대값=100)이라 크기 비교가 된다.
  (대회 자료의 검색 지수처럼 키워드마다 따로 환산한 값과 다름)
- 주 단위(week)·월 단위(month)로 받고, 받은 결과는 자료 저장소에 '검색 트렌드 지수' 표로 저장된다(출처·수집일 표시).
- 자동 갱신: 앱을 열 때 마지막 수집이 7일 넘었으면 '업데이트' 안내. 컴퓨터가 꺼져 있어도 되게 하려면
  Windows 작업 스케줄러에 `python -m vm.trends_ext --refresh` 를 주 1회 등록.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import pandas as pd

from . import store

HUB_URL = "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"
DEVCENTER_URL = "https://openapi.naver.com/v1/datalab/search"


def endpoint():
    """(주소, 헤더 이름 2개). 기본은 API HUB, NAVER_API=devcenter 면 예전 개발자센터."""
    if os.getenv("NAVER_API", "hub").lower() == "devcenter":
        return DEVCENTER_URL, ("X-Naver-Client-Id", "X-Naver-Client-Secret")
    return HUB_URL, ("X-NCP-APIGW-API-KEY-ID", "X-NCP-APIGW-API-KEY")


def has_key() -> bool:
    return bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET"))


def fetch(groups: dict[str, list[str]], unit: str = "week", years: int = 3) -> pd.DataFrame:
    """groups: {"그룹 이름": ["검색어1", "검색어2"]} (최대 5개). 반환: 기준월(또는 주) × 그룹 넓은 표."""
    if not has_key():
        raise RuntimeError(".env 에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 를 넣어 주세요.")
    if not 1 <= len(groups) <= 5:
        raise ValueError("키워드 그룹은 1~5개입니다.")
    end = date.today() - timedelta(days=1)
    body = {"startDate": str(end.replace(year=end.year - years)), "endDate": str(end), "timeUnit": unit,
            "keywordGroups": [{"groupName": g, "keywords": [k for k in ks if k][:20] or [g]} for g, ks in groups.items()]}
    url, (h_id, h_secret) = endpoint()
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        h_id: os.environ["NAVER_CLIENT_ID"].strip(), h_secret: os.environ["NAVER_CLIENT_SECRET"].strip(),
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode("utf-8"))
            msg = j.get("errMsg") or j.get("errorMessage") or (j.get("error") or {}).get("message", "")
        except Exception:
            msg = ""
        where = ("네이버 클라우드 콘솔 > NAVER API HUB > Application" if os.getenv("NAVER_API", "hub").lower() != "devcenter"
                 else "네이버 개발자센터 > 내 애플리케이션")
        hint = {401: f"Client ID/Secret이 틀렸거나, {where}에 '검색어 트렌드' API가 선택돼 있지 않습니다. "
                     "개발자센터에서 받은 예전 키라면 .env에 NAVER_API=devcenter 를 추가하세요.",
                403: f"{where}의 API 권한 설정을 확인하세요.",
                429: "호출 한도를 넘었습니다(월 50,000건 또는 초당 한도). 잠시 뒤 다시 받으세요.",
                400: "키워드 그룹·기간 형식을 확인하세요(그룹 5개, 그룹당 검색어 20개 이하)."}.get(e.code, "")
        raise RuntimeError(f"네이버 데이터랩 오류 {e.code} {msg} — {hint}".strip()) from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"네이버 서버에 연결하지 못했습니다(인터넷·회사 방화벽 확인): {e.reason}") from None
    frames = []
    for res in data.get("results", []):
        s = pd.Series({p["period"]: p["ratio"] for p in res["data"]}, name=res["title"])
        frames.append(s)
    if not frames:
        raise RuntimeError("결과가 비어 있습니다. 검색량이 너무 적은 키워드일 수 있습니다.")
    wide = pd.concat(frames, axis=1).sort_index()
    if unit == "month":
        wide.index = [i[:7] for i in wide.index]
        wide.index.name = "기준월"
    else:
        wide.index.name = "기준주"
    return wide.reset_index()


def to_monthly(wide: pd.DataFrame) -> pd.DataFrame:
    """주 단위 → 월 평균(분석 모듈은 월 단위 '기준월'을 씀). 최근 달은 진행 중이면 표시."""
    if "기준월" in wide:
        return wide
    w = wide.copy()
    w["기준월"] = w["기준주"].str[:7]
    return w.drop(columns="기준주").groupby("기준월").mean().round(1).reset_index()


def collect(groups: dict[str, list[str]], unit: str = "week", years: int = 3, dataset: str | None = None) -> dict:
    """받아서 저장소에 등록(주 단위 원본 + 분석용 월 평균 두 표). 같은 그룹 설정의 이전 수집본은 분석에서 제외."""
    wide = fetch(groups, unit, years)
    monthly = to_monthly(wide)
    stamp = datetime.now().strftime("%Y-%m-%d")
    label = f"네이버 데이터랩 검색어 트렌드 ({', '.join(groups)})"
    db = store._connect()
    with db:
        db.execute("UPDATE files SET active=0 WHERE name LIKE ? AND dataset=? AND source='API'",
                   ("네이버 데이터랩 검색어 트렌드%", dataset or store.active_dataset()))  # 같은 묶음의 예전 수집분은 키워드가 달라도 모두 끔
    frames = {"월평균(분석용)": monthly.assign(_row=range(2, len(monthly) + 2))}
    if unit == "week":
        frames["주별(원본)"] = wide.assign(_row=range(2, len(wide) + 2))
    import hashlib
    sha = hashlib.sha256((wide.to_csv(index=False) + stamp).encode()).hexdigest()
    res = store._save(f"{label} · 수집 {stamp}", sha, frames, "", dataset or store.active_dataset(), "API")
    # 주별 원본은 분석에 겹쳐 쓰지 않도록 역할을 비워 둔다(월평균만 '검색 트렌드'로 사용)
    with store._connect() as db2:
        db2.execute("UPDATE tables SET role=NULL, how='참고(주별 원본)' WHERE sheet='주별(원본)' AND file_id IN "
                    "(SELECT file_id FROM files WHERE sha256=?)", (sha,))
    links = store.get_setting("trend_jobs", {})
    links[dataset or store.active_dataset()] = {"groups": groups, "unit": unit, "years": years, "last": stamp}
    store.set_setting("trend_jobs", links)
    return {"rows": len(wide), "months": len(monthly), "period": f"{wide.iloc[0, 0]} ~ {wide.iloc[-1, 0]}", **res}


def due(days: int = 7) -> dict | None:
    """마지막 수집 후 days일이 지났으면 그 설정을 돌려준다."""
    job = store.get_setting("trend_jobs", {}).get(store.active_dataset())
    if job and (date.today() - date.fromisoformat(job["last"])).days >= days:
        return job
    return None


def main():
    from .config import load_env
    load_env()
    ap = argparse.ArgumentParser(description="네이버 데이터랩 검색어 트렌드 수집")
    ap.add_argument("--refresh", action="store_true", help="모든 자료 묶음의 저장된 수집 설정으로 다시 받기")
    a = ap.parse_args()
    if a.refresh:
        for ds, job in store.get_setting("trend_jobs", {}).items():
            print(ds, collect(job["groups"], job["unit"], job["years"], ds))


if __name__ == "__main__":
    main()
