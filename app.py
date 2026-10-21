from __future__ import annotations

import html
import base64
from io import BytesIO
import json
import os
import re
import zipfile
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from PIL import Image, ImageDraw
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, OpenAIError

APP_DIR = Path(__file__).resolve().parent
MODEL = "gpt-6-luna"
IMAGE_MODEL = "gpt-image-2.5-flare"
for raw_line in (APP_DIR / ".env").read_text(encoding="utf-8-sig").splitlines() if (APP_DIR / ".env").exists() else []:
    line = raw_line.strip()
    if line and not line.startswith("#") and "=" in line:
        env_name, env_value = line.split("=", 1)
        env_name = env_name.strip()
        if env_name and env_name not in os.environ:
            os.environ[env_name] = env_value.strip().strip("\"'")
if not os.getenv("OPENAI_API_KEY"):
    try:
        cloud_api_key = st.secrets["OPENAI_API_KEY"]
    except (KeyError, StreamlitSecretNotFoundError):
        cloud_api_key = ""
    if cloud_api_key:
        os.environ["OPENAI_API_KEY"] = str(cloud_api_key)
st.set_page_config(page_title="GoTruck Studio", page_icon="🚚", layout="wide")
st.session_state.setdefault("app_page", "landing")
brand_col, nav_col = st.columns([5, 1], vertical_alignment="center", wrap=True)
with brand_col:
    brand_title = "고트럭 마케팅 콘텐츠 생성기" if st.session_state["app_page"] == "studio" else "GoTruck Content Studio"
    brand_subtitle = "CONTENT STUDIO" if st.session_state["app_page"] == "studio" else "MARKETING WORKSPACE"
    st.markdown(f'<div style="display:flex;align-items:center;gap:10px;margin:4px 0 12px"><span style="display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:10px;background:#f07824;color:white;font-size:21px;font-weight:800;flex:none">G</span><span style="min-width:0"><b>{brand_title}</b><br><small style="letter-spacing:1.5px;color:#8b7769">{brand_subtitle}</small></span></div>', unsafe_allow_html=True)
with nav_col:
    page_action = "콘텐츠 제작하기" if st.session_state["app_page"] == "landing" else "소개 페이지"
    if st.button(page_action, key="app_page_toggle", type="primary" if st.session_state["app_page"] == "landing" else "secondary", width="stretch"):
        st.session_state["app_page"] = "studio" if st.session_state["app_page"] == "landing" else "landing"
        st.rerun()

OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "key_message": {"type": "string"}, "planning_note": {"type": "string"},
        "kakao_copy": {"type": "string"}, "article_copy": {"type": "string"}, "leaflet_copy": {"type": "string"},
        "visuals": {"type": "object", "additionalProperties": False,
            "properties": {name: {"type": "object", "additionalProperties": False,
                "properties": {field: {"type": "string"} for field in ["concept", "composition", "visual_elements", "palette_mood", "image_prompt"]},
                "required": ["concept", "composition", "visual_elements", "palette_mood", "image_prompt"]}
                for name in ["kakao", "article", "leaflet"]},
            "required": ["kakao", "article", "leaflet"]},
        "review_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["key_message", "planning_note", "kakao_copy", "article_copy", "leaflet_copy", "visuals", "review_notes"],
}

CHANNEL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "copy": {"type": "string"},
        "visual": {"type": "object", "additionalProperties": False,
            "properties": {field: {"type": "string"} for field in ["concept", "composition", "visual_elements", "palette_mood", "image_prompt"]},
            "required": ["concept", "composition", "visual_elements", "palette_mood", "image_prompt"]},
        "review_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["copy", "visual", "review_notes"],
}

KAKAO_VARIATIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "variations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["variations"],
}

SYSTEM_PROMPT = """당신은 상용차·운송 분야의 마케팅 콘텐츠 기획자입니다. 입력된 확인 사실만 사용해 카카오 브랜드톡, 기획/보도기사, 지류 리플렛 카피를 작성하세요. 이미지 기획은 카카오 브랜드톡과 지류 리플렛에만 제안하고, 기사 유형에서는 이미지 브리프를 만들지 않습니다.

광고 표현 사전 점검 참고 원칙(사용자가 제공한 2023.11 광고심의 업무매뉴얼에서 일반적으로 적용 가능한 검토 신호를 요약):
- 객관적 근거 없는 최상급·최초·유일·1위 및 무조건·무제한·누구나 같은 보편·확정 표현, 입증되지 않은 비교우위 표현을 피하고, 필요한 경우 담당자 검토 메모에 근거 확인 필요를 남기세요.
- 혜택·수치·기간·대상·조건은 서로 맞게 쓰고 중요한 제한조건을 감추거나 작게 취급하지 마세요. 통계·수상·비교 표현은 출처·기준·시점을 확인해야 합니다.
- 이 매뉴얼은 여신전문금융회사 및 금융상품 광고 중심의 참고자료입니다. 일반 물류·서비스 광고에 금융상품 전용 의무고지사항이나 심의 범위를 그대로 적용하지 말고, 금융상품 또는 대출을 다루는 경우에만 별도 적용성 검토를 요청하세요.

반드시 지킬 것:
- 입력에 없는 수치, 가격, 혜택, 성과, 서비스 조건, URL, 연락처, 고객 후기, 회사 사실을 만들지 마세요. 모르는 내용은 [확인 필요]로 남기세요.
- 필수 문구는 자연스럽게 포함하고, 금칙 표현은 문안과 이미지 지시문에 쓰지 마세요.
- 참고 레퍼런스는 말투와 구성만 참고하고 사실 근거로 사용하지 마세요.
- 카카오/리플렛 이미지 시안은 디자이너용 콘셉트, 구도, 요소, 색감, 제작 프롬프트입니다. 카피는 편집 가능한 별도 텍스트로 분리하고 로고는 생성하지 마세요.
- 브랜드톡은 간결한 메시지와 CTA를 작성하세요. 리플렛은 선택된 규격·접지에 맞춰 실제 인쇄물에 바로 배치 가능한 면별 원고로 작성하세요. 각 면을 '[앞면]' '[뒷면]'으로 나누고, 앞면에는 헤드라인·서브카피·대표 혜택·CTA, 뒷면에는 상세 혜택·이용 방법·필수 안내·URL/QR 위치를 반영하세요. 3단 접지는 '[바깥면]'과 '[안쪽면]'을 각각 좌/중/우 패널로 나눠 제목과 짧은 문구를 구성하고, 표지·접지 순서를 고려하세요. 안내 문구를 반복하거나 긴 단락으로 채우지 말고, 각 패널에 하나의 메시지만 두세요. 입력에 없는 사실이나 URL은 만들지 말고, 필요한 정보는 [확인 필요]로 표시하세요. 기사는 고객이 읽기 쉬운 브랜드 기사로 작성하고, 반드시 '헤드카피:', '서브카피:', '본문:' 라벨로 구분하세요. 헤드카피는 고객의 필요나 핵심 효용을 선명하게 제시하고, 서브카피는 기사 내용을 보완하며, 본문은 고객 상황-서비스 설명-이용 안내 순으로 자연스럽게 전개하세요. 광고성 과장이나 입력에 없는 사실은 쓰지 마세요. 매체·기사 유형·관점·배포 조건 등 사전 기획 요건을 반영하세요. 기사 유형의 visuals 필드는 빈 문자열로 두세요.
- 지정 글자 수에 맞추고, JSON 스키마에 맞는 결과만 제공하세요.
- 광고 규정 준수 여부를 확정하거나 준법심의를 대체하지 마세요. 확인할 표현은 검토 메모에 남기세요.
"""

CHANNELS = {
    "카카오 브랜드톡": {"key": "kakao", "copy_key": "copy_kakao", "visual_key": "visual_kakao", "copy_field": "kakao_copy"},
    "지류 리플렛": {"key": "leaflet", "copy_key": "copy_leaflet", "visual_key": "visual_leaflet", "copy_field": "leaflet_copy"},
    "기획·보도기사": {"key": "article", "copy_key": "copy_article", "visual_key": "visual_article", "copy_field": "article_copy"},
}

DEFAULT_CHANNEL_SPECS = {
    "kakao": {"message_goal": "혜택 안내 및 이용 유도", "max_characters": 350, "cta": "자세히 알아보기", "url": "", "required_phrases": "", "image_count": 3, "image_style": "현장감 있는 실사"},
    "article": {"article_type": "서비스 소개", "article_purpose": "서비스 인지도", "editorial_angle": "타깃 고객에게 유용한 정보 중심", "target_media": "운송·물류 전문 매체", "max_characters": 1800, "release_date": "", "embargo_note": "", "quote": "", "keywords": "", "fact_check": "", "required_phrases": ""},
    "leaflet": {"format": "A4 양면", "max_characters": 1800, "audience_focus": "핵심 타깃 고객", "url": "", "required_phrases": "", "production_note": ""},
}

DEMO_INPUTS = {
    "service_name": "고트럭 플러스 (데모)",
    "service_description": "화물차 운전자가 운행 관련 정보를 확인하고 필요한 서비스를 찾아볼 수 있도록 돕는 모바일 서비스 콘셉트입니다. 아래 문구와 기능 설명은 화면 확인을 위한 가상 샘플입니다.",
    "verified_benefits": ["운행 관련 정보를 한 곳에서 확인", "필요한 서비스와 이용 정보를 간편하게 탐색", "이동 중에도 보기 쉬운 정보 구성"],
    "target": "운행·차량 관리 정보를 빠르게 확인하고 싶은 화물차 운전자",
    "campaign_objective": "핵심 혜택 이해시키기",
    "customer_need": "운행 중 필요한 정보를 여러 경로에서 찾아야 하는 번거로움",
    "tone": "신뢰감 있는 정보형",
    "forbidden_phrases": ["무조건", "업계 최초"],
    "common_verified_context_and_reference": "데모 데이터입니다. 실제 제공 기능, 이용 조건 및 성과로 간주하지 마세요.",
    "revision_direction": "",
    "channel_specs": json.loads(json.dumps(DEFAULT_CHANNEL_SPECS)),
}

