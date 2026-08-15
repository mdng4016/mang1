# -*- coding: utf-8 -*-
"""
서논술형 답안 자동 채점 앱 (Streamlit, 단일 파일 버전)
실행: streamlit run grading_app.py

구성 (파일 내부 섹션):
  1) 채점 기준 데이터 (CRITERIA, METHOD_DEFINITIONS)
  2) 채점 로직 (Claude API 호출, grade_blank_fill / grade_method_writing / grade_media_plan)
  3) Streamlit 화면 (UI)
"""

import json
import os
import re

import streamlit as st
from anthropic import Anthropic

MODEL = "claude-sonnet-5"


# =============================================================================
# 1) 채점 기준 데이터
# =============================================================================
METHOD_DEFINITIONS = {
    "정의": "대상의 뜻이나 개념을 규정하는 문장 (~란 ~이다 / ~을 말한다)",
    "예시": "구체적인 사례를 들어 대상을 설명하는 문장 (예를 들어 / ~ 등이 있다)",
    "인과": "원인과 결과의 관계로 서술하는 문장 (~ 때문에 / 그래서 / ~로 인해)",
    "분석": "대상을 구성 요소로 나누어 설명하는 문장 (~로 이루어져 있다 / ~부분으로 나뉜다)",
    "비교와 대조": "둘 이상 대상의 공통점 또는 차이점을 함께 언급하는 문장 (반면 / ~와 달리 / 공통점 / 차이점)",
    "분류와 구분": "기준에 따라 대상을 종류별로 묶거나 나누는 문장 (~에 따라 나뉜다 / ~로 묶인다)",
}

