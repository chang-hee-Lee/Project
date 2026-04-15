# """
# 피부 분석 프로그램 (Gemini 2.0 Flash 기반)
# ========================================
# - 모델  : gemini-2.0-flash (무료 티어 지원)
# - 무료 한도 : 15 RPM / 1,500 RPD / 1M TPM
# - 특징  : 자동 재시도, 이미지 압축, 토큰 절약 프롬프트

# 사전 설치:
#     pip install google-generativeai python-dotenv Pillow
# """

# import os
# import sys
# import time
# import re
# import io
# import random
# from dotenv import load_dotenv

# # ── 의존 패키지 확인 ─────────────────────────────────────────────
# try:
#     import google.generativeai as genai
#     from google.api_core import exceptions as google_exceptions
# except ImportError:
#     print("오류: 'google-generativeai' 패키지가 없습니다.")
#     print("설치:  pip install google-generativeai")
#     sys.exit(1)

# try:
#     from PIL import Image
#     PIL_AVAILABLE = True
# except ImportError:
#     PIL_AVAILABLE = False  # 이미지 압축 없이 진행 (선택 사항)

# # ── 환경 설정 ────────────────────────────────────────────────────
# load_dotenv()
# API_KEY = os.getenv("GEMINI_API_KEY")

# if not API_KEY:
#     print("오류: API 키가 없습니다.")
#     print(".env 파일에  GEMINI_API_KEY=your_api_key  를 추가하세요.")
#     sys.exit(1)

# genai.configure(api_key=API_KEY)

# # ── 무료 티어 최적 모델 ─────────────────────────────────────────
# MODEL_NAME = "gemini-2.0-flash"          # 무료 15 RPM / 1,500 RPD
# GENERATION_CONFIG = genai.types.GenerationConfig(
#     temperature=0.4,                     # 일관된 분석을 위해 낮게 설정
#     max_output_tokens=1024,              # 토큰 절약 (무료 한도 보호)
# )

# model = genai.GenerativeModel(
#     model_name=MODEL_NAME,
#     generation_config=GENERATION_CONFIG,
# )

# # ── 무료 티어 레이트 리밋 설정 ──────────────────────────────────
# # 실제 한도(15 RPM)보다 보수적으로 10 RPM 기준 사용 → 여유 확보
# FREE_TIER_RPM    = 10
# MIN_REQ_INTERVAL = 60 / FREE_TIER_RPM   # 6초 간격

# # 여러 프로그램이 같은 API 키를 공유하므로, 마지막 요청 시각을 파일로 동기화
# _TIMESTAMP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gemini_last_request")


# def _rate_limit_wait():
#     """무료 티어 RPM 초과 방지: API 호출 전 최소 간격 보장 (파일 기반 크로스-프로세스 동기화)"""
#     try:
#         last = float(open(_TIMESTAMP_FILE).read().strip())
#     except (FileNotFoundError, ValueError):
#         last = 0.0

#     elapsed = time.time() - last
#     if elapsed < MIN_REQ_INTERVAL:
#         wait = MIN_REQ_INTERVAL - elapsed
#         print(f"  (요청 간격 조정: {wait:.1f}초 대기…)", end="\r", flush=True)
#         time.sleep(wait)

#     with open(_TIMESTAMP_FILE, "w") as f:
#         f.write(str(time.time()))


# def _exponential_backoff(attempt: int, base: float = 15.0, cap: float = 120.0) -> float:
#     """
#     지수 백오프 + Jitter:  min(base × 2^(attempt-1) + random, cap)
#     attempt=1 → ~15s, attempt=2 → ~30s, attempt=3 → ~60s
#     """
#     delay = min(base * (2 ** (attempt - 1)), cap)
#     jitter = random.uniform(0, delay * 0.2)   # ±20% 랜덤 지터
#     return round(delay + jitter, 1)