DEMO_RESULT = {
    "key_message": "운행에 필요한 정보를 더 편하게 확인하는 방법, 고트럭 플러스 (데모)",
    "planning_note": "운전자 관점의 정보 탐색 부담을 출발점으로 삼고, 확인된 샘플 혜택을 채널별 읽기 흐름에 맞춰 전달합니다. 실제 기능·조건 확인이 필요합니다.",
    "kakao_copy": "[고트럭 플러스 데모]\n운행에 필요한 정보, 여기저기 찾느라 번거로우셨나요?\n운행 관련 정보와 필요한 서비스를 한 곳에서 살펴보세요.\n\n고트럭 플러스에서 확인해 보세요.",
    "article_copy": "헤드카피: 운행에 필요한 정보, 한곳에서 살펴보세요\n서브카피: 고트럭 플러스(데모)로 운행 정보와 서비스 이용 정보를 확인하는 방법\n본문:\n운행 중 필요한 정보를 찾기 위해 여러 경로를 살펴보는 일은 화물차 운전자에게 번거로울 수 있습니다. 고트럭 플러스(데모)는 운행 관련 정보와 서비스 이용 정보를 한 화면에서 확인할 수 있도록 구성한 모바일 서비스 콘셉트입니다.\n\n운전자에게 필요한 정보를 살펴보고, 이용 가능한 서비스와 절차를 확인하는 흐름을 제안합니다. 실제 지원 기능과 제공 조건은 출시 자료를 통해 확인해야 합니다.\n\n※ 데모용 가상 기사 초안이며 실제 사실이나 보도자료가 아닙니다.",
    "leaflet_copy": "[앞면]\n고트럭 플러스 (데모)\n운행에 필요한 정보를 한 곳에서\n운행 중 필요한 내용을 더 쉽게 찾아볼 수 있도록 돕는 모바일 서비스 콘셉트입니다.\n\n대표 혜택\n• 운행 관련 정보를 한 곳에서 확인\n\nCTA: 자세히 알아보기\n\n[뒷면]\n주요 혜택\n• 필요한 서비스와 이용 정보를 간편하게 탐색\n• 이동 중에도 보기 쉬운 정보 구성\n\n이용 방법\n서비스 화면에서 관심 있는 정보와 서비스를 살펴보세요.\n\nQR·URL: [확인 필요]\n※ 데모용 가상 문구입니다. 실제 제공 기능과 조건을 확인한 뒤 사용하세요.",
    "visuals": {
        "kakao": {"concept": "운전자에게 필요한 정보를 빠르게 찾는 순간", "composition": "800×600px 와이드 이미지형 4:3 가로 구도. 화물차와 정보 탐색 장면을 한눈에 보이게 배치", "visual_elements": "안전하게 정차한 화물차, 운행 경로를 암시하는 선 그래픽, 문구 배치를 위한 여백", "palette_mood": "밝고 신뢰감 있는 GoTruck 오렌지와 웜 화이트, 깔끔하고 실용적인 분위기", "image_prompt": "800×600px 와이드 이미지형 4:3 가로 구도. 화물차 운전자가 안전하게 정차한 상태에서 운행 정보를 확인하는 순간을 가로로 구성한다. GoTruck 오렌지와 웜 화이트, 이미지 내 문자와 로고 생성 금지. 카피를 얹을 여백을 확보한다."},
        "article": {"concept": "운행 정보 탐색 경험을 보여주는 에디토리얼 히어로", "composition": "넓은 도로와 화물차를 배경으로 한 여백 중심 가로 구도, 한쪽에 UI 목업 배치", "visual_elements": "주행 경로를 나타내는 얇은 선, 차량 실루엣, 검증 후 삽입할 서비스 화면", "palette_mood": "차분한 블루·네이비와 자연광, 정보 기사에 어울리는 현실감", "image_prompt": "가로형 에디토리얼 이미지. 넓은 도로 위 화물차와 정차 공간, 주변에 절제된 경로 그래픽을 더한다. 기사 헤드라인용 여백을 확보하고 로고·텍스트는 생성하지 않는다. 실제 서비스 UI는 제공된 화면으로 교체."},
        "leaflet": {"concept": "서비스 사용 흐름과 핵심 정보를 한눈에 보여주는 안내물", "composition": "상단 헤드라인, 중앙 모바일 화면 목업, 하단 3개 혜택과 QR 자리의 A4 양면 구성", "visual_elements": "모바일 화면, 혜택 아이콘 3개, 이용 안내 영역, 검증된 링크 연결용 QR 자리", "palette_mood": "명확한 위계의 블루·화이트, 현장에서 읽기 쉬운 대비", "image_prompt": "A4 양면 리플렛 시안. 앞면은 서비스명과 핵심 메시지, 검증된 화면 목업을 중심에 두고 뒷면은 혜택·이용 안내·문의 정보를 카드형으로 정리한다. QR 코드는 빈 자리 표시만 하고 실제 링크는 제작 단계에서 삽입. 로고와 문자는 생성하지 않는다."},
    },
    "review_notes": ["데모용으로 만든 가상 콘텐츠입니다.", "실제 서비스 기능, 이용 조건, 화면, URL을 확인한 뒤 모든 문구를 교체해야 합니다."],
}


def visual_brief(visual: dict) -> str:
    return "\n".join([
        f"콘셉트: {visual['concept']}", f"구도: {visual['composition']}",
        f"주요 요소: {visual['visual_elements']}", f"색감·무드: {visual['palette_mood']}",
        f"\n이미지 제작 프롬프트(시안):\n{visual['image_prompt']}",
    ])


def make_demo_png(variation: int) -> bytes:
    """Render an unbranded local demo visual at the Kakao 4:3 output size."""
    palettes = [((255, 245, 235), (246, 123, 35), (43, 58, 70)), ((255, 228, 205), (222, 83, 20), (255, 255, 255)), ((70, 47, 39), (255, 141, 50), (249, 231, 208))]
    background, orange, ink = palettes[variation % len(palettes)]
    image = Image.new("RGB", (800, 600), background)
    draw = ImageDraw.Draw(image)
    if variation == 0:
        draw.ellipse((560, -95, 900, 245), fill=(255, 216, 185))
        draw.polygon([(0, 410), (800, 330), (800, 600), (0, 600)], fill=(235, 230, 223))
        draw.line((0, 520, 800, 440), fill=orange, width=12)
    elif variation == 1:
        draw.rectangle((0, 360, 800, 600), fill=(42, 49, 57))
        draw.ellipse((545, 30, 740, 225), fill=(255, 188, 113))
        draw.polygon([(0, 430), (800, 340), (800, 600), (0, 600)], fill=(59, 65, 72))
        draw.line((0, 526, 800, 436), fill=orange, width=14)
    else:
        draw.ellipse((555, 40, 785, 270), fill=orange)
        draw.rounded_rectangle((45, 48, 430, 312), radius=28, fill=(255, 255, 255))
        draw.rounded_rectangle((80, 86, 260, 275), radius=22, fill=(242, 245, 247), outline=orange, width=7)
        draw.polygon([(0, 440), (800, 350), (800, 600), (0, 600)], fill=(224, 229, 231))
    # Simple unbranded truck silhouette, intentionally without copy or logo.
    x = [205, 485, 485, 568, 635, 660, 660, 205]
    y = [342, 342, 410, 410, 438, 468, 510, 510]
    draw.polygon(list(zip(x, y)), fill=ink)
    draw.polygon([(501, 356), (552, 356), (552, 396), (501, 396)], fill=(208, 222, 227))
    draw.ellipse((260, 478, 322, 540), fill=(27, 32, 37))
    draw.ellipse((544, 478, 606, 540), fill=(27, 32, 37))
    draw.ellipse((278, 496, 304, 522), fill=(230, 235, 238))
    draw.ellipse((562, 496, 588, 522), fill=(230, 235, 238))
    draw.rounded_rectangle((55, 44, 175, 56), radius=6, fill=orange)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def generate_kakao_images(specs: dict, inputs: dict, copy: str, visual: dict) -> list[bytes]:
    prompt = f"""Create a wide landscape 4:3 Kakao BrandTalk campaign image, final canvas 800 x 600 pixels. Generate a polished advertising visual that can be paired with editable Korean message copy.
Brand palette: GoTruck warm orange (#F07824), warm white and charcoal. Do not use blue as the dominant brand color.
Art direction: {specs.get('image_style', 'warm, realistic commercial photography')}.
Visual concept: {visual.get('concept', '')}. Composition: {visual.get('composition', '')}. Elements: {visual.get('visual_elements', '')}.
Mood: {visual.get('palette_mood', '')}. Source visual brief: {visual.get('image_prompt', '')}.
Campaign copy context (for visual meaning only, do not render any text): {copy[:900]}.
Audience: {inputs.get('target', '')}. Create a distinct wide visual for this specific copy variation, with a clear focal point, a balanced 4:3 composition and uncluttered negative space for the message alongside the image. Show believable Korean commercial-vehicle context and no unsafe driving.
Strictly no words, letters, numbers, captions, signs, watermarks, logos, or fake phone UI text. Do not invent a GoTruck logo. Return the image only."""
    response = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=180, max_retries=1).images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        n=1,
        size="1536x1024",
        quality="medium",
        output_format="png",
    )
    return [normalize_kakao_png(base64.b64decode(image.b64_json)) for image in response.data or []]


def normalize_kakao_png(image_data: bytes) -> bytes:
    """Center-crop a landscape model image to 4:3 and export exactly 800×600 PNG."""
    image = Image.open(BytesIO(image_data)).convert("RGB")
    width, height = image.size
    target_ratio = 4 / 3
    if width / height > target_ratio:
        cropped_width = round(height * target_ratio)
        left = (width - cropped_width) // 2
        image = image.crop((left, 0, left + cropped_width, height))
    else:
        cropped_height = round(width / target_ratio)
        top = (height - cropped_height) // 2
        image = image.crop((0, top, width, top + cropped_height))
    image = image.resize((800, 600), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def generate_kakao_copy_variations(source_copy: str, inputs: dict, specs: dict) -> list[str]:
    prompt_data = {
        "source_copy": source_copy,
        "service_facts": inputs,
        "channel_requirements": specs,
    }
    response = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90, max_retries=1).responses.create(
        model=MODEL, reasoning={"effort": "low"}, max_output_tokens=1800,
        input=[
            {"role": "system", "content": "카카오 브랜드톡 카피라이터입니다. 입력된 확인 사실만 사용해 서로 다른 전략의 카피 Variation을 정확히 3개 작성하세요. 각 카피는 메시지 목적, 타깃, CTA, 필수 문구와 글자 수 요건을 반영하고 금칙 표현 및 가상 문구 안내는 카피 본문에 넣지 마세요. 각각 독립적으로 바로 사용할 수 있게 쓰세요."},
            {"role": "user", "content": json.dumps(prompt_data, ensure_ascii=False, indent=2)},
        ],
        text={"format": {"type": "json_schema", "name": "gotruck_kakao_copy_variations", "strict": True, "schema": KAKAO_VARIATIONS_SCHEMA}},
    )
    variations = json.loads(response.output_text).get("variations", [])
    variations = [str(item).strip() for item in variations if str(item).strip()]
    if len(variations) != 3:
        raise ValueError("카피 Variation 3종을 생성하지 못했습니다.")
    return variations