CRITERIA = {
    "세트1": {
        "제재": "사회적 촉진과 억제",
        "탭아이콘": "🔴",
        "실전제목": "과제 난이도와 사회적 촉진/억제",
        "passage": (
            "기자: 심리학 용어인 '사회적 촉진'과 '사회적 억제'를 일상생활, 특히 우리의 학습에 "
            "어떻게 적용할 수 있을까요?\n"
            "전문가: 이 두 가지 개념을 알면 상황에 맞춰 유용하게 활용할 수 있습니다. 예를 들어, "
            "비교적 쉬운 취미 생활이나 큰 노력을 들일 필요가 없는 과제를 할 때는 어떨까요?\n"
            "기자: 음, 그냥 집에서 편하게 혼자 하는 게 집중이 잘되지 않을까요?\n"
            "전문가: 그렇지 않습니다. 오히려 집에서 혼자 하는 것보다는 커피숍이나 도서관에서 하는 "
            "것이 더 효율적일 수 있습니다. 평소 친숙하고 좋아하는 과목이라면 공부 모임을 만들어서 "
            "다른 사람들과 함께 공부하는 것도 좋은 방법이죠.\n"
            "기자: 그렇다면 어렵고 복잡한 과제를 할 때는 어떻게 해야 하나요?\n"
            "전문가: 그럴 때는 반대입니다. 지나치게 어렵거나 도전이 필요한 과제는 충분히 연습하며 "
            "익숙해질 때까지 차분하게 혼자 집중하는 시간을 가지는 것이 좋습니다."
        ),
        "문항1": {
            "설명": "표 완성 (㉠~㉢)",
            "table": {
                "columns": ["과제의 특성", "효율적인 환경 및 방법", "관련된 심리 현상"],
                "rows": [
                    ["㉠", "커피숍, 도서관 등에서 하거나 모임을 만들어 다른 사람들과 함께 함", "사회적 촉진"],
                    ["지나치게 어렵거나 도전이 필요한 과제", "㉡", "㉢"],
                ],
            },
            "blanks": {
                "㉠": {
                    "label": "과제의 특성 (쉬운 과제 쪽)",
                    "required_concepts": ["과제 난이도가 쉬움", "노력이 많이 들지 않음"],
                    "accepted_examples": ["쉬운 과제", "부담이 적은 과제", "간단한 과제"],
                    "rejected_examples": ["재미있는 과제(의미 추가로 불인정)", "짧은 과제(무관한 속성)"],
                    "misconception_swap": "㉡(환경/방법) 내용을 여기에 쓰는 오류에 주의",
                    "model_answer": "비교적 쉬운 취미 생활이나 큰 노력을 들일 필요가 없는 과제",
                },
                "㉡": {
                    "label": "지나치게 어렵거나 도전이 필요한 과제의 효율적 환경 및 방법",
                    "required_concepts": ["혼자(타인 없이)", "차분함/집중", "연습하여 익숙해짐"],
                    "accepted_examples": ["홀로 조용히 연습", "혼자서 익숙해질 때까지 연습"],
                    "rejected_examples": ["조용한 곳에서 공부(혼자 요소 누락)", "열심히 연습(혼자·차분 요소 누락)"],
                    "misconception_swap": "㉠ 칸의 '함께하는 환경'(커피숍/도서관/모임)을 여기 쓰면 오답 방향 반대",
                    "model_answer": "충분히 연습하며 익숙해질 때까지 차분하게 혼자 집중하는 시간을 가짐",
                },
                "㉢": {
                    "label": "지나치게 어렵거나 도전이 필요한 과제의 관련 심리 현상",
                    "required_concepts": ["사회적 억제라는 고유 용어"],
                    "accepted_examples": [],
                    "rejected_examples": ["사회적 촉진(정반대 오류로 가장 흔함)", "집중 방해 효과(임의 표현 불인정)"],
                    "misconception_swap": "'사회적 촉진'과 좌우 대칭 구조라 헷갈려 반대로 쓰는 경우가 가장 흔한 오답",
                    "model_answer": "사회적 억제",
                },
            },
        },
        "문항2": {
            "설명": "서로 다른 2가지 설명 방법으로 이어지는 문장 (1),(2) 작성",
            "conditions": [
                "서로 다른 2가지의 설명 방법을 (1),(2)에 각각 하나씩 사용",
                "윗글에 제시된 내용만을 활용 (외부 배경지식 불인정)",
                "각 문장 끝에 사용한 설명 방법의 명칭을 괄호로 표기",
            ],
            "flow_required": False,
            "misconceptions": [
                "(1)과 (2)에 같은 설명 방법을 중복 사용",
                "괄호 명칭과 실제 문장의 서술 방식이 불일치 (예: 괄호엔 '인과'라 적었지만 실제 문장은 정의/예시 방식)",
                "지문에 없는 배경지식 삽입 (카페인, 집중력 앱, 백색소음의 과학적 원리 등)",
                "촉진/억제 상황을 지문과 반대로 서술 (쉬운 과제에 혼자 집중을, 어려운 과제에 함께를 적용)",
            ],
            "conclusion_requirement": (
                "쉬운 과제=함께(사회적 촉진), 어려운 과제=혼자(사회적 억제) 라는 대응 관계가 "
                "문장 내용에 정확히 반영되어야 함"
            ),
            "model_answers_by_method": {
                "정의": "사회적 촉진이란 타인의 존재가 수행을 돕는 현상을 말한다.",
                "예시": "예를 들어 도서관이나 공부 모임에서 함께 공부하면 수행이 향상된다.",
                "인과": "타인이 존재하기 때문에 쉬운 과제의 수행이 향상된다.",
                "비교와 대조": "반면 어려운 과제는 혼자 집중하는 것이 효과적이다.",
            },
        },
        "문항3": {
            "설명": "영상 기획안 시각(Ⓐ)·청각(Ⓑ) 요소 + 각 효과 서술",
            "conditions": [
                "어려운 과제를 할 때 필요한 환경의 특성이 잘 드러나도록 연출 계획을 세울 것",
                "설정한 시각/청각 요소가 글의 내용을 전달하는 데 어떤 효과가 있는지 각각 서술할 것",
            ],
            "requires_passage_evidence": False,  # 세트1은 조건문에 '근거 포함'이 명시되지 않음
            "contrast_with_scene1_required": False,  # 지문에 암묵적일 뿐 필수 조건 아님(가산 요소)
            "required_concept_axes": ["혼자(타인 없음)", "차분함/집중"],
            "model_answer": {
                "시각(Ⓐ)": "조용한 개인 열람실에서 한 학생이 문제집을 붙잡고 골똘히 집중하는 모습을 클로즈업",
                "시각효과": "혼자만의 몰입 상태를 강조하여 '차분한 집중'이 필요한 어려운 과제의 특성을 전달",
                "청각(Ⓑ)": "배경음악 없이 연필 소리, 시계 초침 소리 같은 미세한 효과음만 사용",
                "청각효과": "정적인 사운드로 산만함을 배제해 '혼자 집중하는 환경'의 필요성을 강조",
            },
        },
    },
    "세트2": {
        "제재": "정전기",
        "탭아이콘": "⚡",
        "실전제목": "물에 비유한 정전기의 특성",
        "passage": (
            "기자: 겨울철 불청객인 '정전기'란 정확히 무엇인지 설명 부탁드립니다.\n"
            "전문가: 정전기란 전하가 정지 상태로 있어 그 분포가 시간적으로 변화하지 않는 전기, "
            "그리고 그로 인한 전기 현상을 말합니다.\n"
            "기자: 우리가 실생활에서 쓰는 전기와는 어떻게 다른가요? 물에 비유해서 설명해 주시면 "
            "이해가 쉬울 것 같습니다.\n"
            "전문가: 아주 좋은 비유가 될 수 있습니다. 우리가 실생활에서 쓰는 전기가 '흐르는 물'이라면, "
            "정전기는 '높은 곳에 고여 있는 물'이라고 할 수 있습니다.\n"
            "기자: 정전기가 일어날 때 찌릿한 느낌이 드는데, 혹시 위험하지는 않은가요?\n"
            "전문가: 정전기의 전압은 매우 높지만, 우리가 실생활에서 쓰는 전기와는 다르게 전하가 "
            "이동하지 않고 머물러 있어 위험하지는 않습니다."
        ),
        "문항1": {
            "설명": "표 완성 (㉠~㉢)",
            "table": {
                "columns": ["대상", "물의 상태에 비유", "전하의 상태", "위험성"],
                "rows": [
                    ["실생활 전기", "흐르는 물", "전하가 이동함", "감전 등의 위험이 있음"],
                    ["정전기", "㉠", "㉡", "㉢"],
                ],
            },
            "blanks": {
                "㉠": {
                    "label": "정전기의 물 상태 비유",
                    "required_concepts": ["높은 곳(위치)", "고여 있음(정지 상태)"],
                    "accepted_examples": ["높은 곳에 머물러 있는 물", "고지대에 정지된 물"],
                    "rejected_examples": ["고여 있는 물(위치 요소 누락→부분점수)", "떨어지는 물(반대 의미)"],
                    "misconception_swap": "'흐르는 물'(실생활 전기 쪽 정답)과 뒤바꿔 쓰는 오류 주의",
                    "model_answer": "높은 곳에 고여 있는 물",
                },
                "㉡": {
                    "label": "정전기의 전하 상태",
                    "required_concepts": ["이동하지 않음/머물러 있음"],
                    "accepted_examples": ["전하가 흐르지 않음", "전하가 정지 상태"],
                    "rejected_examples": ["전기가 안 통함(전하 개념과 다른 부정확한 표현)"],
                    "misconception_swap": "'전하가 이동함'(실생활 전기 쪽)과 반대로 써야 함",
                    "model_answer": "전하가 이동하지 않고 머물러 있음",
                },
                "㉢": {
                    "label": "정전기의 위험성",
                    "required_concepts": ["위험하지 않음/안전함"],
                    "accepted_examples": ["안전함", "피해가 없음"],
                    "rejected_examples": ["약함(위험성과 무관한 속성)"],
                    "misconception_swap": "전압이 높다=위험하다는 상식적 오개념으로 '위험함'이라 반대로 쓰는 오류가 흔함",
                    "model_answer": "위험하지 않음(감전 등의 위험이 없음)",
                },
            },
        },
        "문항2": {
            "설명": "설명 방법 1가지 이상씩 다르게 사용, 논리적 흐름을 갖는 (1),(2) 작성",
            "conditions": [
                "(1)과 (2)에는 서로 다른 설명 방법이 1가지 이상 활용",
                "윗글에 제시된 내용만을 활용",
                "(1)과 (2)가 논리적 흐름을 갖고 이어지도록 할 것",
            ],
            "flow_required": True,
            "misconceptions": [
                "비유('물에 비유')를 '비교와 대조'가 아니라 '비유'라고만 표기 (정식 6대 방법 명칭 아님 → 불인정)",
                "(1)(2) 둘 다 비유만 반복 (중복 방법)",
                "순서가 뒤바뀌어 흐름이 어색 (비교가 먼저, 정의가 나중)",
                "배경지식 삽입 (마찰 발생 원리, 정전기 방지 스프레이 등)",
            ],
            "conclusion_requirement": "정전기 = 전압은 높지만 위험하지 않다는 결론이 명확히 드러나야 함",
            "model_answers_by_method": {
                "정의": "정전기란 전하가 정지 상태로 있어 시간적으로 분포가 변화하지 않는 전기를 말한다.",
                "비교와 대조": (
                    "실생활 전기가 흐르는 물이라면 정전기는 고여 있는 물과 같아서, 전압은 높지만 "
                    "위험하지 않다는 점에서 차이가 있다."
                ),
            },
        },
        "문항3": {
            "설명": "영상 기획안 시각(Ⓐ)·청각(Ⓑ) 요소 + 각 효과 서술 (근거 포함 필수)",
            "conditions": [
                "정전기의 특성이 잘 드러나도록 연출 계획을 세울 것",
                "효과를 서술하되, 반드시 윗글의 내용을 근거로 포함할 것",
            ],
            "requires_passage_evidence": True,  # 조건문에 명시
            "contrast_with_scene1_required": True,  # 폭포/저수지 대비가 지문에 명시적
            "required_concept_axes": ["고여 있음/정지 상태", "위험하지 않음/안전함"],
            "model_answer": {
                "시각(Ⓐ)": "고요한 저수지나 댐에 물이 잔잔하게 고여 있는 모습을 보여줌",
                "시각효과": (
                    "지문에서 정전기를 '높은 곳에 고여 있는 물'에 비유했으므로, 폭포처럼 흐르지 않고 "
                    "고요히 머물러 있는 저수지 이미지로 정지된 상태를 전달함"
                ),
                "청각(Ⓑ)": "거센 물소리 대신 정적 또는 잔잔한 물결 소리",
                "청각효과": (
                    "지문에서 '정전기는 전압은 높지만 위험하지 않다'고 했으므로, 소리 크기를 줄여 "
                    "고요하게 표현함으로써 안전함을 감각적으로 전달함"
                ),
            },
        },
    },
    "세트3": {
        "제재": "인공지능이 그린 그림",
        "탭아이콘": "🎨",
        "실전제목": "인간과 인공지능이 만드는 예술의 차이",
        "passage": (
            "기자: 최근 생성형 인공 지능이 그린 그림이 미술계에서 큰 화제를 모으고 있습니다.\n"
            "전문가: 「에드몽 드 벨라미」라는 작품이 대표적입니다.\n"
            "기자: 이 그림을 인간이 만든 예술 작품과 같다고 볼 수 있을까요?\n"
            "전문가: 로봇이 한 번의 실수 없이 완벽하게 피겨 스케이팅을 해내더라도 우리의 마음을 "
            "울리지는 못하지요. 인간의 작품에는 작가의 고유한 감정이나 철학, 삶의 경험, 세상을 "
            "바라보는 관점 같은 요소가 종합적으로 담겨 있으므로 예술로 볼 수 있습니다. 하지만 "
            "인공 지능은 감정도 느끼지 못하고 독자적인 철학이나 이야기가 없기 때문에 이를 예술로 "
            "보기는 어렵습니다.\n"
            "기자: 그렇다면 인공 지능이 그린 그림은 가치가 전혀 없는 것인가요?\n"
            "전문가: 그렇지는 않습니다. 기존 미술계에 큰 변화를 가져왔다는 점에서 분명한 의미가 "
            "있습니다. 또한 앞으로 예술의 범주를 확장할 수 있다는 점에서 상징적인 가치를 지닙니다."
        ),
        "문항1": {
            "설명": "표 완성 (㉠~㉢)",
            "table": {
                "columns": ["대상", "올림픽 경기에 비유", "예술로 볼 수 있는가 (근거 포함)", "예술로서의 가치"],
                "rows": [
                    ["인간의 예술", "인간 선수의 노력과 열정이 담긴 올림픽 경기",
                     "작가의 경험, 관점, 환경이 담겨 있으므로 예술이다.", "감상자에게 남다른 감동을 줌"],
                    ["인공지능의 예술", "㉠", "㉡", "㉢"],
                ],
            },
            "blanks": {
                "㉠": {
                    "label": "인공지능 예술의 올림픽 경기 대응 비유",
                    "required_concepts": ["로봇", "피겨 스케이팅", "완벽함/실수 없음"],
                    "accepted_examples": ["실수 없이 완벽하게 피겨를 하는 로봇"],
                    "rejected_examples": ["인공지능이 그린 그림(비유 대상과 표의 대상을 혼동 → 불인정)"],
                    "misconception_swap": "표의 대상(인공지능 그림) 자체를 다시 쓰는 오류 주의 — 지문 속 '비유'를 찾아야 함",
                    "model_answer": "로봇이 실수 없이 완벽하게 해내는 피겨 스케이팅",
                },
                "㉡": {
                    "label": "예술로 볼 수 있는가 (근거 포함)",
                    "required_concepts": ["감정 없음", "철학/이야기 없음", "예술이 아니다(결론)"],
                    "accepted_examples": ["감정이 없고 이야기가 없어 예술로 볼 수 없음"],
                    "rejected_examples": ["인간이 아니라서 예술이 아님(지문에 없는 자의적 이유)"],
                    "misconception_swap": "'예술이다'로 결론을 반대로 쓰는 오류 주의",
                    "model_answer": "감정도 느끼지 못하고 독자적인 철학이나 이야기가 없으므로 예술이 아니다",
                },
                "㉢": {
                    "label": "예술로서의 가치 (이중 구조: 부정+긍정 모두 필요)",
                    "required_concepts": [
                        "감동을 주지 못함(부정 요소)",
                        "미술계 변화 또는 예술 범주 확장(긍정 요소, 상징적 가치)",
                    ],
                    "accepted_examples": ["감동은 주지 못하나 미술계에 의미 있는 변화를 줌"],
                    "rejected_examples": ["가치가 전혀 없음(지문 결론과 반대)", "훌륭한 예술임(과잉 해석)"],
                    "misconception_swap": (
                        "부정 요소만 쓰거나 긍정 요소만 쓰면 지문의 절반만 반영한 것 — "
                        "이 항목만 유일하게 두 요소 모두 필요"
                    ),
                    "model_answer": (
                        "감동을 주지는 못하지만 미술계에 변화를 가져오고 예술의 범주를 확장한다는 "
                        "상징적 가치는 있음"
                    ),
                    "dual_requirement": True,
                },
            },
        },
        "문항2": {
            "설명": "설명 방법 1가지 이상씩 다르게 사용, 논리적 흐름(반전 구조)을 갖는 (1),(2) 작성",
            "conditions": [
                "(1)과 (2)에는 서로 다른 설명 방법이 1가지 이상 활용",
                "윗글에 제시된 내용만을 활용",
                "(1)과 (2)가 논리적 흐름을 갖고 이어지도록 할 것",
            ],
            "flow_required": True,
            "flow_note": (
                "이 지문은 '예술이 아니다 → 그러나 가치는 있다'는 반전 구조. (1)에서 부정만 쓰고 "
                "(2)에서 반전 없이 부정을 반복하면 지문의 핵심 결론(그래도 가치는 있음)을 놓친 것으로 "
                "논리적 흐름 조건 미충족 처리"
            ),
            "misconceptions": [
                "(1)(2) 둘 다 인과로 중복 (지문이 인과 구조 위주라 세트 중 가장 빈번)",
                "반전 접속어('그러나/하지만') 없이 부정만 반복하여 지문의 최종 결론(가치 있음)을 누락",
                "배경지식 삽입 (화가들의 일자리 위협, 저작권 문제 등)",
            ],
            "conclusion_requirement": (
                "인공지능 그림은 예술은 아니지만 상징적 가치는 있다는 '반전 결론'이 반드시 드러나야 함 "
                "(부정만으로 끝나면 결론 방향 미충족)"
            ),
            "model_answers_by_method": {
                "인과": "인공지능은 감정과 철학이 없기 때문에 진정한 예술로 보기 어렵다.",
                "비교와 대조": (
                    "그러나 인간 예술과 달리 감정이 없어도, 인공지능 그림은 미술계에 변화를 가져오고 "
                    "예술의 범주를 확장한다는 점에서 다른 가치를 지닌다."
                ),
            },
        },
        "문항3": {
            "설명": "영상 기획안 시각(Ⓐ)·청각(Ⓑ) 요소 + 각 효과 서술 (근거 포함 필수) [총 6점]",
            "conditions": [
                "인간이 만들어내는 예술의 특성이 잘 드러나도록 연출 계획을 세울 것",
                "효과를 서술하되, 반드시 윗글의 내용을 근거로 포함할 것",
            ],
            "requires_passage_evidence": True,
            "contrast_with_scene1_required": True,  # 로봇/인간 대비가 지문에 명시적
            "required_concept_axes": ["작가의 감정·경험·철학(작가 측)", "감상자의 감동(감상자 측)"],
            "total_points": 6,
            "point_breakdown": {
                "시각 요소(Ⓐ) 타당성": 1,
                "시각 효과 서술(근거+연결)": 2,
                "청각 요소(Ⓑ) 타당성": 1,
                "청각 효과 서술(근거+연결)": 2,
            },
            "model_answer": {
                "시각(Ⓐ)": "화가가 자신의 기억이나 아픔을 떠올리며 그림을 그리고, 관객이 감동받아 눈시울을 붉히는 모습",
                "시각효과": (
                    "지문에서 인간의 예술에는 '작가의 감정이나 철학, 경험'이 담겨 있다고 했으므로, "
                    "화가가 자신의 경험을 그림에 담는 모습을 통해 이를 시각적으로 표현함"
                ),
                "청각(Ⓑ)": "잔잔하고 감정을 자극하는 현악기(첼로/바이올린) 선율",
                "청각효과": (
                    "지문에서 인간의 예술은 '감상자에게 남다른 감동을 준다'고 했으므로, 감정을 자극하는 "
                    "선율을 사용해 감동을 청각적으로 강조함"
                ),
            },
        },
    },
}


