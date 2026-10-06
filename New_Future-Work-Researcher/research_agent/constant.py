import os
from dotenv import load_dotenv
import global_state

load_dotenv()  # 加载.env文件
# utils: 
def str_to_bool(value):
    """convert string to bool"""
    true_values = {'true', 'yes', '1', 'on', 't', 'y'}
    false_values = {'false', 'no', '0', 'off', 'f', 'n'}
    
    if isinstance(value, bool):
        return value
        
    if not value:
        return False
        
    value = str(value).lower().strip()
    if value in true_values:
        return True
    if value in false_values:
        return False
    return True  # default return True


DOCKER_WORKPLACE_NAME = os.getenv('DOCKER_WORKPLACE_NAME', 'workplace_meta')
GITHUB_AI_TOKEN = os.getenv('GITHUB_AI_TOKEN', None)
AI_USER = os.getenv('AI_USER', "ai-sin")
LOCAL_ROOT = os.getenv('LOCAL_ROOT', os.getcwd())

DEBUG = str_to_bool(os.getenv('DEBUG', True))

DEFAULT_LOG = str_to_bool(os.getenv('DEFAULT_LOG', True))
LOG_PATH = os.getenv('LOG_PATH', None)
LOG_PATH = global_state.LOG_PATH
EVAL_MODE = str_to_bool(os.getenv('EVAL_MODE', False))
BASE_IMAGES = os.getenv('BASE_IMAGES', "tjbtech1/paperapp:latest")

COMPLETION_MODEL = os.getenv('COMPLETION_MODEL', "openrouter/openai/gpt-4o-2024-08-06") # 기존 - gpt-4o-2024-08-06
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', "text-embedding-3-small")
CHEEP_MODEL = os.getenv('CHEEP_MODEL', "openrouter/openai/gpt-4o-mini-2024-07-18") # openrouter수정시 위 아래 기존으로 바꿀 것 - gpt-4o-mini-2024-07-18
# [3단계 step4 판정자] Qwen2.5-72B + Likert — 생성(COMPLETION_MODEL)과 역할 분리(JuStRank 근거).
JUDGE_MODEL = os.getenv('JUDGE_MODEL', "openrouter/qwen/qwen-2.5-72b-instruct")
# BASE_URL = os.getenv('BASE_URL', None)

# GPUS = os.getenv('GPUS', "all")
GPUS = os.getenv('GPUS', None)

FN_CALL = str_to_bool(os.getenv('FN_CALL', True))
API_BASE_URL = os.getenv('API_BASE_URL', None)
ADD_USER = str_to_bool(os.getenv('ADD_USER', False))

NON_FN_CALL = str_to_bool(os.getenv('NON_FN_CALL', False))

# ── OpenRouter provider 라우팅 제어 ───────────────────────────────────────
# OpenRouter는 한 모델을 여러 upstream provider에 나눠 돌려막고(요청마다 랜덤 라우팅), 그중 하나가
# 죽어 있으면 그 provider로 배정된 요청만 간헐적으로 실패한다. 실측: qwen-2.5-72b는 DeepInfra(정상)와
# Novita(이 모델에 대해 400 "does not support endpoint" / stall) 둘로 돌려막혀, Novita에 걸린 판정자
# 호출만 실패 → 재시도 소진 후 KEEP-UNJUDGED로 루브릭이 통째로 스킵됐다.
#
# 기본 대책은 "고장난 provider를 라우팅에서 배제(ignore)"다 — 특정 provider로 강제 고정(order)보다 안전:
#   · qwen-72b: Novita만 빠지고 DeepInfra로 감 → 랜덤 실패 사라짐.
#   · grok/gemini 등 Novita가 애초에 안 파는 모델: 무영향(그 pool에 Novita가 없으니 no-op).
# 그래서 전 openrouter 모델에 일괄 적용해도 안전하다. 쉼표구분 목록. 비우면("") 배제 안 함.
OPENROUTER_IGNORE_PROVIDERS = os.getenv('OPENROUTER_IGNORE_PROVIDERS', "Novita")
# (선택) 특정 provider로 우선/고정하고 싶을 때의 우선순위 목록. 모델마다 파는 provider가 달라 전역 order는
# 위험하므로 기본은 비움. 값을 주면 그 provider들을 우선 사용한다(예: "DeepInfra").
OPENROUTER_PROVIDER_ORDER = os.getenv('OPENROUTER_PROVIDER_ORDER', "")
# order를 쓸 때만 의미 있음. True면 지정 provider가 죽었을 때 나머지로 폴백(권장), False면 엄격 고정(죽으면 실패).
OPENROUTER_ALLOW_FALLBACKS = str_to_bool(os.getenv('OPENROUTER_ALLOW_FALLBACKS', True))


def openrouter_provider_extra_body(model: str) -> dict:
    """OpenRouter 모델일 때만 provider 라우팅을 담은 extra_body(litellm→OpenRouter 요청 body로 그대로
    전달)를 돌려준다. openrouter 모델이 아니거나(gpt/gemini 직접호출 등) 라우팅 설정이 비면 빈 dict —
    아무 것도 안 붙여 기존 동작 그대로. 호출부에서 create_params/completion kwargs에 **merge 하면 된다."""
    if not model or "openrouter/" not in model:
        return {}
    provider: dict = {}
    order = [p.strip() for p in OPENROUTER_PROVIDER_ORDER.split(",") if p.strip()]
    ignore = [p.strip() for p in OPENROUTER_IGNORE_PROVIDERS.split(",") if p.strip()]
    if order:
        provider["order"] = order
        provider["allow_fallbacks"] = OPENROUTER_ALLOW_FALLBACKS
    if ignore:
        provider["ignore"] = ignore
    if not provider:
        return {}
    return {"extra_body": {"provider": provider}}


NOT_SUPPORT_SENDER = ["mistral", "groq"]


MUST_ADD_USER = ["deepseek/deepseek-reasoner", "o1-mini"]
NOT_SUPPORT_FN_CALL = ["o1-mini", "deepseek/deepseek-reasoner"]
NOT_USE_FN_CALL = [ "deepseek/deepseek-chat"] + NOT_SUPPORT_FN_CALL

if EVAL_MODE:
    DEFAULT_LOG = False

# if "deepseek" in COMPLETION_MODEL:
#     os.environ["http_proxy"] = "http://127.0.0.1:7890"
#     os.environ["https_proxy"] = "http://127.0.0.1:7890"