# # ────────────────────────────────────────────────────────────────
# # 1. 피부 MBTI 설문
# # ────────────────────────────────────────────────────────────────
# def _ask(question: str) -> str:
#     """A 또는 B만 입력받는 단순 질문"""
#     while True:
#         ans = input(f"  {question} (A/B): ").strip().upper()
#         if ans in ("A", "B"):
#             return ans
#         print("  A 또는 B를 입력해 주세요.")


# def survey_mbti() -> str:
#     """
#     Baumann 피부 타입 설문 (12문항)
#     반환값 예: 'DSPT', 'ORNT', …
#     """
#     scores = {k: 0 for k in "DOSPRNWT"}

#     categories = [
#         ("건성(D) vs 지성(O)", [
#             ("세안 후 피부가 당기거나 건조하다 / 번들거리거나 유분이 많다", "D", "O", 2),
#             ("오후에 피부가 건조해진다 / 유분이 올라온다",                  "D", "O", 1),
#             ("모공이 거의 안 보인다 / 모공이 잘 보인다",                   "D", "O", 1),
#         ]),
#         ("민감성(S) vs 저항성(R)", [
#             ("새 화장품 사용 시 트러블이 자주 생긴다 / 거의 없다",         "S", "R", 2),
#             ("피부가 자주 붉어지거나 가렵다 / 그렇지 않다",                "S", "R", 1),
#             ("자외선·바람 등 환경 변화에 피부가 민감하다 / 강하다",        "S", "R", 1),
#         ]),
#         ("색소성(P) vs 비색소성(N)", [
#             ("잡티·기미가 많다 / 거의 없다",                              "P", "N", 2),
#             ("햇빛에 노출 후 색소침착이 잘 생긴다 / 잘 안 생긴다",        "P", "N", 1),
#             ("여드름 자국이 오래 남는다 / 금방 사라진다",                  "P", "N", 1),
#         ]),
#         ("주름성(W) vs 탄력성(T)", [
#             ("눈가·이마에 주름이 보인다 / 거의 없다",                      "W", "T", 2),
#             ("피부 탄력이 많이 줄었다 / 탄력이 좋은 편이다",               "W", "T", 1),
#             ("자외선 차단을 잘 하지 않는다 / 꼼꼼히 한다",                 "W", "T", 1),
#         ]),
#     ]

#     for title, questions in categories:
#         print(f"\n[{title}]")
#         for q, a_key, b_key, w in questions:
#             winner = a_key if _ask(q) == "A" else b_key
#             scores[winner] += w

#     skin_type = (
#         ("D" if scores["D"] >= scores["O"] else "O") +
#         ("S" if scores["S"] >= scores["R"] else "R") +
#         ("P" if scores["P"] >= scores["N"] else "N") +
#         ("W" if scores["W"] >= scores["T"] else "T")
#     )
#     return skin_type


# # ────────────────────────────────────────────────────────────────
# # 2. 이미지 전처리 (토큰 절약용 압축)
# # ────────────────────────────────────────────────────────────────
# MAX_IMAGE_DIM   = 768   # 무료 티어 토큰 절약: 최대 해상도 제한
# MAX_IMAGE_BYTES = 3 * 1024 * 1024  # 3 MB


# def _prepare_image(image_path: str) -> tuple[bytes, str]:
#     """
#     이미지를 읽어 (bytes, mime_type) 반환.
#     Pillow가 있으면 크기·용량을 줄여 토큰을 절약한다.
#     """
#     ext = os.path.splitext(image_path)[1].lower()
#     mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
#     mime_type = mime_map.get(ext, "image/jpeg")

#     with open(image_path, "rb") as f:
#         raw = f.read()

#     if not PIL_AVAILABLE:
#         if len(raw) > MAX_IMAGE_BYTES:
#             print("⚠️  이미지가 크지만 Pillow 없이는 압축할 수 없습니다.")
#             print("   pip install Pillow  로 설치하면 자동 압축됩니다.")
#         return raw, mime_type