# =============================================================================
# 2) 채점 로직
# =============================================================================
def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다. "
            "터미널에서 `export ANTHROPIC_API_KEY=sk-...` 또는 .streamlit/secrets.toml에 등록하세요."
        )
    return Anthropic(api_key=api_key)


def _clean_ai_text(text) -> str:
    """AI가 생성한 텍스트에서 마크다운 강조 기호(**, __)와 둥근따옴표를 정리해
    화면에 'AI가 쓴 티'가 나지 않도록 다듬는다."""
    if not text:
        return ""
    text = str(text)
    text = text.replace("**", "").replace("__", "")
    text = (
        text.replace("\u201c", '"').replace("\u201d", '"')
        .replace("\u2018", "'").replace("\u2019", "'")
    )
    return text.strip()


def _call_claude_json(system_prompt: str, user_prompt: str) -> dict:
    """Claude를 호출하고 JSON 응답을 파싱해서 반환. 코드펜스가 섞여 와도 방어적으로 파싱."""
    client = _client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError(f"채점 응답에서 JSON을 찾지 못했습니다. 원본 응답: {text[:500]}")
    return json.loads(match.group(0))


# ----------------------------------------------------------------------------
# 공통 시스템 프롬프트: 5가지 필수 반영 사항을 모두 명시
# ----------------------------------------------------------------------------
_BASE_SYSTEM_PROMPT = """\
너는 중학교 국어(설명하는 글 쓰기 / 영상 매체 제작) 서논술형 문항의 채점자다.
다음 6가지 원칙을 반드시 지켜서 채점한다.

1) [용어 없이도 의미 인정] 채점 기준에 제시된 표현(용어)이 답안에 그대로 없어도,
   요구된 의미(개념)가 문장에 담겨 있으면 정답으로 인정한다. 단어 매칭이 아니라 뜻으로 판단한다.
2) [방법의 기능 확인] 학생이 특정 설명 방법의 명칭을 표기했다면, 그 방법의 실제 기능적 특성
   (예: '인과'라면 원인→결과 관계, '비교와 대조'라면 공통점 또는 차이점 언급)이 문장에
   실제로 드러나는지 확인한다. 명칭만 맞고 기능이 다르면 오답(또는 명칭 오류)으로 처리한다.
3) [오개념 방지] 채점 기준에 제시된 '오개념 패턴'(한 개념의 특성을 반대/다른 개념 설명에
   사용하는 경우)이 답안에 나타나면 반드시 오답으로 처리하고, 어떤 오개념인지 reason에 명시한다.
4) [결론 누락 확인] 개념 설명(정의·과정·근거 등)만 있고, 문항 조건이 요구한 결론
   (행동/처방/판단/최종 대답 등)이 답안에 명확히 드러나지 않으면 설령 앞부분 설명이 옳아도
   오답 또는 부분점수로 처리한다. "결론이 빠졌다"는 사실을 reason에 반드시 명시한다.
5) [요소 간 연결 확인] 답안이 두 개의 요소로 이루어져야 하는 경우(예: 시각 요소와 그 효과,
   질문과 근거, 주장과 근거), 두 요소가 형식상 모두 존재하더라도 내용상 실제로 서로 연결되지
   않았다면 오답으로 처리한다. 특히 뒤에 오는 요소(효과·근거 등)에는 앞 요소가 왜 그렇게
   설정되었는지에 대한 구체적 내용이 반드시 담겨 있어야 하며, "좋은 느낌을 준다"처럼 앞 요소와
   무관하게도 쓸 수 있는 일반적 서술은 연결되지 않은 것으로 본다.
6) [지문 외 배경지식 배제] 답안이 지문에 없는 외부 지식·주장을 추가했다면, 그 부분은 인정하지
   않는다. 단, 지문 내용을 다른 표현으로 재진술한 것은 배경지식이 아니라 정상적인 답안으로 본다.

reason은 학생이 이해할 수 있는 한국어 평서문으로 쓰고, 마크다운 강조 기호(**, __ 등)나
곡선 따옴표(“ ” ‘ ’)를 쓰지 않는다. 필요하면 큰따옴표(")나 작은따옴표(')를 직선 형태로만 쓴다.

반드시 순수 JSON만 출력한다. 코드펜스나 설명 문장을 앞뒤에 붙이지 않는다.
"""