def show_landing_page() -> None:
    st.markdown("""
    <style>
    .stApp{background:#fffaf6}
    .gt-landing{max-width:1180px;margin:0 auto;color:#253548;word-break:keep-all;overflow-wrap:break-word}
    .gt-landing-hero{display:grid;grid-template-columns:1fr;align-items:center;padding:76px 56px 68px;border-radius:22px;background:linear-gradient(120deg,#fff 0%,#fff7f0 58%,#ffeadb 100%);border:1px solid #f3e1d3;position:relative;overflow:hidden}.gt-landing-hero>div{max-width:790px;position:relative;z-index:1}
    .gt-overline{font-size:12px;font-weight:800;letter-spacing:2px;color:#e66d1f}.gt-landing-hero h1{font-size:clamp(38px,5.3vw,64px);line-height:1.18;letter-spacing:-2.8px;margin:18px 0 20px;color:#20344b;word-break:keep-all;overflow-wrap:normal}.gt-landing-hero p{max-width:600px;color:#6f7d8b;font-size:17px;line-height:1.85;margin:0}
    .gt-metrics{display:grid;grid-template-columns:repeat(3,1fr);background:#fff;border-block:1px solid #e9e6e2;margin:0 0 62px}.gt-metric{padding:22px 25px;border-right:1px solid #e9e6e2}.gt-metric:last-child{border-right:0}.gt-metric strong{display:block;font-size:16px;color:#2a3d52}.gt-metric span{display:block;margin-top:6px;color:#74818d;font-size:13px}
    .gt-section{padding:0 18px 64px}.gt-section-head{display:flex;justify-content:space-between;align-items:end;gap:25px;margin-bottom:26px}.gt-section-head h2{font-size:30px;line-height:1.35;letter-spacing:-1.1px;margin:0;color:#24384e;word-break:keep-all;overflow-wrap:normal;max-width:430px}.gt-section-head p{max-width:410px;color:#707d89;font-size:15px;line-height:1.8;margin:0}.gt-features{display:grid;grid-template-columns:repeat(3,1fr);border-top:2px solid #33465a}.gt-feature{padding:20px 22px 0 0;min-height:122px}.gt-feature+.gt-feature{padding-left:22px;border-left:1px solid #e7e8e8}.gt-feature b{font-size:16px;color:#2b3e52}.gt-feature p{font-size:14px;line-height:1.8;color:#707d89;margin:9px 0 0}
    .gt-output-band{background:#20364d;color:white;padding:45px 30px;border-radius:18px;margin-bottom:28px}.gt-output-band .gt-section-head h2{color:#fff}.gt-output-band .gt-section-head p{color:#d0d9e1}.gt-output-list{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid #607184}.gt-output{padding:17px 14px 4px 0;display:flex;align-items:start;gap:12px}.gt-output+.gt-output{padding-left:18px;border-left:1px solid #607184}.gt-output-num{color:#f5a76e;font-size:12px;font-weight:800}.gt-output b{font-size:15px;color:#fff}.gt-output small{display:block;color:#d0d9e1;font-size:13px;margin-top:6px}
    .gt-landing-footer{color:#7d8994;font-size:12px;padding:8px 18px 25px;display:flex;justify-content:space-between;gap:8px 20px;flex-wrap:wrap;line-height:1.7}
    @media(max-width:820px){.gt-landing-hero{padding:52px 32px}.gt-section-head{display:block}.gt-section-head p{margin-top:12px}.gt-output-band{padding:34px 22px}}
    @media(max-width:600px){.gt-landing-hero{padding:32px 20px}.gt-landing-hero h1{font-size:39px;letter-spacing:-1.8px}.gt-landing-hero p{font-size:14px}.gt-metrics,.gt-features,.gt-output-list{grid-template-columns:1fr}.gt-metric,.gt-metric:last-child{padding:15px 4px;border-right:0;border-bottom:1px solid #e9e6e2}.gt-metric:last-child{border-bottom:0}.gt-section{padding:0 7px 42px}.gt-section-head h2{font-size:25px}.gt-feature,.gt-feature+.gt-feature{padding:16px 0;border-left:0;border-bottom:1px solid #e7e8e8;min-height:auto}.gt-output+.gt-output{padding-left:0;border-left:0;border-top:1px solid #607184}.gt-landing-footer{display:block;padding-inline:7px}.gt-landing-footer span{display:block;margin:4px 0}}
    </style>
    <main class="gt-landing">
      <section class="gt-landing-hero">
        <div><div class="gt-overline">●　CONTENT, SIMPLIFIED</div><h1>한 번의 기획으로<br>세 가지 콘텐츠를.</h1><p>서비스 정보와 타깃을 입력하면 채널별 홍보 카피와 이미지 제작안을 제안합니다.</p></div>
      </section>
      <section class="gt-metrics"><div class="gt-metric"><strong>핵심 정보 입력</strong><span>서비스 · 소구점 · 타깃 · 톤앤매너</span></div><div class="gt-metric"><strong>채널별 초안 생성</strong><span>목적과 규격을 반영한 카피</span></div><div class="gt-metric"><strong>검토 후 바로 활용</strong><span>편집·미리보기·파일 다운로드</span></div></section>
      <section class="gt-section"><div class="gt-section-head"><h2>필요한 기능만<br>분명하게.</h2><p>초안을 직접 편집하고 채널별 형식으로 검토하세요. 처음부터 작성하는 부담을 덜고 전달할 메시지를 선명하게 다듬을 수 있습니다.</p></div><div class="gt-features"><article class="gt-feature"><b>맞춤형 조건 반영</b><p>타깃, 톤앤매너, 글자 수, 필수 문구와 참고자료를 반영합니다.</p></article><article class="gt-feature"><b>하나의 소재, 여러 형식</b><p>카카오 브랜드톡, 지류 리플렛, 기획·보도기사로 메시지를 확장합니다.</p></article><article class="gt-feature"><b>표현 점검 보조</b><p>필수·금칙 표현을 살피고 사실 확인이 필요한 부분을 표시합니다.</p></article></div></section>
      <section class="gt-output-band"><div class="gt-section-head"><h2>세 가지 채널에<br>맞춰 활용하세요.</h2><p>하나의 서비스 소재를 매체별 형식에 맞게 정리합니다. 이미지가 필요한 콘텐츠는 디자이너용 시안도 함께 확인할 수 있습니다.</p></div><div class="gt-output-list"><div class="gt-output"><span class="gt-output-num">01</span><div><b>카카오 브랜드톡</b><small>카피 Variation + 와이드 이미지 PNG</small></div></div><div class="gt-output"><span class="gt-output-num">02</span><div><b>지류 리플렛</b><small>인쇄 카피 + 이미지 제작 브리프</small></div></div><div class="gt-output"><span class="gt-output-num">03</span><div><b>기획·보도기사</b><small>헤드카피 · 서브카피 · 본문</small></div></div></div></section>
      <div class="gt-landing-footer"><span>GoTruck Content Studio</span><span>기획·검토용 초안 · 최종 사실관계와 광고 규정은 담당자가 확인하세요.</span></div>
    </main>
    """, unsafe_allow_html=True)
    start_cols = st.columns([1, 2, 1], gap="small", vertical_alignment="center", wrap=True)
    with start_cols[1]:
        if st.button("콘텐츠 제작 시작하기　→", key="landing_start", type="primary", width="stretch"):
            st.session_state["app_page"] = "studio"
            st.rerun()


if st.session_state["app_page"] == "landing":
    show_landing_page()
    st.stop()

st.markdown("""
<style>
.studio-hero{background:linear-gradient(112deg,#9a3412,#f07824 72%,#fb923c);color:#fff;border-radius:18px;padding:32px 36px;margin:8px 0 22px;position:relative;overflow:hidden}
.studio-hero:after{content:"";position:absolute;right:5%;top:-90px;width:270px;height:270px;border:1px solid #ffffff35;border-radius:50%;box-shadow:0 0 0 28px #ffffff0b,0 0 0 62px #ffffff08}
.studio-kicker{font-size:11px;letter-spacing:3px;font-weight:700;color:#ffedd5;margin-bottom:16px}.studio-title{font-size:32px;line-height:1.25;margin:0 0 10px;color:#fff}.studio-subtitle{font-size:14px;color:#fff1e8;margin:0}.studio-steps{position:absolute;right:28px;bottom:22px;color:#fff1e8;font-size:12px;z-index:1}
.mockup{border:1px solid #f1e4db;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 8px 24px #5a321517;margin:4px 0 10px}.mockup-visual{padding:18px 20px;background:linear-gradient(140deg,#bd4d16,#f07824);color:#fff;min-height:165px;display:flex;flex-direction:column;justify-content:flex-end}.mockup-visual .eyebrow{font-size:9px;letter-spacing:2px;font-weight:700;opacity:.75;margin-bottom:11px}.mockup-visual h3{font-size:22px;line-height:1.3;margin:0 0 8px;color:#fff}.mockup-visual p{font-size:12px;margin:0;color:#fff1e8}.mockup-body{padding:16px 20px;color:#334155;font-size:12px;line-height:1.65}.mockup-label{font-size:9px;letter-spacing:1.6px;color:#d56614;font-weight:800;margin-bottom:9px}.mockup-cta{display:block;text-align:center;background:#e76512;border-radius:7px;padding:9px;color:#fff;font-weight:700;margin-top:12px}.mockup-benefit{border-bottom:1px solid #f1e4db;padding:6px 0}.visual-tag{display:inline-block;background:#fff0e4;color:#b8470d;border-radius:20px;padding:4px 9px;font-size:10px;font-weight:700;margin-bottom:10px}
.stTabs [data-baseweb="tab-list"]{gap:8px;border-bottom:2px solid #ffdec4;padding-bottom:7px}
.stTabs [data-baseweb="tab"]{min-height:52px;padding:0 20px;border:1px solid #f1d7c2;border-radius:12px 12px 0 0;background:#fff8f2;color:#744521;font-size:15px;font-weight:800}
.stTabs [data-baseweb="tab"] *{color:inherit!important}
.stTabs [data-baseweb="tab"][aria-selected="true"],.stTabs [role="tab"][aria-selected="true"]{background:#f07824!important;border-color:#f07824!important;color:#fff!important;box-shadow:0 5px 14px #f0782433}
.stTabs [data-baseweb="tab-highlight"]{background-color:#f07824!important;height:0!important}
.sim-panel{border:1px solid #f1d7c2;background:#fffaf6;border-radius:12px;padding:12px 14px;margin:8px 0 14px}
.image-card{border:1px solid #f1e4db;border-radius:12px;padding:10px;background:#fff}
.kakao-composite{border:1px solid #eadfd8;border-top:0;border-radius:0 0 12px 12px;background:#fff;padding:18px 20px;color:#273444;font-size:14px;line-height:1.7;white-space:normal;box-shadow:0 8px 24px #5a321510}
.kakao-composite-copy{white-space:normal;overflow-wrap:anywhere}.kakao-composite-cta{display:block;margin-top:16px;border-radius:8px;background:#f07824;color:#fff;text-align:center;font-weight:800;padding:11px 14px}
.article-draft{border:1px solid #ece3dc;background:#fff;border-radius:12px;padding:22px 24px;color:#293847;line-height:1.8;box-shadow:0 5px 18px #5a32150d}.article-draft-kicker{font-size:10px;letter-spacing:1.5px;color:#d56614;font-weight:800}.article-draft h2{font-size:23px;line-height:1.45;margin:10px 0 12px;color:#263546}.article-draft-subhead{font-size:14px;font-weight:650;color:#73533f;border-left:3px solid #f07824;padding-left:13px;margin:0 0 17px}.article-draft-body{font-size:13px;white-space:pre-line}.article-plan{border:1px solid #f1d7c2;background:#fffaf6;border-radius:12px;padding:12px 15px;margin-top:14px;font-size:12px;color:#66584f}.article-plan b{color:#a34712}
.leaflet-preview-wrap{padding:15px;border:1px solid #eadfd6;border-radius:14px;background:#f5f1ed}.leaflet-preview-heading{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:12px;color:#344355;font-size:12px}.leaflet-preview-heading span{color:#9b765f;font-size:10px}.leaflet-spread{display:grid;grid-template-columns:1fr 1fr;gap:10px;max-width:680px;margin:auto}.leaflet-sheet{position:relative;aspect-ratio:0.707;background:#fff;padding:22px 19px;box-shadow:0 5px 16px #3b2c201a;border:1px solid #e8e1da;overflow:hidden;color:#293847}.leaflet-sheet-label{position:absolute;top:7px;right:8px;color:#a4a4a4;font-size:8px}.leaflet-front{display:flex;flex-direction:column;background:linear-gradient(160deg,#fff 0%,#fff8f2 100%)}.leaflet-brandline{font-size:8px;font-weight:800;color:#cf5a13;letter-spacing:1px;border-bottom:1px solid #f0ddd0;padding:7px 0}.leaflet-cover-copy{margin:auto 0}.leaflet-cover-copy span,.leaflet-back-section small,.leaflet-feature small,.leaflet-back-bottom small{font-size:8px;font-weight:800;letter-spacing:1.1px;color:#df6e27}.leaflet-cover-copy h3{font-size:clamp(14px,2vw,22px);line-height:1.45;margin:9px 0;color:#25364a;word-break:keep-all}.leaflet-cover-copy p{font-size:10px;line-height:1.7;color:#667381}.leaflet-feature{padding:10px;border-left:3px solid #f07824;background:#fff;margin-bottom:10px}.leaflet-feature b{display:block;font-size:10px;line-height:1.5;margin-top:4px}.leaflet-front-cta{background:#f07824;color:#fff;text-align:center;padding:8px;border-radius:4px;font-size:9px;font-weight:800}.leaflet-back{display:flex;flex-direction:column;gap:13px}.leaflet-back-section h4{margin:4px 0;font-size:13px;color:#293847}.leaflet-back-section p,.leaflet-back-section li{font-size:9px;line-height:1.65;color:#607080}.leaflet-back-section ul{padding-left:15px;margin:5px 0}.leaflet-back-bottom{display:flex;align-items:center;justify-content:space-between;border-top:1px solid #eee4db;padding-top:10px;margin-top:auto}.leaflet-back-bottom p{font-size:8px;color:#5f6a76;margin:5px 0;overflow-wrap:anywhere}.leaflet-qr{width:38px;height:38px;border:1px dashed #f07824;color:#d56614;display:grid;place-items:center;font-size:8px;flex:none}.leaflet-print-note{font-size:9px;line-height:1.55;color:#8c8179;margin-top:9px}.leaflet-trifold{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;max-width:700px;margin:auto;box-shadow:0 5px 16px #3b2c201a}.leaflet-panel{aspect-ratio:0.72;background:#fff;border:1px dashed #d9c8b9;padding:12px 9px;display:flex;flex-direction:column;justify-content:center;min-width:0}.leaflet-panel:nth-child(3),.leaflet-panel:nth-child(4){background:#fff5ec}.leaflet-panel small{font-size:7px;color:#9a8879;line-height:1.4}.leaflet-panel-tag{font-size:7px;letter-spacing:1px;font-weight:800;color:#df6e27;margin-top:auto}.leaflet-panel b{font-size:clamp(10px,1.4vw,15px);line-height:1.5;color:#293847;margin:8px 0;word-break:keep-all}.leaflet-panel p{font-size:8px;line-height:1.6;color:#667381;margin:0 auto auto;word-break:keep-all}
@media(max-width:1000px){.studio-hero{padding:24px 21px}.studio-title{font-size:27px}.studio-steps{position:relative;right:auto;bottom:auto;margin-top:18px}.studio-hero:after{right:-150px}.mockup-visual{min-height:140px}}
@media(max-width:600px){.leaflet-preview-wrap{padding:9px}.leaflet-spread{gap:6px}.leaflet-sheet{padding:20px 12px 12px}.leaflet-back{gap:8px}.leaflet-preview-heading{align-items:flex-start;flex-direction:column}.leaflet-panel{padding:8px 5px}.leaflet-panel small{font-size:6px}.leaflet-panel p{font-size:7px}}
</style>
<div class="studio-hero"><div class="studio-kicker">GOTRUCK CONTENT STUDIO</div><h1 class="studio-title">고트럭 마케팅 콘텐츠 생성기</h1><p class="studio-subtitle">서비스 정보를 바탕으로 채널별 카피와 이미지 시안을 만듭니다.</p><div class="studio-steps">01 정보 입력　→　02 콘텐츠 생성　→　03 검토·활용</div></div>
""", unsafe_allow_html=True)

