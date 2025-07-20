# syntax=docker/dockerfile:1
# Multi-stage build for optimized SageMaker Real-ESRGAN container
FROM python:3.11-slim AS base

# 시스템 환경 변수
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 시스템 패키지 업데이트 및 필수 의존성 설치
RUN apt-get update && apt-get install -y \
  git \
  gcc \
  g++ \
  libgl1-mesa-glx \
  libglib2.0-0 \
  && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# uv 설치
RUN pip install --no-cache-dir uv

# Build stage - 종속성 및 모델 준비
FROM base AS builder
WORKDIR /build

# 종속성 파일 먼저 복사
COPY sagemaker/requirements.txt .

# 가상환경 생성 및 종속성 설치
RUN uv venv /opt/venv && \
  . /opt/venv/bin/activate && \
  uv pip sync requirements.txt --no-cache

# 모델 다운로드
COPY sagemaker/download_model.py .
RUN mkdir -p /opt/ml/model && \
  . /opt/venv/bin/activate && \
  python download_model.py

# Production stage
FROM python:3.11-slim

# 시스템 환경 변수
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/ml/code:/opt/venv/bin:${PATH}"

# 런타임 종속성 설치
RUN apt-get update && apt-get install -y \
  libgl1-mesa-glx \
  libglib2.0-0 \
  && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# 디렉토리 생성
WORKDIR /opt/ml/code
RUN mkdir -p /opt/ml/model

# 빌드된 환경과 모델 복사
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/ml/model /opt/ml/model

# 추론 코드 복사
COPY sagemaker/inference.py .
COPY sagemaker/serve.sh .
RUN chmod +x serve.sh

# SageMaker 포트
EXPOSE 8080

# SageMaker 엔트리포인트
ENTRYPOINT ["./serve.sh", "serve"]