def grade_blank_fill(set_id: str, blank_id: str, blank_criteria: dict, student_answer: str) -> dict:
    user_prompt = f"""
[채점 대상] {set_id} 문항1 - 빈칸 {blank_id} ({blank_criteria['label']})

[정답에 필요한 핵심 의미 요소]
{json.dumps(blank_criteria['required_concepts'], ensure_ascii=False)}

[인정 가능한 표현 예시]
{json.dumps(blank_criteria.get('accepted_examples', []), ensure_ascii=False)}

[불인정 예시 및 이유]
{json.dumps(blank_criteria.get('rejected_examples', []), ensure_ascii=False)}

[흔한 오개념 패턴 - 반드시 확인]
{blank_criteria.get('misconception_swap', '없음')}

[모범 답안]
{blank_criteria['model_answer']}

[이중 요소 필수 여부]
{"이 항목은 서로 다른 두 의미 요소(부정+긍정 등)가 '모두' 있어야 만점이며, 하나만 있으면 부분점수(0.5)만 인정." if blank_criteria.get('dual_requirement') else "해당 없음(단일 요소 판단)"}

[학생 답안]
{student_answer if student_answer.strip() else "(답안 없음)"}

다음 JSON 형식으로만 응답할 것 (배점은 1점 만점 기준):
{{
  "score": 0~1 사이 숫자 (정답=1, 부분점수=0.5, 오답=0),
  "verdict": "정답" 또는 "부분점수" 또는 "오답",
  "reason": "판단 근거를 한국어 1~2문장으로",
  "misconception_flag": "감지된 오개념 패턴 설명 또는 null"
}}
"""
    result = _call_claude_json(_BASE_SYSTEM_PROMPT, user_prompt)
    reason = _clean_ai_text(result["reason"])
    misconception = _clean_ai_text(result.get("misconception_flag")) or None
    return {
        "total_score": result["score"],
        "max_score": 1,
        "items": [
            {
                "name": f"{blank_id} {blank_criteria['label']}",
                "score": result["score"],
                "max": 1,
                "verdict": result["verdict"],
                "reason": reason,
                "misconception_flag": misconception,
            }
        ],
        "overall_feedback": reason,
    }