left_col, right_col = st.columns([4, 8], gap="large", vertical_alignment="top", wrap=True)
with left_col:
    with st.container(border=True):
        st.caption("01 / INPUT")
        title_col, reset_col = st.columns([4, 1], vertical_alignment="bottom")
        with title_col:
            st.subheader("마케팅 기획 정보")
        with reset_col:
            reset_clicked = st.button("초기화", key="reset_form")
        if reset_clicked:
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        if st.button("▣  데모 데이터 불러오기", width="stretch", key="load_demo"):
            for form_key, value in {
                "service": DEMO_INPUTS["service_name"],
                "description": DEMO_INPUTS["service_description"],
                "benefits": "\n".join(DEMO_INPUTS["verified_benefits"]),
                "target": DEMO_INPUTS["target"],
                "objective": DEMO_INPUTS["campaign_objective"],
                "customer_need": DEMO_INPUTS["customer_need"],
                "tone": DEMO_INPUTS["tone"],
                "forbidden_phrases": ", ".join(DEMO_INPUTS["forbidden_phrases"]),
                "references": DEMO_INPUTS["common_verified_context_and_reference"],
                "confirmed": True,
                "revision_direction": "",
            }.items():
                st.session_state[form_key] = value
            for widget_key in [
                "sim_kakao_goal", "sim_kakao_goal_custom", "sim_kakao_limit", "sim_kakao_cta", "sim_kakao_url", "sim_kakao_required", "sim_kakao_image_count", "sim_kakao_image_style",
                "sim_article_type", "sim_article_purpose", "sim_article_angle", "sim_article_limit", "sim_article_date", "sim_article_quote", "sim_article_required", "sim_article_media", "sim_article_embargo", "sim_article_keywords", "sim_article_fact_check",
                "sim_leaflet_format", "sim_leaflet_limit", "sim_leaflet_audience", "sim_leaflet_url", "sim_leaflet_required", "sim_leaflet_note",
            ]:
                st.session_state.pop(widget_key, None)
            demo_inputs = json.loads(json.dumps(DEMO_INPUTS))
            st.session_state["generated_inputs"] = demo_inputs
            st.session_state["generated_result"] = json.loads(json.dumps(DEMO_RESULT))
            st.session_state["model_name"] = "DEMO · 샘플 데이터"
            st.session_state["demo_mode"] = True
            st.session_state.pop("kakao_copy_variations", None)
            st.session_state.pop("kakao_image_variations", None)
            st.session_state.pop("kakao_images_demo", None)
            for channel in CHANNELS.values():
                st.session_state[channel["copy_key"]] = DEMO_RESULT[channel["copy_field"]]
                st.session_state[channel["visual_key"]] = visual_brief(DEMO_RESULT["visuals"][channel["key"]])
            st.toast("더미 기획 정보와 3종 샘플 결과를 불러왔습니다.", icon=":material/visibility:")
        st.caption("샘플 데이터를 불러오면 API 키 없이 결과 탭과 매체별 시뮬레이션을 확인할 수 있습니다.")
        service = st.text_input("서비스명 *", placeholder="예: 고트럭 플러스", key="service")
        description = st.text_area("서비스 소개", placeholder="서비스의 주요 내용과 제공 조건을 입력해 주세요.", height=82, key="description")
        benefits = st.text_area("핵심 소구점 *", placeholder="한 줄에 하나씩 입력하세요.\n예: 차량 운행 정보 확인\n이용 절차 안내", height=100, key="benefits")
        st.caption("여러 소구점은 줄바꿈으로 구분합니다.")
        target = st.text_input("마케팅 타깃 *", placeholder="예: 화물차 운전자", key="target")
        objective = st.selectbox("이번 마케팅의 공통 목표", ["서비스 인지도 높이기", "핵심 혜택 이해시키기", "가입·이용 고려 유도", "기존 고객 이용 활성화", "직접 입력"], key="objective")
        if objective == "직접 입력":
            objective = st.text_input("공통 목표 직접 입력", placeholder="예: 신규 서비스 체험 신청 유도", key="objective_custom")
        customer_need = st.text_area("타깃의 상황·고민 (선택)", placeholder="예: 운행 관련 정보를 여러 곳에서 확인해야 하는 번거로움", height=65, key="customer_need")
        tone = st.selectbox("공통 톤앤매너", ["신뢰감 있는 정보형", "친근하고 쉬운 말투", "간결하고 전문적인 톤", "활기차고 자신감 있는 톤"], key="tone")
        forbidden_phrases = st.text_input("사용 주의·금지 표현", placeholder="예: 무조건, 국내 최초 (쉼표로 구분)", key="forbidden_phrases")
        references = st.text_area("공통 참고자료·브랜드 표현 (선택)", placeholder="확인된 사실, 모든 매체에 공통으로 반영할 내용, 참고 문체를 입력하세요.", height=72, key="references")
        confirmed = st.checkbox("입력 자료의 사용이 허용됨을 확인했습니다.", key="confirmed")
        generate = st.button("✦ 공통 브리프로 3종 초안 생성", type="primary", width="stretch", key="generate")
        revision_direction = st.text_area("수정 방향 (선택)", placeholder="예: 더 간결하고 전문적으로, CTA를 더 분명하게", height=60, key="revision_direction")
        regenerate = st.button("수정 방향 반영해 다시 생성", disabled="generated_result" not in st.session_state, width="stretch", key="regenerate")
        st.caption("OpenAI API · GPT-6 Luna · API 키는 로컬 .env에서 읽습니다.")

if generate or regenerate:
    missing = [label for label, value in [("서비스명", service), ("핵심 소구점", benefits), ("마케팅 타깃", target)] if not value.strip()]
    if not confirmed:
        missing.append("자료 사용 확인")
    if missing:
        st.error("먼저 필수 항목을 확인해 주세요: " + ", ".join(missing))
    elif not os.getenv("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY를 찾지 못했습니다. 로컬은 .env, Streamlit Cloud는 앱 Secrets에 설정해 주세요.")
    else:
        request_data = {
            "service_name": service.strip(), "service_description": description.strip(),
            "verified_benefits": [line.strip() for line in benefits.splitlines() if line.strip()],
            "target": target.strip(), "campaign_objective": objective,
            "customer_need": customer_need.strip(), "tone": tone,
            "forbidden_phrases": [part.strip() for part in re.split(r"[,，\n]", forbidden_phrases) if part.strip()],
            "common_verified_context_and_reference": references.strip(),
            "revision_direction": revision_direction.strip(),
        }
        request_data["channel_specs"] = json.loads(json.dumps(DEFAULT_CHANNEL_SPECS))
        user_prompt = "아래 공통 브리프를 바탕으로 콘텐츠 3종을 작성해 주세요. 카카오 브랜드톡과 지류 리플렛만 이미지 시안 기획을 생성하고 기획·보도기사의 이미지 필드는 빈 값으로 두세요. 매체별 시뮬레이션 요건은 기본값이므로 탭에서 조정 후 개별 재생성할 수 있습니다. 입력에 없는 사실은 추가하지 마세요.\n\n" + json.dumps(request_data, ensure_ascii=False, indent=2)
        try:
            with st.spinner("GPT-6 Luna가 콘텐츠 카피와 채널별 기획 요건을 작성하고 있습니다…"):
                client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90, max_retries=1)
                response = client.responses.create(
                    model=MODEL, reasoning={"effort": "low"}, max_output_tokens=5000,
                    input=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
                    text={"format": {"type": "json_schema", "name": "gotruck_content_plan", "strict": True, "schema": OUTPUT_SCHEMA}},
                )
                result = json.loads(response.output_text)
                st.session_state["generated_result"] = result
                st.session_state["model_name"] = MODEL
                st.session_state["demo_mode"] = False
                st.session_state.pop("kakao_image_variations", None)
                st.session_state.pop("kakao_images_demo", None)
                st.session_state.pop("kakao_copy_variations", None)
                st.session_state["generated_inputs"] = request_data
                for label, channel in CHANNELS.items():
                    st.session_state[channel["copy_key"]] = result[channel["copy_field"]]
                    visual = result["visuals"][channel["key"]]
                    st.session_state[channel["visual_key"]] = "\n".join([
                        f"콘셉트: {visual['concept']}", f"구도: {visual['composition']}",
                        f"주요 요소: {visual['visual_elements']}", f"색감·무드: {visual['palette_mood']}",
                        f"\n이미지 제작 프롬프트(시안):\n{visual['image_prompt']}",
                    ])
                st.toast("3종 카피와 채널별 기획안이 생성됐습니다.", icon=":material/check_circle:")
        except AuthenticationError:
            st.error("OpenAI 인증에 실패했습니다. .env 또는 Streamlit Cloud Secrets의 OPENAI_API_KEY를 확인해 주세요.")
        except APIConnectionError:
            st.error("OpenAI API에 연결할 수 없습니다. 인터넷 연결을 확인해 주세요.")
        except APIStatusError as exc:
            st.error(f"OpenAI API 요청이 거절됐습니다 (HTTP {exc.status_code}). 모델 접근 권한과 사용 한도를 확인해 주세요.")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            st.error(f"모델 응답을 결과로 읽지 못했습니다. 다시 생성해 주세요. ({type(exc).__name__})")
        except OpenAIError as exc:
            st.error(f"OpenAI API 요청 중 오류: {type(exc).__name__}")
        except Exception as exc:
            st.error(f"생성 중 오류: {type(exc).__name__}")