#     # Pillow로 압축
#     img = Image.open(io.BytesIO(raw))
#     if img.mode == "RGBA":
#         img = img.convert("RGB")
#         mime_type = "image/jpeg"

#     # 해상도 축소
#     if max(img.size) > MAX_IMAGE_DIM:
#         img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM), Image.LANCZOS)

#     # JPEG 품질 조정으로 용량 절약
#     buf = io.BytesIO()
#     save_fmt = "JPEG" if mime_type == "image/jpeg" else "PNG"
#     quality = 85
#     img.save(buf, format=save_fmt, quality=quality, optimize=True)

#     compressed = buf.getvalue()
#     ratio = len(compressed) / len(raw) * 100
#     print(f"  이미지 압축 완료: {len(raw)//1024}KB → {len(compressed)//1024}KB ({ratio:.0f}%)")
#     return compressed, mime_type


# # ────────────────────────────────────────────────────────────────
# # 3. Gemini API 호출 (자동 재시도 포함)
# # ────────────────────────────────────────────────────────────────
# def _parse_retry_wait(err_msg: str) -> int | None:
#     """
#     Google API 오류 메시지에서 재시도 대기 시간(초)을 추출.
#     retry_delay { seconds: N } 또는 retry-after: N 형식 지원.
#     """
#     # grpc 메타데이터 형식: retry_delay { seconds: 60 }
#     m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", err_msg)
#     if m:
#         return int(m.group(1)) + 3

#     # HTTP 헤더 형식: retry-after: 60
#     m = re.search(r"retry[_-]after[:\s]+(\d+\.?\d*)", err_msg.lower())
#     if m:
#         return int(float(m.group(1))) + 3

#     return None


# def _is_daily_limit(err_msg: str) -> bool:
#     """일일 한도(RPD) 초과 여부 판별"""
#     lower = err_msg.lower()
#     return "per day" in lower or "daily" in lower or "1500" in lower or "rpd" in lower


# def _call_gemini(parts: list, max_retries: int = 5) -> str | None:
#     """
#     Gemini API 호출 + 무료 티어 429 오류 자동 재시도 (지수 백오프).

#     - ResourceExhausted(429) : 지수 백오프 후 재시도 (일일 한도 시 즉시 중단)
#     - SafetyBlock           : 즉시 중단, 안내 출력
#     - 기타 오류             : 즉시 중단
#     성공 시 응답 텍스트, 실패 시 None 반환.
#     """
#     for attempt in range(1, max_retries + 1):
#         _rate_limit_wait()
#         try:
#             response = model.generate_content(parts)

#             # 응답이 차단된 경우 (finish_reason == SAFETY)
#             if not response.parts:
#                 print("\n⚠️  안전 필터로 인해 응답이 차단되었습니다.")
#                 print("   다른 각도나 조명의 사진으로 다시 시도해 주세요.")
#                 return None

#             return response.text

#         # ── 429 Resource Exhausted (무료 한도 초과) ──────────────
#         except google_exceptions.ResourceExhausted as e:
#             err_msg = str(e)

#             # 일일 한도 초과 → 재시도 의미 없음
#             if _is_daily_limit(err_msg):
#                 _print_quota_help(daily=True)
#                 return None

#             # 서버가 retry-after 값을 알려주면 우선 사용, 아니면 지수 백오프
#             server_wait = _parse_retry_wait(err_msg)
#             wait_sec = server_wait if server_wait else _exponential_backoff(attempt)

#             if attempt < max_retries:
#                 print(f"\n⚠️  분당 요청 한도 초과 — {wait_sec}초 후 재시도합니다. "
#                       f"({attempt}/{max_retries})")
#                 for t in range(int(wait_sec), 0, -1):
#                     print(f"\r  대기 중: {t:3d}초 남음   ", end="", flush=True)
#                     time.sleep(1)
#                 print("\r  재시도합니다…                  ")
#             else:
#                 _print_quota_help(daily=False)
#                 return None