def grade_method_writing(set_id: str, q_criteria: dict, sentence1: str, method1: str,
                          sentence2: str, method2: str) -> dict:
    user_prompt = f"""
[채점 대상] {set_id} 문항2 - 설명 방법을 활용한 이어쓰기

[문항 조건]
{json.dumps(q_criteria['conditions'], ensure_ascii=False, indent=2)}

[6가지 설명 방법의 기능 정의 - 명칭과 실제 기능 일치 여부 판단용]
{json.dumps(METHOD_DEFINITIONS, ensure_ascii=False, indent=2)}

[논리적 흐름 조건 필요 여부]
{q_criteria.get('flow_required', False)}
{q_criteria.get('flow_note', '')}

[흔한 오개념/위반 패턴 - 반드시 확인]
{json.dumps(q_criteria['misconceptions'], ensure_ascii=False, indent=2)}

[요구되는 결론/방향]
{q_criteria['conclusion_requirement']}

[방법별 모범 답안 참고]
{json.dumps(q_criteria['model_answers_by_method'], ensure_ascii=False, indent=2)}

[학생 답안]
(1) 문장: {sentence1 if sentence1.strip() else '(없음)'}
(1) 표기한 방법 명칭: {method1 if method1.strip() else '(없음)'}
(2) 문장: {sentence2 if sentence2.strip() else '(없음)'}
(2) 표기한 방법 명칭: {method2 if method2.strip() else '(없음)'}

다음 항목을 각각 1점 만점으로 채점하고 JSON으로만 응답:
- "different_methods": (1)(2)가 서로 다른 방법을 사용했는가 (명칭이 아니라 실제 기능 기준)
- "method_function_match": 표기한 방법 명칭과 실제 문장의 기능이 일치하는가 (두 문장 평균)
- "passage_only": 지문 내용만 활용했는가 (외부 배경지식 없음)
- "flow_and_conclusion": (흐름 조건이 있다면) 논리적 흐름이 자연스럽고, 요구되는 결론 방향이 드러나는가.
   흐름 조건이 없다면 결론 방향만 확인.

JSON 형식:
{{
  "different_methods": {{"score": 0~1, "reason": "..."}},
  "method_function_match": {{"score": 0~1, "reason": "..."}},
  "passage_only": {{"score": 0~1, "reason": "..."}},
  "flow_and_conclusion": {{"score": 0~1, "reason": "..."}},
  "misconception_flag": "감지된 오개념 또는 null",
  "overall_feedback": "학생에게 줄 종합 피드백 2~3문장"
}}
"""
    result = _call_claude_json(_BASE_SYSTEM_PROMPT, user_prompt)
    items = []
    name_map = {
        "different_methods": "서로 다른 방법 사용",
        "method_function_match": "방법 명칭-기능 일치",
        "passage_only": "지문 내용만 활용",
        "flow_and_conclusion": "논리적 흐름/결론 방향",
    }
    total = 0
    for key, name in name_map.items():
        sub = result[key]
        total += sub["score"]
        items.append({
            "name": name, "score": sub["score"], "max": 1,
            "verdict": "정답" if sub["score"] >= 1 else ("부분점수" if sub["score"] > 0 else "오답"),
            "reason": _clean_ai_text(sub["reason"]), "misconception_flag": None,
        })
    return {
        "total_score": total,
        "max_score": 4,
        "items": items,
        "overall_feedback": _clean_ai_text(result.get("overall_feedback", "")),
        "misconception_flag": _clean_ai_text(result.get("misconception_flag")) or None,
    }