def esc(value: str) -> str:
    return html.escape(value or "", quote=True)


AD_REVIEW_PATTERNS = [
    ("근거 확인 · 최상급/단정", re.compile(r"최고|최저|최상|최초|최대|1\s*위|제일|유일|무조건|무제한|누구나|무심사|무서류|무담보|즉시(?:\s*(?:승인|발급|대출))?"), "최상급·단정 표현은 객관적인 근거와 적용 범위를 확인하세요."),
    ("비교 근거 확인", re.compile(r"(?:보다|대비|비교(?:해|하여)?|더\s*(?:높|낮|많|크|빠르|간편|저렴|크게|높게)|업계\s*평균|타사|경쟁사)"), "비교 대상·기준·시점과 객관적 근거를 함께 확인하세요."),
    ("혜택 조건 확인", re.compile(r"무료|할인|캐시백|적립|지급|혜택|보장|절감|절약|지원금|이벤트"), "광고된 혜택의 제공 주체, 대상, 기간, 한도와 제한조건이 확인 자료와 일치하는지 살펴보세요."),
    ("수치·기간 근거 확인", re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?\s*(?:%|원|만원|억원|명|건|회|일|개월|년|배|위)"), "수치의 산출 기준·출처·기준 시점 및 적용 조건을 확인하세요."),
]
FINANCIAL_AD_TERMS = re.compile(r"대출|대출금리|연체이자율|연체율|이자율|연회비|신용카드|카드론|리스금융|할부금융|원리금|개인신용평점")


def review_ad_copy(copy: str, inputs: dict) -> list[tuple[str, str, str]]:
    """Return explainable review signals; this is not a legal/compliance verdict."""
    findings: list[tuple[str, str, str]] = []
    text = copy or ""
    verified_context = " ".join([
        inputs.get("service_description", ""),
        inputs.get("common_verified_context_and_reference", ""),
        *inputs.get("verified_benefits", []),
    ])
    for label, pattern, reason in AD_REVIEW_PATTERNS:
        seen: set[str] = set()
        for match in pattern.finditer(text):
            phrase = match.group(0)
            normalized = re.sub(r"\s+", "", phrase).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            # Keep source-backed amounts visible for human confirmation, but only
            # raise a finding when the same value is absent from the supplied brief.
            if label == "수치·기간 근거 확인" and phrase in verified_context:
                continue
            findings.append((label, phrase, reason))
            if len(seen) >= 4:
                break
    custom_forbidden = inputs.get("forbidden_phrases", [])
    for phrase in custom_forbidden:
        if phrase and phrase in text:
            findings.append(("사용자 지정 금칙 표현", phrase, "공통 입력에서 금지한 표현이 초안에 포함되어 있습니다."))
    if FINANCIAL_AD_TERMS.search(text):
        findings.append(("금융광고 적용성 검토", "금융상품 관련 표현", "매뉴얼은 여신금융회사·금융상품 광고 중심입니다. 금융상품 광고에 해당하면 필수 고지·경고문구·심의 절차를 별도 검토하세요."))
    # Preserve first occurrence and avoid repeating the same signal.
    return list(dict.fromkeys(findings))


def regenerate_channel(channel_name: str, channel: dict, specs: dict, inputs: dict) -> dict:
    prompt_data = {"공통_기획정보": inputs, "선택_매체": channel_name, "매체별_시뮬레이션_요건": specs}
    channel_instruction = (
        "선택된 한 매체의 결과만 작성하세요. 기사는 기사문과 검토 메모만 작성하고 이미지 브리프 필드는 빈 문자열로 두세요."
        if channel["key"] == "article" else
        "선택된 한 매체의 결과만 작성하세요. 카피는 해당 매체 요건을 우선 적용하고, 이미지 브리프는 디자이너가 제작할 수 있도록 구체화하세요."
    )
    response = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90, max_retries=1).responses.create(
        model=MODEL, reasoning={"effort": "low"}, max_output_tokens=3000,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT + "\n" + channel_instruction},
            {"role": "user", "content": json.dumps(prompt_data, ensure_ascii=False, indent=2)},
        ],
        text={"format": {"type": "json_schema", "name": "gotruck_channel_draft", "strict": True, "schema": CHANNEL_SCHEMA}},
    )
    return json.loads(response.output_text)


def simulate_demo_channel(channel_name: str, channel: dict, specs: dict, inputs: dict, visual: dict) -> dict:
    """Create clearly labeled local-only sample drafts without making an API request."""
    benefits = inputs.get("verified_benefits", [])
    benefit_lines = "\n".join(f"• {item}" for item in benefits)
    required = [phrase.strip() for phrase in re.split(r"[,，\n]", specs.get("required_phrases", "")) if phrase.strip()]
    if channel["key"] == "kakao":
        cta = specs.get("cta", "자세히 알아보기") or "자세히 알아보기"
        url = f"\n{specs['url']}" if specs.get("url") else ""
        copy = f"[{inputs.get('service_name', '서비스')} · 데모]\n{specs.get('message_goal', '서비스 정보 안내')}\n{benefits[0] if benefits else '서비스 핵심 정보 확인'}\n\n{cta}{url}"
    elif channel["key"] == "article":
        article_type = specs.get("article_type", "서비스 소개")
        angle = specs.get("editorial_angle", "고객 편의 중심")
        quote = f"\n\n[확정 인용문]\n“{specs['quote']}”" if specs.get("quote") else ""
        article_purpose = specs.get("article_purpose", "서비스 인지도")
        copy = (f"헤드카피: {inputs.get('service_name', '서비스')}, 운행에 필요한 정보를 한곳에서\n"
                f"서브카피: {article_purpose}를 위한 서비스 소개 · {article_type}\n"
                f"본문:\n{inputs.get('target', '운전자')}가 운행 중 필요한 정보를 찾는 상황을 살펴봅니다. "
                f"이번 기사는 ‘{angle}’ 관점에서 구성한 데모 초안입니다. 아래 서비스 혜택은 검증 전 샘플입니다.\n\n{benefit_lines}\n\n"
                f"실제 서비스 기능과 제공 조건을 확인한 뒤 기사 문안을 확정하세요.{quote}\n\n※ 화면 확인용 가상 초안입니다.")
    else:
        url = f"\nURL·QR 목적지: {specs['url']}" if specs.get("url") else ""
        note = f"\n제작 유의: {specs['production_note']}" if specs.get("production_note") else ""
        copy = (f"{inputs.get('service_name', '서비스')}\n운행에 필요한 정보를 한 곳에서\n\n"
                f"{specs.get('audience_focus', '핵심 타깃 고객')}를 위한 {specs.get('format', '인쇄물')} 시뮬레이션\n\n"
                f"{benefit_lines}\n\n이용 안내\n서비스 화면에서 필요한 정보와 이용 방법을 확인해 보세요.\n\n"
                f"{url}{note}\n※ 화면 확인용 가상 문구입니다.")
    if required:
        copy += "\n\n[필수 문구 시뮬레이션]\n" + "\n".join(required)
    updated_visual = dict(visual)
    updated_visual["concept"] = f"데모 시뮬레이션 · {specs.get('message_goal') or specs.get('article_type') or specs.get('format') or channel_name}"
    updated_visual["image_prompt"] = "더미 데이터 미리보기용 이미지 지시문입니다. 실제 서비스의 화면, 브랜드 자산, 인쇄 규격에 맞게 디자이너가 교체하세요."
    return {"copy": copy, "visual": updated_visual, "review_notes": ["현재 결과는 API를 호출하지 않고 로컬에서 만든 데모 시뮬레이션입니다.", "실제 서비스 정보와 대조하고 검토 후 활용하세요."]}


def show_preview(channel_name: str, copy: str, visual: dict, specs: dict | None = None) -> None:
    lines = [line.strip() for line in copy.splitlines() if line.strip()]
    headline = esc(lines[0] if lines else st.session_state.get("service", "GoTruck Service"))
    subline = esc(lines[1] if len(lines) > 1 else visual.get("concept", "이미지 시안"))
    concept = esc(visual.get("concept", "이미지 시안"))
    composition = esc(visual.get("composition", ""))
    palette = esc(visual.get("palette_mood", ""))
    if channel_name == "카카오 브랜드톡":
        message_lines = "<br>".join(esc(line) for line in lines[1:])
        body = f'<div class="mockup-label">MESSAGE COPY</div><p>{message_lines}</p>'
        palette = ""
    elif channel_name == "지류 리플렛":
        benefits = [esc(line.lstrip("•- ")) for line in lines if line.startswith(("•", "-"))][:4]
        body = '<div class="mockup-label">KEY BENEFITS</div>' + ("".join(f'<div class="mockup-benefit">✓　{x}</div>' for x in benefits) or f"<p>{subline}</p>")
    elif channel_name == "기획·보도기사":
        body = f'<div class="mockup-label">HERO IMAGE DIRECTION</div><p>{concept}</p><p>{composition}</p>'
    else:
        body = f'<div class="mockup-label">MESSAGE PREVIEW</div><p>{subline}</p><p>{concept}</p>'
    specs = specs or {}
    cta_text = esc(specs.get("cta", "자세히 알아보기") or "자세히 알아보기")
    cta = f'<span class="mockup-cta">{cta_text}</span>' if channel_name == "카카오 브랜드톡" else ""
    image_direction = "" if channel_name == "카카오 브랜드톡" else f'<p style="font-size:10px;color:#7890a5;margin-top:12px">이미지 방향: {concept}</p>'
    st.markdown(f'<div class="mockup"><div class="mockup-visual"><div class="eyebrow">GOTRUCK SERVICE · {esc(channel_name.upper())}</div><h3>{headline}</h3><p>{palette}</p></div><div class="mockup-body">{body}{cta}{image_direction}</div></div>', unsafe_allow_html=True)


