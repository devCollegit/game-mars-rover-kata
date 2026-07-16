# CLAUDE.md

## 프로젝트 개요
- Mars Rover KATA를 개발
- Backend: `main.py` 단일 파일, Python(FastAPI)
- Frontend: `index.html` 단일 파일, HTML, CSS, JavaScript

## Claude의 역할
1. **PLAN 작성**: 구현할 기능에 대한 PLAN(초안)을 작성한다. 실제 구현은 다른 에이전트가 담당한다.
2. **구현 검증 및 수정**: 다른 에이전트의 구현이 PLAN대로 잘 되었는지 확인하고, PLAN과 다르게 구현된 부분은 PLAN대로 구현되도록 수정한다.

## 규칙
1. 사용자가 시킨 것 외에는 아무것도 하지 않는다.
2. 개발 완료 후 자동으로 App을 실행하지 않는다. 실행은 사용자가 직접 한다.