def grade_media_plan(set_id: str, q_criteria: dict, visual: str, visual_effect: str,
                      audio: str, audio_effect: str) -> dict:
    total_points = q_criteria.get("total_points", 6)
    breakdown = q_criteria.get("point_breakdown", {
        "시각 요소(Ⓐ) 타당성": total_points / 6,
        "시각 효과 서술(근거+연결)": total_points / 3,
        "청각 요소(Ⓑ) 타당성": total_points / 6,
        "청각 효과 서술(근거+연결)": total_points / 3,
    })

    user_prompt = f"""
[채점 대상] {set_id} 문항3 - 영상 기획안 시각/청각 요소 및 효과 서술 (총 {total_points}점)

[문항 조건]
{json.dumps(q_criteria['conditions'], ensure_ascii=False, indent=2)}

[반드시 반영해야 할 핵심 개념 축]
{json.dumps(q_criteria['required_concept_axes'], ensure_ascii=False)}
(이 문항은 개방형이라 정답이 하나가 아니다. 위 개념 축이 요소/효과 서술에 반영되어 있는지로 판단한다.)

[효과 서술에 지문 근거 인용이 필수인가]
{q_criteria['requires_passage_evidence']}
(참고: 이 항목이 True인 세트는 근거 언급이 없으면 효과 서술 점수를 절반 이하로 감점한다.
 False인 세트는 근거 인용이 없어도 요소-효과 간 논리적 연결만 있으면 만점 가능.)

[장면1과의 대비를 필수 조건으로 볼지 여부]
{q_criteria['contrast_with_scene1_required']}
(True면 대비되는 연출이 없을 경우 감점 대상. False면 가산 요소로만 취급하고 감점하지 않는다.)

[배점 배분]
{json.dumps(breakdown, ensure_ascii=False, indent=2)}

[모범 답안 예시(참고용, 유일 정답 아님)]
{json.dumps(q_criteria['model_answer'], ensure_ascii=False, indent=2)}

[학생 답안]
시각 요소(Ⓐ): {visual if visual.strip() else '(없음)'}
시각 효과: {visual_effect if visual_effect.strip() else '(없음)'}
청각 요소(Ⓑ): {audio if audio.strip() else '(없음)'}
청각 효과: {audio_effect if audio_effect.strip() else '(없음)'}

위 배점 배분 항목별로 채점하여 다음 JSON 형식으로만 응답 (score는 각 항목의 배점 한도 내 실수):
{{
  "시각 요소(Ⓐ) 타당성": {{"score": 0~배점, "reason": "..."}},
  "시각 효과 서술(근거+연결)": {{"score": 0~배점, "reason": "..."}},
  "청각 요소(Ⓑ) 타당성": {{"score": 0~배점, "reason": "..."}},
  "청각 효과 서술(근거+연결)": {{"score": 0~배점, "reason": "..."}},
  "overall_feedback": "학생에게 줄 종합 피드백 2~3문장"
}}
"""
    result = _call_claude_json(_BASE_SYSTEM_PROMPT, user_prompt)
    items = []
    total = 0
    for name, max_score in breakdown.items():
        sub = result[name]
        total += sub["score"]
        items.append({
            "name": name, "score": sub["score"], "max": max_score,
            "verdict": "정답" if sub["score"] >= max_score else ("부분점수" if sub["score"] > 0 else "오답"),
            "reason": _clean_ai_text(sub["reason"]), "misconception_flag": None,
        })
    return {
        "total_score": total,
        "max_score": total_points,
        "items": items,
        "overall_feedback": _clean_ai_text(result.get("overall_feedback", "")),
    }


# =============================================================================
# 3) Streamlit 화면 (UI)
# =============================================================================
st.set_page_config(page_title="서논술형 자동 채점", page_icon="✍️", layout="wide")

# API 키는 화면에 노출하지 않고 Secrets/환경변수에서만 조용히 읽어온다.
try:
    _default_key = st.secrets.get("ANTHROPIC_API_KEY", "")
except Exception:
    _default_key = ""
_default_key = _default_key or os.environ.get("ANTHROPIC_API_KEY", "")
if _default_key:
    os.environ["ANTHROPIC_API_KEY"] = _default_key

# ---------------------------------------------------------------------------
# 전역 상태 초기화
# ---------------------------------------------------------------------------
if "results" not in st.session_state:
    st.session_state["results"] = {}  # key: f"{set_id}|{q_id}" -> 채점 결과 dict