def show_kakao_preview(image_data: bytes | None, copy: str, specs: dict) -> None:
    """Show the proposed image paired with editable message copy, without app chrome."""
    if image_data:
        st.image(image_data, alt="카카오 브랜드톡 제작안 이미지 · 800×600px 원본", width=360)
    else:
        st.info("이 Variation의 PNG 시안을 생성하면 이미지와 카피 조합 프리뷰가 여기에 표시됩니다.", icon=":material/image:")
    cta = esc(specs.get("cta", "자세히 알아보기") or "자세히 알아보기")
    url = specs.get("url", "")
    copy_lines = (copy or "").splitlines()
    if copy_lines and copy_lines[-1].strip() == specs.get("cta", "자세히 알아보기"):
        copy_lines = copy_lines[:-1]
    if url and copy_lines and copy_lines[-1].strip() == url.strip():
        copy_lines = copy_lines[:-1]
    safe_copy = "<br>".join(esc(line) for line in copy_lines)
    link_line = f'<div style="font-size:11px;color:#7b8794;margin-top:7px">{esc(url)}</div>' if url else ""
    st.markdown(
        f'<div class="kakao-composite"><div class="kakao-composite-copy">{safe_copy}</div>'
        f'<div class="kakao-composite-cta">{cta}</div>{link_line}</div>',
        unsafe_allow_html=True,
    )


def show_leaflet_preview(copy: str, specs: dict, service_name: str) -> None:
    """Render print-like leaflet sides/panels instead of a generic web card."""
    lines = [line.strip() for line in (copy or "").splitlines() if line.strip()]
    benefits = [line.lstrip("•-✓ ") for line in lines if line.startswith(("•", "-", "✓"))][:4]
    title = next((line for line in lines if not line.startswith(("[", "※", "•", "-", "✓")) and len(line) < 48), service_name)
    subtitle = next((line for line in lines[lines.index(title) + 1:] if len(line) < 100), "서비스 핵심 내용을 한눈에 확인하세요.") if title in lines else "서비스 핵심 내용을 한눈에 확인하세요."
    url = esc(specs.get("url", ""))
    qr_note = "QR 연결 영역" if url else "QR 코드 자리 · 링크 확정 후 삽입"
    format_name = specs.get("format", "A4 양면")
    if "3단 접지" in format_name:
        panels = [
            ("접지 바깥면 · 좌", "이용 안내", "이용 조건과 안내 사항을 이 면에 배치합니다.", "NOTE"),
            ("접지 바깥면 · 중", "서비스 소개", subtitle, "INTRO"),
            ("접지 바깥면 · 우", "표지", title, "COVER"),
            ("접지 안쪽면 · 좌", "핵심 혜택", benefits[0] if benefits else "확인된 핵심 혜택을 배치합니다.", "BENEFIT 01"),
            ("접지 안쪽면 · 중", "이용 방법", "서비스에서 필요한 정보와 이용 방법을 확인하세요.", "HOW TO"),
            ("접지 안쪽면 · 우", "더 알아보기", qr_note, "CTA / QR"),
        ]
        panel_html = "".join(f'<div class="leaflet-panel"><small>{esc(label)}</small><div class="leaflet-panel-tag">{esc(kicker)}</div><b>{esc(heading)}</b><p>{esc(body)}</p></div>' for label, heading, body, kicker in panels)
        st.markdown(f'<div class="leaflet-preview-wrap"><div class="leaflet-preview-heading"><b>3단 접지 · 패널 배치 시뮬레이션</b><span>인쇄 전개면</span></div><div class="leaflet-trifold">{panel_html}</div><div class="leaflet-print-note">접지 방향과 패널 순서는 인쇄소 템플릿에 맞춰 최종 확인하세요.</div></div>', unsafe_allow_html=True)
        return

    front_benefit = benefits[0] if benefits else "확인된 대표 혜택을 한 문장으로 배치합니다."
    back_benefits = benefits[1:4] or benefits[:1] or ["확인된 서비스 혜택을 입력해 주세요."]
    back_list = "".join(f'<li>{esc(item)}</li>' for item in back_benefits)
    side_html = f'''<div class="leaflet-sheet leaflet-front"><div class="leaflet-sheet-label">앞면 · 표지</div><div class="leaflet-brandline">GOTRUCK　/　{esc(service_name)}</div><div class="leaflet-cover-copy"><span>운행을 위한 정보</span><h3>{esc(title)}</h3><p>{esc(subtitle)}</p></div><div class="leaflet-feature"><small>KEY BENEFIT</small><b>{esc(front_benefit)}</b></div><div class="leaflet-front-cta">{esc(specs.get("cta", "자세히 알아보기") or "자세히 알아보기")}</div></div><div class="leaflet-sheet leaflet-back"><div class="leaflet-sheet-label">뒷면 · 상세 안내</div><div class="leaflet-back-section"><small>WHAT YOU GET</small><h4>주요 혜택</h4><ul>{back_list}</ul></div><div class="leaflet-back-section"><small>HOW TO USE</small><h4>이용 방법</h4><p>서비스에서 필요한 정보와 이용 절차를 확인하세요.</p></div><div class="leaflet-back-bottom"><div><small>MORE INFORMATION</small><p>{url or qr_note}</p></div><div class="leaflet-qr" aria-label="QR code placeholder">QR</div></div></div>'''
    st.markdown(f'<div class="leaflet-preview-wrap"><div class="leaflet-preview-heading"><b>{esc(format_name)} · 인쇄물 미리보기</b><span>앞면 / 뒷면</span></div><div class="leaflet-spread">{side_html}</div><div class="leaflet-print-note">실제 인쇄 크기 비율을 축소해 표시합니다. 재단 여백·접지선·QR 실링크는 제작 전 확인하세요.</div></div>', unsafe_allow_html=True)


