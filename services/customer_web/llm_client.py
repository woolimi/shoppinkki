"""
채널 D: customer_web ↔ LLM (REST HTTP :8000)
자연어 상품 검색 전용 클라이언트.
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def query(name: str, host: str = "127.0.0.1", port: int = 8000) -> Optional[dict]:
    """
    LLM 서버에 자연어 상품 검색 질의.

    GET http://{host}:{port}/query?name={name}

    반환: {"zone_id": 3, "zone_name": "음료 코너"}
    실패 시 None 반환.
    """
    url = f"http://{host}:{port}/query"
    try:
        resp = requests.get(url, params={"name": name}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "zone_id" in data and "zone_name" in data:
            return data
        logger.warning("LLM 응답 형식 이상: %s", data)
        return None
    except requests.exceptions.Timeout:
        logger.error("LLM 서버 타임아웃: %s", url)
        return None
    except requests.exceptions.ConnectionError:
        logger.error("LLM 서버 연결 실패: %s", url)
        return None
    except Exception as e:
        logger.error("LLM 질의 오류: %s", e)
        return None