#         # ── 인증 오류 ─────────────────────────────────────────────
#         except google_exceptions.Unauthenticated:
#             print("\n❌ API 키가 유효하지 않습니다. .env 파일을 확인하세요.")
#             return None

#         # ── 안전 필터 / 입력 오류 ────────────────────────────────
#         except google_exceptions.InvalidArgument as e:
#             print(f"\n❌ 잘못된 요청: {e}")
#             print("   이미지 형식이나 크기를 확인해 주세요.")
#             return None

#         # ── 서버/네트워크 일시 오류 → 재시도 ────────────────────
#         except (google_exceptions.ServiceUnavailable,
#                 google_exceptions.DeadlineExceeded) as e:
#             wait_sec = _exponential_backoff(attempt, base=10.0)
#             if attempt < max_retries:
#                 print(f"\n⚠️  서버 일시 오류 — {wait_sec}초 후 재시도합니다. "
#                       f"({attempt}/{max_retries})")
#                 time.sleep(wait_sec)
#             else:
#                 print(f"\n❌ 서버 오류 반복: {e}")
#                 return None

#         # ── 예상치 못한 기타 오류 ────────────────────────────────
#         except Exception as e:
#             err = str(e)
#             # 혹시 문자열에 429가 포함된 경우 (라이브러리 버전 차이 대비)
#             if "429" in err or "quota" in err.lower() or "exhausted" in err.lower():
#                 if _is_daily_limit(err):
#                     _print_quota_help(daily=True)
#                     return None
#                 wait_sec = _exponential_backoff(attempt)
#                 if attempt < max_retries:
#                     print(f"\n⚠️  요청 한도 초과(fallback) — {wait_sec}초 후 재시도 "
#                           f"({attempt}/{max_retries})")
#                     for t in range(int(wait_sec), 0, -1):
#                         print(f"\r  대기 중: {t:3d}초 남음   ", end="", flush=True)
#                         time.sleep(1)
#                     print()
#                     continue
#                 else:
#                     _print_quota_help(daily=False)
#                     return None
#             print(f"\n❌ 예상치 못한 오류: {e}")
#             return None

#     return None


# def _print_quota_help(daily: bool = False):
#     print("\n❌ 재시도 횟수를 초과했습니다.")
#     print("─" * 50)
#     print("  무료 티어 한도 안내")
#     print("  • 분당 요청: 15 RPM")
#     print("  • 일일 요청: 1,500 RPD")
#     if daily:
#         print("\n  ※ 일일 한도(1,500 RPD)를 초과했습니다.")
#         print("  해결 방법:")
#         print("  1. 내일 다시 시도하세요 (일일 한도 초과)")
#         print("  2. 유료 플랜 전환 → https://ai.dev/rate-limit")
#     else:
#         print("\n  ※ 분당 한도(15 RPM)를 초과했습니다.")
#         print("  해결 방법:")
#         print("  1. 잠시 후 다시 실행하세요 (약 1~2분 후)")
#         print("  2. 유료 플랜 전환 → https://ai.dev/rate-limit")
#     print("─" * 50)


# # ────────────────────────────────────────────────────────────────
# # 4. 피부 분석 (이미지 + MBTI → 결과 텍스트)
# # ────────────────────────────────────────────────────────────────
# SKIN_TYPE_DESC = {
#     "D": "건성", "O": "지성",
#     "S": "민감성", "R": "저항성",
#     "P": "색소성", "N": "비색소성",
#     "W": "주름성", "T": "탄력성",
# }


# def _mbti_korean(mbti: str) -> str:
#     return "-".join(SKIN_TYPE_DESC.get(c, c) for c in mbti)