def article_sections(copy: str) -> tuple[str, str, str]:
    """Read the article's headline, subheadline, and body from the editable draft."""
    headline, subheadline, body = "", "", ""
    active = ""
    for line in (copy or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("헤드카피:"):
            headline, active = stripped.split(":", 1)[1].strip(), "headline"
        elif stripped.startswith("서브카피:"):
            subheadline, active = stripped.split(":", 1)[1].strip(), "subheadline"
        elif stripped.startswith("본문:"):
            body, active = stripped.split(":", 1)[1].strip(), "body"
        elif active == "headline" and stripped:
            headline += (" " if headline else "") + stripped
        elif active == "subheadline" and stripped:
            subheadline += (" " if subheadline else "") + stripped
        elif active == "body":
            body += ("\n" if body else "") + line
    if not headline and not subheadline and not body:
        paragraphs = [part.strip() for part in (copy or "").split("\n\n") if part.strip()]
        headline = paragraphs[0] if paragraphs else "헤드카피를 입력하세요"
        subheadline = paragraphs[1] if len(paragraphs) > 1 else "서브카피가 이곳에 표시됩니다."
        body = "\n\n".join(paragraphs[2:])
    return headline, subheadline, body


def show_article_preview(copy: str, specs: dict) -> None:
    """Render customer-facing article headline, subheadline, and body."""
    headline, subheadline, body = article_sections(copy)
    article_html = (
        '<div class="article-draft"><div class="article-draft-kicker">ARTICLE DRAFT · '
        + esc(specs.get("article_type", "서비스 소개")).upper()
        + f'</div><h2>{esc(headline or "헤드카피를 입력하세요")}</h2><p class="article-draft-subhead">{esc(subheadline or "서브카피가 이곳에 표시됩니다.")}</p>'
        + f'<div class="article-draft-body">{esc(body)}</div></div>'
    )
    st.markdown(article_html, unsafe_allow_html=True)


def article_preflight_lines(specs: dict) -> list[str]:
    return [
        f"기사 목적·유형: {specs.get('article_purpose') or '서비스 인지도'} · {specs.get('article_type') or '서비스 소개'}",
        f"매체·섹션: {specs.get('target_media') or '미지정'}",
        f"배포 희망일: {specs.get('release_date') or '미정'}",
        f"엠바고·배포 조건: {specs.get('embargo_note') or '별도 조건 없음'}",
        f"사전 팩트체크·승인: {specs.get('fact_check') or '기능·수치·인용문 확인 필요'}",
        f"기사 핵심 키워드: {specs.get('keywords') or '미지정'}",
        f"인용문: {'확정 발언 적용' if specs.get('quote') else '담당자 확정 전 · 임의 인용 금지'}",
    ]


with right_col:
    with st.container(border=True):
        head_col, state_col = st.columns([5, 1], vertical_alignment="center")
        with head_col:
            st.caption("02 / OUTPUT")
            st.subheader("콘텐츠 결과물")
        with state_col:
            if st.session_state.get("demo_mode"):
                st.badge("더미 데이터", icon=":material/science:", color="blue")
            else:
                st.badge("AI 초안" if "generated_result" in st.session_state else "생성 대기", icon=":material/auto_awesome:", color="green" if "generated_result" in st.session_state else "gray")
        if "generated_result" not in st.session_state:
            st.info("실제 정보를 입력해 AI 초안을 만들거나, 왼쪽의 ‘데모 데이터 불러오기’를 눌러 API 없이 샘플 결과를 확인하세요.", icon=":material/lightbulb:")
            with st.container(border=True):
                st.markdown("**생성 항목**")
                st.markdown("브랜드톡 카피와 PNG 시안　·　헤드카피·서브카피·본문으로 구성한 기사문　·　리플렛 카피와 이미지 브리프")
        else:
            result = st.session_state["generated_result"]
            inputs = st.session_state["generated_inputs"]
            if st.session_state.get("demo_mode"):
                st.info("데모 데이터로 표시 중입니다. 샘플 문구와 가상 서비스 정보는 실제 광고에 사용할 수 없습니다. 탭의 시뮬레이션 설정은 API 없이 로컬 샘플 결과에 반영됩니다.", icon=":material/science:")
            overview_cols = st.columns([1, 3], vertical_alignment="center", wrap=True)
            with overview_cols[0]:
                st.badge("핵심 메시지", icon=":material/flare:", color="blue")
            with overview_cols[1]:
                st.write(result.get("key_message", ""))
            st.caption("기획 방향 · " + result.get("planning_note", ""))
            tab_titles = ["01　카카오 브랜드톡", "02　지류 리플렛", "03　기획·보도기사"]
            for tab, (channel_name, channel) in zip(st.tabs(tab_titles), CHANNELS.items()):
                with tab:
                    st.session_state.setdefault(channel["copy_key"], result.get(channel["copy_field"], ""))
                    visual = result["visuals"][channel["key"]]
                    initial_visual = visual_brief(visual)
                    st.session_state.setdefault(channel["visual_key"], initial_visual)
                    specs = inputs.setdefault("channel_specs", {}).setdefault(channel["key"], DEFAULT_CHANNEL_SPECS[channel["key"]].copy())
                    with st.container(border=True):
                        st.caption(f"시뮬레이션 요건 · {channel_name}")
                        if channel["key"] == "kakao":
                            row = st.columns(3, gap="small", vertical_alignment="bottom", wrap=True)
                            goal_options = ["혜택 안내 및 이용 유도", "공지·정보 전달", "신규 서비스 소개", "이벤트 참여 유도", "직접 입력"]
                            with row[0]:
                                goal = st.selectbox("메시지 목적", goal_options, index=goal_options.index(specs.get("message_goal")) if specs.get("message_goal") in goal_options else 0, key="sim_kakao_goal")
                            if goal == "직접 입력":
                                goal = st.text_input("목적 직접 입력", key="sim_kakao_goal_custom")
                            with row[1]:
                                kakao_limit = st.number_input("최대 글자", 50, 2000, int(specs.get("max_characters", 350)), 10, key="sim_kakao_limit")
                            with row[2]:
                                st.markdown("**이미지 제작안**\n\n카피별 3종")
                            row = st.columns(3, gap="small", vertical_alignment="bottom", wrap=True)
                            with row[0]:
                                kakao_cta = st.text_input("버튼 CTA", value=specs.get("cta", "자세히 알아보기"), key="sim_kakao_cta")
                            with row[1]:
                                kakao_url = st.text_input("연결 URL", value=specs.get("url", ""), placeholder="선택", key="sim_kakao_url")
                            with row[2]:
                                image_styles = ["현장감 있는 실사", "밝은 라이프스타일", "깔끔한 에디토리얼", "그래픽 일러스트"]
                                current_style = specs.get("image_style", image_styles[0])
                                image_style = st.selectbox("이미지 스타일", image_styles, index=image_styles.index(current_style) if current_style in image_styles else 0, key="sim_kakao_image_style")
                            kakao_required = st.text_input("필수 문구", value=specs.get("required_phrases", ""), placeholder="쉼표로 구분 · 선택", key="sim_kakao_required")
                            st.caption("PNG에 카피나 로고를 넣지 않아 후속 편집이 쉽습니다.")
                            specs.update(message_goal=goal, max_characters=kakao_limit, cta=kakao_cta, url=kakao_url, required_phrases=kakao_required, image_count=3, image_style=image_style)
                        elif channel["key"] == "article":
                            kinds = ["서비스 소개", "기획기사", "보도자료형", "인터뷰형"]
                            old_kind = specs.get("article_type", "서비스 소개")
                            row = st.columns([1.2, 1.3, 2.2, 1], gap="small", vertical_alignment="bottom", wrap=True)
                            with row[0]:
                                article_type = st.selectbox("기사 유형", kinds, index=kinds.index(old_kind) if old_kind in kinds else 0, key="sim_article_type")
                            with row[1]:
                                purposes = ["서비스 인지도", "신규 서비스·기능 소개", "이용 방법 안내", "업계 이슈·인사이트"]
                                old_purpose = specs.get("article_purpose", "서비스 인지도")
                                article_purpose = st.selectbox("기사 목적", purposes, index=purposes.index(old_purpose) if old_purpose in purposes else 0, key="sim_article_purpose")
                            with row[2]:
                                article_angle = st.text_input("기사 관점", value=specs.get("editorial_angle", "타깃 고객에게 유용한 정보 중심"), key="sim_article_angle")
                            with row[3]:
                                article_limit = st.number_input("최대 글자", 200, 10000, int(specs.get("max_characters", 1800)), 100, key="sim_article_limit")
                            row = st.columns([1.4, 1.6, 1], gap="small", vertical_alignment="bottom", wrap=True)
                            with row[0]:
                                article_media = st.text_input("타깃 매체·섹션", value=specs.get("target_media", "운송·물류 전문 매체"), key="sim_article_media")
                            with row[1]:
                                article_keywords = st.text_input("기사 핵심 키워드", value=specs.get("keywords", ""), placeholder="헤드라인·검색어", key="sim_article_keywords")
                            with row[2]:
                                release_date = st.text_input("배포 희망일", value=specs.get("release_date", ""), placeholder="선택", key="sim_article_date")
                            row = st.columns([1, 1], gap="small", vertical_alignment="bottom", wrap=True)
                            with row[0]:
                                embargo_note = st.text_input("엠바고·배포 조건", value=specs.get("embargo_note", ""), placeholder="예: 배포 가능 시각", key="sim_article_embargo")
                            with row[1]:
                                quote = st.text_input("확정 인용문", value=specs.get("quote", ""), placeholder="선택 · 확인된 발언만", key="sim_article_quote")
                            row = st.columns([1.6, 1.4], gap="small", vertical_alignment="bottom", wrap=True)
                            with row[0]:
                                article_required = st.text_input("필수 문구", value=specs.get("required_phrases", ""), placeholder="쉼표로 구분 · 선택", key="sim_article_required")
                            with row[1]:
                                st.caption("사전 팩트체크 항목은 본문 확정 전에 확인할 내부 검토 요건입니다.")
                            fact_check = st.text_input("사전 팩트체크·승인 항목", value=specs.get("fact_check", ""), placeholder="예: 기능·수치 확인, 인용자 승인, 법무 검토", key="sim_article_fact_check")
                            st.caption("기사 목적과 매체 독자에 맞춰 카피를 작성합니다. 사실·수치 및 인용문은 본문 확정 전에 승인하세요.")
                            specs.update(article_type=article_type, article_purpose=article_purpose, editorial_angle=article_angle, target_media=article_media, max_characters=article_limit, release_date=release_date, embargo_note=embargo_note, quote=quote, keywords=article_keywords, required_phrases=article_required, fact_check=fact_check)
                        else:
                            formats = ["A4 단면", "A4 양면", "A5 양면", "3단 접지", "규격 미정"]
                            old_format = specs.get("format", "A4 양면")
                            row = st.columns([1.2, 1, 1.8], gap="small", vertical_alignment="bottom", wrap=True)
                            with row[0]:
                                leaflet_format = st.selectbox("인쇄 규격·접지", formats, index=formats.index(old_format) if old_format in formats else 0, key="sim_leaflet_format")
                            with row[1]:
                                leaflet_limit = st.number_input("최대 글자", 100, 3000, int(specs.get("max_characters", 500)), 50, key="sim_leaflet_limit")
                            with row[2]:
                                leaflet_audience = st.text_input("독자·배포처", value=specs.get("audience_focus", "핵심 타깃 고객"), key="sim_leaflet_audience")
                            row = st.columns(2, gap="small", vertical_alignment="bottom", wrap=True)
                            with row[0]:
                                leaflet_url = st.text_input("URL·QR 목적지", value=specs.get("url", ""), placeholder="선택", key="sim_leaflet_url")
                            with row[1]:
                                leaflet_required = st.text_input("필수 문구", value=specs.get("required_phrases", ""), placeholder="쉼표로 구분 · 선택", key="sim_leaflet_required")
                            production_note = st.text_input("제작 유의", value=specs.get("production_note", ""), placeholder="예: QR 여백 확보 · 선택", key="sim_leaflet_note")
                            specs.update(format=leaflet_format, max_characters=leaflet_limit, audience_focus=leaflet_audience, url=leaflet_url, required_phrases=leaflet_required, production_note=production_note)
                        if channel["key"] == "kakao":
                            source_copy = st.session_state.get(channel["copy_key"], "")
                            make_proposals = st.button("✦ 카피 Variation + 와이드 이미지 제작안 3종 생성", key="generate_kakao_proposals", type="primary", width="stretch")
                            if make_proposals:
                                try:
                                    if st.session_state.get("demo_mode"):
                                        benefits = inputs.get("verified_benefits", [])
                                        service_name = inputs.get("service_name", "고트럭 플러스")
                                        cta = specs.get("cta", "자세히 알아보기") or "자세히 알아보기"
                                        variations = [
                                            f"[{service_name} · 데모]\n운행 정보 찾기, 아직도 여러 곳을 확인하시나요?\n{benefits[0] if benefits else '운행 관련 정보를 한 곳에서 확인'}\n\n{cta}",
                                            f"[{service_name} · 데모]\n필요한 운행 정보와 서비스를 한눈에.\n{benefits[1] if len(benefits) > 1 else (benefits[0] if benefits else '필요한 서비스 정보를 간편하게 탐색')}\n\n{cta}",
                                            f"[{service_name} · 데모]\n운행 중 필요한 정보, 더 간편하게 살펴보세요.\n{benefits[2] if len(benefits) > 2 else (benefits[0] if benefits else '보기 쉬운 운행 정보 구성')}\n\n{cta}",
                                        ]
                                    elif not os.getenv("OPENAI_API_KEY"):
                                        st.error("OPENAI_API_KEY를 찾지 못했습니다. 로컬은 .env, Streamlit Cloud는 앱 Secrets에 설정해 주세요.")
                                        variations = []
                                    else:
                                        with st.spinner("GPT-6 Luna가 전략이 다른 카카오 카피 Variation 3종을 작성하고 있습니다…"):
                                            variations = generate_kakao_copy_variations(source_copy, inputs, specs)
                                    if variations:
                                        st.session_state["kakao_copy_variations"] = variations
                                        for index, variation in enumerate(variations, start=1):
                                            st.session_state[f"kakao_copy_variation_{index}"] = variation
                                        st.session_state.pop("kakao_image_variations", None)
                                        st.session_state.pop("kakao_images_demo", None)
                                        if st.session_state.get("demo_mode"):
                                            images = [make_demo_png(i - 1) for i in range(3)]
                                            st.session_state["kakao_images_demo"] = True
                                        else:
                                            images = []
                                            for index, variation_copy in enumerate(variations, start=1):
                                                with st.spinner(f"카피와 함께 {index}/3 와이드 이미지 제작안을 생성하고 있습니다…"):
                                                    generated = generate_kakao_images(specs, inputs, variation_copy, visual)
                                                if not generated:
                                                    raise ValueError(f"제작안 {index} 이미지 응답이 비었습니다.")
                                                images.append(generated[0])
                                            st.session_state["kakao_images_demo"] = False
                                        st.session_state["kakao_image_variations"] = images
                                        st.toast("카피 Variation 3종과 각 카피에 맞춘 800×600 PNG 3종을 생성했습니다.", icon=":material/check_circle:")
                                        st.rerun()
                                except AuthenticationError:
                                    st.error("OpenAI 인증에 실패했습니다. .env 또는 Streamlit Cloud Secrets의 OPENAI_API_KEY를 확인해 주세요.")
                                except APIStatusError as exc:
                                    st.error(f"콘텐츠 생성 요청이 거절됐습니다 (HTTP {exc.status_code}). 모델 접근 권한과 사용 한도를 확인해 주세요.")
                                except (APIConnectionError, OpenAIError, IndexError, ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
                                    st.error(f"카피와 이미지 제작안을 생성하지 못했습니다. {type(exc).__name__}")
                    regen_requested = False
                    if channel["key"] != "kakao":
                        regen_requested = st.button(f"↻ {channel_name} 요건 반영해 재생성", key=f"regen_{channel['key']}", width="stretch")
                    if regen_requested:
                        if st.session_state.get("demo_mode"):
                            updated = simulate_demo_channel(channel_name, channel, specs.copy(), inputs, visual)
                            result[channel["copy_field"]] = updated["copy"]
                            result["visuals"][channel["key"]] = updated["visual"]
                            result["review_notes"] = updated["review_notes"]
                            st.session_state[channel["copy_key"]] = updated["copy"]
                            st.session_state[channel["visual_key"]] = visual_brief(updated["visual"])
                            if channel["key"] == "kakao":
                                st.session_state.pop("kakao_copy_variations", None)
                                st.session_state.pop("kakao_image_variations", None)
                                st.session_state.pop("kakao_images_demo", None)
                            st.toast("데모 설정을 로컬 시뮬레이션에 반영했습니다. API 호출은 없었습니다.", icon=":material/check_circle:")
                            st.rerun()
                        elif not os.getenv("OPENAI_API_KEY"):
                            st.error("OPENAI_API_KEY를 찾지 못했습니다. 로컬은 .env, Streamlit Cloud는 앱 Secrets에 설정해 주세요.")
                        else:
                            try:
                                task_label = "헤드카피·서브카피·본문을 기사 요건에 맞춰 작성하고 있습니다…" if channel["key"] == "article" else f"{channel_name} 카피와 이미지 시안을 다시 기획하고 있습니다…"
                                with st.spinner(task_label):
                                    updated = regenerate_channel(channel_name, channel, specs.copy(), {k: v for k, v in inputs.items() if k != "channel_specs"})
                                result[channel["copy_field"]] = updated["copy"]
                                result["visuals"][channel["key"]] = updated["visual"]
                                result["review_notes"] = updated["review_notes"]
                                st.session_state[channel["copy_key"]] = updated["copy"]
                                st.session_state[channel["visual_key"]] = visual_brief(updated["visual"])
                                if channel["key"] == "kakao":
                                    st.session_state.pop("kakao_copy_variations", None)
                                    st.session_state.pop("kakao_image_variations", None)
                                    st.session_state.pop("kakao_images_demo", None)
                                st.toast(f"{channel_name} 시뮬레이션 결과를 반영했습니다.", icon=":material/check_circle:")
                                st.rerun()
                            except (AuthenticationError, APIConnectionError, APIStatusError, OpenAIError, json.JSONDecodeError, KeyError, TypeError) as exc:
                                st.error(f"해당 콘텐츠를 다시 생성하지 못했습니다. {type(exc).__name__}")
                    if channel["key"] == "kakao":
                        st.markdown("**제작안 프리뷰 · 와이드 이미지 800 × 600px**")
                        if st.session_state.get("demo_mode"):
                            st.caption("※ 화면 확인용 가상 문구와 로컬 샘플 이미지입니다.")
                        variations = st.session_state.get("kakao_copy_variations", [])
                        images = st.session_state.get("kakao_image_variations", [])
                        demo_prefix = "> 데모용 더미 콘텐츠 — 실제 사용 금지\n\n" if st.session_state.get("demo_mode") else ""
                        if variations:
                            proposal_tabs = st.tabs([f"제작안 {i}" for i in range(1, 4)])
                            for index, proposal_tab in enumerate(proposal_tabs, start=1):
                                with proposal_tab:
                                    with st.container(border=True):
                                        image_data = images[index - 1] if len(images) >= index else None
                                        edit_col, preview_col = st.columns([0.9, 1.1], gap="medium", vertical_alignment="top", wrap=True)
                                        with edit_col:
                                            st.markdown("**카피 편집**")
                                            variation_copy = st.text_area(f"제작안 {index} 카피 · 직접 수정 가능", key=f"kakao_copy_variation_{index}", height=125, label_visibility="collapsed")
                                            limit = int(specs.get("max_characters", DEFAULT_CHANNEL_SPECS["kakao"]["max_characters"]))
                                            st.caption(f"{len(variation_copy)} / {limit}자")
                                        with preview_col:
                                            st.markdown("**이미지 + 카피 프리뷰**")
                                            show_kakao_preview(image_data, variation_copy, specs)
                                        download_cols = st.columns(2, gap="small", vertical_alignment="center", wrap=True)
                                        with download_cols[0]:
                                            st.download_button(f"카피 다운로드 · {index}", f"{demo_prefix}# 카카오 브랜드톡 제작안 {index}\n\n{variation_copy}\n", file_name=f"gotruck_kakao_copy_variation_{index}.md", mime="text/markdown", key=f"download_kakao_copy_variation_{index}", width="stretch")
                                        with download_cols[1]:
                                            st.download_button(f"PNG 다운로드 · {index}", data=image_data or b"", file_name=f"gotruck_kakao_proposal_{index}.png", mime="image/png", key=f"download_kakao_png_{index}", width="stretch", disabled=not image_data)
                        else:
                            st.info("카피 Variation 3종과 각 이미지 제작안이 생성되면 이 영역에 프리뷰가 표시됩니다.", icon=":material/auto_awesome:")
                        if len(images) == 3:
                            zip_buffer = BytesIO()
                            with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                                for index, image_data in enumerate(images, start=1):
                                    archive.writestr(f"gotruck_kakao_proposal_{index}.png", image_data)
                            st.download_button("3개 제작안 PNG 전체 다운로드", zip_buffer.getvalue(), file_name="gotruck_kakao_proposals.zip", mime="application/zip", key="download_kakao_pngs_zip")
                        edited_visual = ""
                    elif channel["key"] == "article":
                        edit_col, preview_col = st.columns([1.25, 0.75], gap="medium", vertical_alignment="top", wrap=True)
                        with edit_col:
                            st.markdown("**기사문 편집 · 헤드카피 / 서브카피 / 본문**")
                            edited_copy = st.text_area("기사문 초안 · 직접 수정 가능", key=channel["copy_key"], height=500)
                            limit = int(specs.get("max_characters", DEFAULT_CHANNEL_SPECS["article"]["max_characters"]))
                            st.caption(f"{len(edited_copy)} / {limit}자 · 공백 포함")
                            if len(edited_copy) > limit:
                                st.warning(f"설정한 글자 수보다 {len(edited_copy) - limit}자 초과했습니다.")
                        with preview_col:
                            st.markdown("**기사 미리보기**")
                            show_article_preview(edited_copy, specs)
                        demo_prefix = "> 데모용 더미 콘텐츠 — 실제 사용 금지\n\n" if st.session_state.get("demo_mode") else ""
                        article_bundle = f"{demo_prefix}# {channel_name}\n\n## 기사문\n\n{edited_copy}\n\n## 기사 사전 기획 요건\n\n" + "\n".join(f"- {line}" for line in article_preflight_lines(specs))
                        st.download_button("기사문 + 사전 기획 요건 다운로드 (.md)", article_bundle, file_name="gotruck_article_plan.md", mime="text/markdown", key="download_article")
                    else:
                        edit_col, preview_col = st.columns([1, 1], gap="medium", vertical_alignment="top", wrap=True)
                        with edit_col:
                            st.markdown("**리플렛 원고 · 면별 편집**")
                            edited_copy = st.text_area("리플렛 원고 · 직접 수정 가능", key=channel["copy_key"], height=330, help="[앞면], [뒷면] 또는 3단 접지의 면별 구성을 유지해 편집하세요.")
                            limit = int(specs.get("max_characters", DEFAULT_CHANNEL_SPECS[channel["key"]]["max_characters"]))
                            st.caption(f"{len(edited_copy)} / {limit}자 · 공백 포함")
                            if len(edited_copy) > limit:
                                st.warning(f"설정한 글자 수보다 {len(edited_copy) - limit}자 초과했습니다.")
                            with st.expander("디자이너 전달용 시안 메모", expanded=False):
                                edited_visual = st.text_area("이미지 시안 브리프", key=channel["visual_key"], height=150)
                        with preview_col:
                            st.markdown("**인쇄물 LIVE PREVIEW**")
                            show_leaflet_preview(edited_copy, specs, inputs.get("service_name", "고트럭 서비스"))
                            st.caption(f"독자·배포처: {specs.get('audience_focus', '핵심 타깃 고객')}　·　규격: {specs.get('format', 'A4 양면')}")
                            edited_visual = st.session_state.get(channel["visual_key"], "")
                        demo_prefix = "> 데모용 더미 콘텐츠 — 실제 사용 금지\n\n" if st.session_state.get("demo_mode") else ""
                        bundle = f"{demo_prefix}# {channel_name}\n\n## 카피 초안\n\n{edited_copy}\n\n## 이미지 시안 브리프\n\n{edited_visual}\n"
                        st.download_button(f"{channel_name} 카피 + 이미지 브리프 다운로드", bundle, file_name=f"gotruck_{channel['key']}_brief.md", mime="text/markdown", key=f"download_{channel['key']}")
            required_by_channel = {
                key: [phrase.strip() for phrase in re.split(r"[,，\n]", inputs.get("channel_specs", {}).get(key, {}).get("required_phrases", "")) if phrase.strip()]
                for key in ["kakao", "article", "leaflet"]
            }
            missing_required = [f"{name} · {phrase}" for name, channel in CHANNELS.items()
                                for phrase in required_by_channel[channel["key"]]
                                if phrase not in st.session_state.get(channel["copy_key"], "")]
            compliance_findings = {
                name: review_ad_copy(st.session_state.get(channel["copy_key"], ""), inputs)
                for name, channel in CHANNELS.items()
            }
            finding_count = sum(len(items) for items in compliance_findings.values())
            with st.container(border=True):
                st.markdown("**광고 표현 사전 점검**　:gray[자동 점검은 표현 검토 신호이며, 준법심의나 법률 판단을 대체하지 않습니다.]")
                if finding_count:
                    st.warning(f"검토 신호 {finding_count}건을 찾았습니다. 초안의 문맥과 근거를 확인하세요.")
                    with st.expander("채널별 검토 사유 보기", expanded=True):
                        for name, items in compliance_findings.items():
                            if not items:
                                continue
                            st.markdown(f"**{name}**")
                            for label, phrase, reason in items:
                                st.markdown(f"- **{label}** · ‘{phrase}’ — {reason}")
                else:
                    st.success("등록된 표현 점검 신호가 발견되지 않았습니다. 무위험 또는 심의 적합을 의미하지는 않습니다.")
                if missing_required:
                    st.warning("필수 문구가 빠진 항목이 있습니다: " + ", ".join(missing_required))
                for note in result.get("review_notes", []):
                    st.markdown(f"- {note}")
                st.caption("점검 신호: 최상급·보편 단정, 비교, 혜택 조건, 수치·기간, 사용자 지정 금칙어, 금융상품 관련 표현. 매뉴얼(2023.11)은 여신금융회사·금융상품 광고 중심이므로 업종·매체·현행 규정 적용 여부와 필수 고지는 담당자가 별도 확인하세요.")
            demo_prefix = "> 데모용 더미 콘텐츠 — 실제 사용 금지\n\n" if st.session_state.get("demo_mode") else ""
            all_parts = [f"{demo_prefix}# GoTruck Studio · {inputs['service_name']}", f"> 모델: {'DEMO · 샘플 데이터' if st.session_state.get('demo_mode') else MODEL} · 콘텐츠 기획 초안", f"## 핵심 메시지\n\n{result.get('key_message', '')}", f"## 기획 방향\n\n{result.get('planning_note', '')}"]
            for name, channel in CHANNELS.items():
                all_parts.append(f"## {name}\n\n{st.session_state[channel['copy_key']]}")
                if channel["key"] == "kakao":
                    all_parts.append("### 카카오 PNG 시안\n\n별도 PNG 파일을 화면의 다운로드 버튼에서 받으세요.")
                elif channel["key"] == "article":
                    article_specs = inputs.get("channel_specs", {}).get("article", {})
                    all_parts.append("### 기사 사전 기획 요건\n\n" + "\n".join(f"- {line}" for line in article_preflight_lines(article_specs)))
                else:
                    all_parts.append(f"### 이미지 시안 브리프\n\n{st.session_state[channel['visual_key']]}")
            st.download_button("전체 기획안 다운로드", "\n\n".join(all_parts), file_name="gotruck_content_studio_brief.md", mime="text/markdown", key="download_full")

st.caption("GoTruck Studio · 기획/검토 보조용 초안 · 카피와 PNG 시안은 담당자 검토 후 활용하세요.")