# ---------------------------------------------------------------------------
# 스타일
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .passage-box {
        background-color: #eaf2fd; border-radius: 10px; padding: 20px 24px;
        line-height: 1.7; white-space: pre-line; color: #1a1a2e; margin-bottom: 18px;
    }
    .stem-text {
        font-size: 1.02rem; font-weight: 600; color: #222; margin: 14px 0 8px 0;
    }
    .condition-box {
        background-color: #f2f2f4; border-radius: 8px; padding: 14px 18px;
        margin-bottom: 14px; font-size: 0.92rem; color: #333; line-height: 1.8;
    }
    .field-stem {
        font-size: 0.92rem; font-weight: 600; color: #444; margin: 10px 0 2px 0;
    }
    .criteria-table { width: 100%; border-collapse: collapse; margin-bottom: 8px; }
    .criteria-table th {
        background-color: #f3f0fb; padding: 10px 12px; text-align: center;
        border: 1px solid #e2ddf3; font-size: 0.92rem;
    }
    .criteria-table td {
        padding: 10px 12px; text-align: center; border: 1px solid #eee; font-size: 0.92rem;
    }
    .blank-symbol {
        display: inline-block; background-color: #6c5ce7; color: white;
        border-radius: 50%; width: 26px; height: 26px; line-height: 26px;
        font-weight: 700; font-size: 0.85rem;
    }
    .tip-box {
        background-color: #fff8e1; border-radius: 8px; padding: 14px 16px;
        font-size: 0.88rem; line-height: 1.6; color: #6b5900; margin-top: 10px;
    }
    .review-card {
        background-color: #fff5f5; border-left: 4px solid #e57373; border-radius: 6px;
        padding: 12px 16px; margin-bottom: 12px;
    }
    .reset-hint { font-size: 0.8rem; color: #888; text-align: right; margin-bottom: 2px; }
    div[data-testid="stSidebarUserContent"] { padding-top: 0.5rem; }
    div.stButton > button[kind="secondary"][aria-label="reset-btn"] {}
    </style>
    """,
    unsafe_allow_html=True,
)

SYMBOLS = {"㉠", "㉡", "㉢", "㉣"}


def render_reference_table(table_meta: dict):
    cols = table_meta["columns"]
    rows = table_meta["rows"]
    html = ['<table class="criteria-table"><thead><tr>']
    html += [f"<th>{c}</th>" for c in cols]
    html.append("</tr></thead><tbody>")
    for row in rows:
        html.append("<tr>")
        for cell in row:
            if cell in SYMBOLS:
                html.append(f'<td><span class="blank-symbol">{cell}</span></td>')
            else:
                html.append(f"<td>{cell}</td>")
        html.append("</tr>")
    html.append("</tbody></table>")
    st.markdown("".join(html), unsafe_allow_html=True)


def render_conditions(conditions):
    if not conditions:
        return
    lines = "".join(f"<div>❗ {c}</div>" for c in conditions)
    st.markdown(f'<div class="condition-box">{lines}</div>', unsafe_allow_html=True)


def field(stem_text: str):
    """발문을 입력란 바로 위에 붙여 표시."""
    st.markdown(f'<div class="field-stem">{stem_text}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 상단: 초기화 버튼 (오른쪽 끝, 한 줄)
# ---------------------------------------------------------------------------
top_l, top_r = st.columns([5, 2])
with top_r:
    st.markdown(
        '<div class="reset-hint">모든 문제를 제출하면 복습할 내용 탭에서 틀린 개념을 확인할 수 있어요. '
        "답안을 초기화하고 처음부터 다시 풀고 싶다면 다음의 버튼을 누르세요.</div>",
        unsafe_allow_html=True,
    )
    _, btn_col = st.columns([3, 1])
    with btn_col:
        if st.button("처음부터 다시 풀기", key="reset_all_btn", type="secondary", use_container_width=True):
            st.session_state.clear()
            st.rerun()

# ---------------------------------------------------------------------------
# 사이드바 — 개념 길잡이
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 📖 개념 길잡이")
    with st.expander("1. 설명 방법 공식", expanded=True):
        formulas = {
            "정의": "~란 ~를 말한다.",
            "예시": "예를 들어 ~",
            "인과": "~ 때문에 ~한다.",
            "비교와 대조": "[공통점] ~와 ~의 공통점은 ~이다. / [차이점] ~는 ~이지만, ~는 ~이다.",
            "분석": "~는 ~와(과) ~로 이루어져 있다.",
            "분류와 구분": "~는 ~라는 기준에 따라 ~와(과) ~로 나뉜다.",
        }
        for name, formula in formulas.items():
            st.markdown(f"- **{name}**: {formula}")

    st.markdown("---")
    tip_placeholder = st.empty()

# ---------------------------------------------------------------------------
# 상단 탭
# ---------------------------------------------------------------------------
set_ids = list(CRITERIA.keys())
tab_labels = [f"{CRITERIA[s]['탭아이콘']} {CRITERIA[s]['제재']}" for s in set_ids] + ["📘 복습할 내용"]
tabs = st.tabs(tab_labels)

for tab, set_id in zip(tabs[:-1], set_ids):
    with tab:
        set_data = CRITERIA[set_id]

        st.markdown(f"## 💡 [실전 적용] {set_data['실전제목']}")
        st.markdown(f'<div class="passage-box">{set_data["passage"]}</div>', unsafe_allow_html=True)

        nav_key = f"nav_{set_id}"
        if nav_key not in st.session_state:
            st.session_state[nav_key] = "문항1"

        nav_labels = {"문항1": "✏️ 1번 빈칸 채우기", "문항2": "📝 2번 설명문 쓰기", "문항3": "🎬 3번 영상 기획"}
        nc1, nc2, nc3 = st.columns(3)
        for col, q_key in zip([nc1, nc2, nc3], ["문항1", "문항2", "문항3"]):
            btn_type = "primary" if st.session_state[nav_key] == q_key else "secondary"
            if col.button(nav_labels[q_key], key=f"{set_id}_{q_key}_navbtn",
                          use_container_width=True, type=btn_type):
                st.session_state[nav_key] = q_key

        q_id = st.session_state[nav_key]
        q_data = set_data[q_id]
        result_key = f"{set_id}|{q_id}"
        st.divider()

        # ============================= 문항1 =============================
        if q_id == "문항1":
            st.markdown(
                '<div class="stem-text">[서·논술형 1] 윗글을 요약하여 표로 정리하였다. '
                "빈칸에 들어갈 내용을 찾아 쓰시오.</div>",
                unsafe_allow_html=True,
            )
            render_reference_table(q_data["table"])

            tip_placeholder.markdown(
                '<div class="tip-box">💡 1번 문제 풀이 팁: 표의 다른 칸(주어진 내용)을 먼저 읽고, '
                "빈칸에 들어갈 내용을 지문에서 찾아 정리해 쓰세요. 용어가 지문과 똑같지 않아도 "
                "뜻이 같으면 정답으로 인정됩니다.</div>",
                unsafe_allow_html=True,
            )

            answers = {}
            for blank_id, blank in q_data["blanks"].items():
                field(f"{blank_id}")
                answers[blank_id] = st.text_input(
                    f"{blank_id}", key=f"{set_id}_{q_id}_{blank_id}", label_visibility="collapsed",
                )

            with st.expander("💡 모범 답안 미리 보기"):
                for blank_id, blank in q_data["blanks"].items():
                    st.markdown(f"**{blank_id}**: {blank['model_answer']}")

            if st.button("채점하기 ▶", type="primary", key=f"{set_id}_grade_q1"):
                try:
                    total, maxt, items_all = 0, 0, []
                    for blank_id, blank in q_data["blanks"].items():
                        with st.spinner(f"{blank_id} 채점 중..."):
                            r = grade_blank_fill(set_id, blank_id, blank, answers[blank_id])
                        total += r["total_score"]
                        maxt += r["max_score"]
                        item = r["items"][0]
                        items_all.append(item)
                        icon = {"정답": "✅", "부분점수": "🟡", "오답": "❌"}.get(item["verdict"], "•")
                        st.markdown(f"{icon} **{item['name']}** — {item['verdict']} ({item['score']}/{item['max']}점)")
                        st.caption(item["reason"])
                        if item.get("misconception_flag"):
                            st.warning(f"⚠️ 오개념 감지: {item['misconception_flag']}")
                    st.success(f"### 총점: {total} / {maxt}")

                    review_points = [
                        f"{bid}: {b['required_concepts']}" for bid, b in q_data["blanks"].items()
                    ]
                    st.session_state["results"][result_key] = {
                        "세트": set_id, "문항": q_id, "제재": set_data["제재"], "아이콘": set_data["탭아이콘"],
                        "total_score": total, "max_score": maxt, "items": items_all,
                        "review_points": review_points,
                    }
                except Exception as e:
                    st.error(f"채점 중 오류: {e}")

        # ============================= 문항2 =============================
        elif q_id == "문항2":
            st.markdown(
                '<div class="stem-text">[서·논술형 2] 서로 다른 설명 방법을 사용하여 '
                "이어지는 문장 (1), (2)를 작성하시오.</div>",
                unsafe_allow_html=True,
            )
            render_conditions(q_data["conditions"])

            method_options = list(METHOD_DEFINITIONS.keys())

            c1, c2 = st.columns(2)
            with c1:
                field("(1)")
                sentence1 = st.text_area("(1)", height=100, key=f"{set_id}_{q_id}_s1", label_visibility="collapsed")
                method1 = st.selectbox("사용한 설명 방법", method_options, key=f"{set_id}_{q_id}_m1")
            with c2:
                field("(2)")
                sentence2 = st.text_area("(2)", height=100, key=f"{set_id}_{q_id}_s2", label_visibility="collapsed")
                method2 = st.selectbox("사용한 설명 방법", method_options, key=f"{set_id}_{q_id}_m2")

            tip_placeholder.markdown(
                '<div class="tip-box">💡 2번 문제 풀이 팁: 왼쪽 설명 방법 공식을 활용해 문장을 만들고 '
                "서로 다른 두 방법을 사용하세요. 지문에 없는 내용은 쓰지 않습니다."
                + (" (1)→(2)가 논리적으로 자연스럽게 이어져야 합니다." if q_data.get("flow_required") else "")
                + "</div>",
                unsafe_allow_html=True,
            )

            with st.expander("💡 모범 답안 (방법별) 미리 보기"):
                for method, example in q_data["model_answers_by_method"].items():
                    st.markdown(f"**{method}**: {example}")
                st.caption(f"※ 목록 외 다른 방법 조합도 조건을 충족하면 정답으로 인정됩니다: {', '.join(method_options)}")

            if st.button("채점하기 ▶", type="primary", key=f"{set_id}_grade_q2"):
                try:
                    with st.spinner("채점 중..."):
                        result = grade_method_writing(set_id, q_data, sentence1, method1, sentence2, method2)
                    for item in result["items"]:
                        icon = "✅" if item["score"] >= item["max"] else ("🟡" if item["score"] > 0 else "❌")
                        st.markdown(f"{icon} **{item['name']}** — {item['score']}/{item['max']}점")
                        st.caption(item["reason"])
                    if result.get("misconception_flag"):
                        st.warning(f"⚠️ 오개념 감지: {result['misconception_flag']}")
                    st.success(f"### 총점: {result['total_score']} / {result['max_score']}")
                    st.write("**종합 피드백**:", result["overall_feedback"])

                    st.session_state["results"][result_key] = {
                        "세트": set_id, "문항": q_id, "제재": set_data["제재"], "아이콘": set_data["탭아이콘"],
                        "total_score": result["total_score"], "max_score": result["max_score"],
                        "items": result["items"],
                        "review_points": [f"요구되는 결론/방향: {q_data['conclusion_requirement']}"],
                        "overall_feedback": result["overall_feedback"],
                    }
                except Exception as e:
                    st.error(f"채점 중 오류: {e}")

        # ============================= 문항3 =============================
        elif q_id == "문항3":
            st.markdown(
                '<div class="stem-text">[서·논술형 3] 영상 기획안의 시각(Ⓐ)·청각(Ⓑ) 요소와 '
                "그 효과를 서술하시오.</div>",
                unsafe_allow_html=True,
            )
            conds = list(q_data["conditions"])
            if q_data["requires_passage_evidence"]:
                conds = conds + ["효과 서술에는 반드시 윗글의 내용을 근거로 포함해야 함"]
            render_conditions(conds)

            field("시각 요소 (Ⓐ)")
            visual = st.text_area("시각 요소", height=80, key=f"{set_id}_{q_id}_visual", label_visibility="collapsed")
            field("시각 효과 서술")
            visual_effect = st.text_area("시각 효과", height=80, key=f"{set_id}_{q_id}_veffect", label_visibility="collapsed")
            field("청각 요소 (Ⓑ)")
            audio = st.text_area("청각 요소", height=80, key=f"{set_id}_{q_id}_audio", label_visibility="collapsed")
            field("청각 효과 서술")
            audio_effect = st.text_area("청각 효과", height=80, key=f"{set_id}_{q_id}_aeffect", label_visibility="collapsed")

            tip_placeholder.markdown(
                '<div class="tip-box">💡 3번 문제 풀이 팁: 지문의 핵심 개념이 시각/청각 요소에 드러나야 하고, '
                "효과 서술은 요소와 실제로 연결되어야 합니다."
                + (" 지문 내용을 반드시 근거로 인용하세요." if q_data["requires_passage_evidence"] else "")
                + "</div>",
                unsafe_allow_html=True,
            )

            with st.expander("💡 모범 답안 예시 (개방형 문항 — 참고용)"):
                for k, v in q_data["model_answer"].items():
                    st.markdown(f"**{k}**: {v}")

            if st.button("채점하기 ▶", type="primary", key=f"{set_id}_grade_q3"):
                try:
                    with st.spinner("채점 중..."):
                        result = grade_media_plan(set_id, q_data, visual, visual_effect, audio, audio_effect)
                    for item in result["items"]:
                        icon = "✅" if item["score"] >= item["max"] else ("🟡" if item["score"] > 0 else "❌")
                        st.markdown(f"{icon} **{item['name']}** — {item['score']}/{item['max']}점")
                        st.caption(item["reason"])
                    st.success(f"### 총점: {result['total_score']} / {result['max_score']}")
                    st.write("**종합 피드백**:", result["overall_feedback"])

                    st.session_state["results"][result_key] = {
                        "세트": set_id, "문항": q_id, "제재": set_data["제재"], "아이콘": set_data["탭아이콘"],
                        "total_score": result["total_score"], "max_score": result["max_score"],
                        "items": result["items"],
                        "review_points": [f"반영해야 할 개념: {', '.join(q_data['required_concept_axes'])}"],
                        "overall_feedback": result["overall_feedback"],
                    }
                except Exception as e:
                    st.error(f"채점 중 오류: {e}")

# ---------------------------------------------------------------------------
# 복습할 내용 탭 — 조건 미충족 문제만 표시
# ---------------------------------------------------------------------------
with tabs[-1]:
    st.markdown("## 📘 복습할 내용")

    failed = {
        k: v for k, v in st.session_state["results"].items()
        if v["total_score"] < v["max_score"]
    }

    if not st.session_state["results"]:
        st.info("아직 제출한 문항이 없습니다. 문제를 풀고 채점하면 부족한 부분이 여기에 표시됩니다.")
    elif not failed:
        st.success("제출한 문항을 모두 조건에 맞게 완성했습니다. 복습할 내용이 없습니다. 🎉")
    else:
        for k, v in failed.items():
            st.markdown(f"### {v['아이콘']} {v['제재']} — {v['문항']} ({v['total_score']}/{v['max_score']}점)")
            st.markdown("**핵심 복습 포인트**")
            for rp in v["review_points"]:
                st.markdown(f"- {rp}")
            st.markdown("**내 답안에서 부족했던 부분**")
            for item in v["items"]:
                if item["score"] < item["max"]:
                    st.markdown(
                        f'<div class="review-card"><b>{item["name"]}</b><br>{item["reason"]}</div>',
                        unsafe_allow_html=True,
                    )
            st.divider()

    st.markdown("### 설명 방법 6가지 공식 (전체 복습)")
    for name, definition in METHOD_DEFINITIONS.items():
        st.markdown(f"- **{name}**: {definition}")