# def analyze_skin(image_path: str, mbti: str) -> str | None:
#     """이미지와 피부 MBTI를 기반으로 Gemini 분석 결과 반환"""
#     try:
#         img_bytes, mime_type = _prepare_image(image_path)
#     except FileNotFoundError:
#         print(f"오류: 이미지 파일을 찾을 수 없습니다 → {image_path}")
#         return None

#     mbti_kor = _mbti_korean(mbti)

#     # 토큰을 절약하면서도 구조화된 프롬프트
#     prompt = f"""피부 타입: {mbti} ({mbti_kor})
# 아래 사진을 분석하여 다음 형식으로 한국어로 답변하라.

# [피부 상태]
# 전반적인 피부 상태를 2~3문장으로 서술

# [주요 문제 3가지]
# 1. (문제명): 간략 설명
# 2. (문제명): 간략 설명
# 3. (문제명): 간략 설명

# [개선 방법]
# 각 문제에 대한 구체적 스킨케어 루틴 및 성분 추천

# [생활 습관 개선]
# 식이, 수면, 자외선 차단 등 실천 가능한 항목 3가지

# [주의사항]
# 피부 타입 {mbti}에 특별히 주의해야 할 점"""

#     print(f"\n  분석 중… (모델: {MODEL_NAME})")
#     return _call_gemini([prompt, {"mime_type": mime_type, "data": img_bytes}])


# # ────────────────────────────────────────────────────────────────
# # 5. 결과 저장
# # ────────────────────────────────────────────────────────────────
# def save_result(mbti: str, result: str, output_dir: str) -> str:
#     """결과를 텍스트 파일로 저장하고 경로를 반환"""
#     os.makedirs(output_dir, exist_ok=True)
#     timestamp = time.strftime("%Y%m%d_%H%M%S")
#     filename = f"skin_result_{mbti}_{timestamp}.txt"
#     path = os.path.join(output_dir, filename)

#     with open(path, "w", encoding="utf-8") as f:
#         f.write(f"피부 타입 (MBTI) : {mbti}  ({_mbti_korean(mbti)})\n")
#         f.write(f"분석 일시         : {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
#         f.write(f"사용 모델         : {MODEL_NAME}\n")
#         f.write("=" * 50 + "\n\n")
#         f.write(result)

#     return path


# # ────────────────────────────────────────────────────────────────
# # 메인 실행
# # ────────────────────────────────────────────────────────────────
# def main():
#     print("=" * 50)
#     print("  피부 분석 프로그램  (Gemini 2.0 Flash)")
#     print(f"  무료 한도: {FREE_TIER_RPM} RPM / 1,500 RPD")
#     print("=" * 50)

#     # 1) 설문
#     mbti = survey_mbti()
#     print(f"\n✅ 피부 타입: {mbti}  ({_mbti_korean(mbti)})")

#     # 2) 이미지 경로 입력
#     while True:
#         raw = input("\n이미지 경로를 입력하세요 (.jpg / .jpeg / .png): ")
#         img_path = raw.strip().strip('"').strip("'")

#         if not img_path.lower().endswith((".jpg", ".jpeg", ".png")):
#             print("지원 형식: .jpg  .jpeg  .png")
#             continue
#         if not os.path.isfile(img_path):
#             print(f"파일을 찾을 수 없습니다: {img_path}")
#             continue
#         break

#     # 3) 분석
#     result = analyze_skin(img_path, mbti)

#     if not result:
#         print("\n분석을 완료하지 못했습니다. 위의 안내를 참고하세요.")
#         sys.exit(1)

#     # 4) 출력
#     print("\n" + "=" * 50)
#     print("  [분석 결과]")
#     print("=" * 50)
#     print(result)

#     # 5) 저장
#     script_dir = os.path.dirname(os.path.abspath(__file__))
#     saved_path = save_result(mbti, result, script_dir)
#     print(f"\n💾 결과 저장 완료 → {saved_path}")


# if __name__ == "__main__":
#     main()