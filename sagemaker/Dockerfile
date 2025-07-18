# syntax=docker/dockerfile:1
# Multi-stage build for optimized SageMaker Real-ESRGAN container
FROM python:3.12-slim AS base

# 시스템 환경 변수
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 시스템 패키지 업데이트 및 필수 의존성 설치 (가장 안정적인 레이어)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# uv 설치 (빌드 도구)
RUN pip install --no-cache-dir uv

# Build stage - 종속성 및 모델 준비
FROM base AS builder
WORKDIR /build

# 종속성 파일 먼저 복사 (레이어 캐싱 최적화)
COPY sagemaker/requirements.txt .

# 최신 uv sync 사용으로 성능 최적화
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip sync requirements.txt --no-cache

# 모델 다운로드 (빌드 시점에 실행)
COPY sagemaker/download_model.py .
RUN . /opt/venv/bin/activate && \
    python download_model.py && \
    mv models /opt/ml/model

# Production stage - 최종 경량 이미지
FROM python:3.12-slim

# 시스템 환경 변수
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/ml/code:/opt/venv/bin:${PATH}"

# 런타임 시스템 종속성만 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# 코드 및 모델 디렉토리 생성
WORKDIR /opt/ml/code
RUN mkdir -p /opt/ml/model

# 빌드된 가상환경과 모델 복사
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/ml/model /opt/ml/model

# 추론 코드 및 서빙 스크립트 복사 (자주 변경되는 레이어를 마지막에)
COPY sagemaker/inference.py .
COPY sagemaker/serve.sh .

# SageMaker가 사용할 포트 노출
EXPOSE 8080

# 컨테이너 실행 시 Uvicorn으로 FastAPI 서버 시작
ENTRYPOINT ["bash", "serve.sh"]