# syntax=docker/dockerfile:1
# SageMaker Real-ESRGAN 컨테이너를 위한 멀티 스테이지 빌드
# ml.g6e 인스턴스에 최적화 (NVIDIA L4 GPU)

# Base 스테이지: CUDA 런타임 및 기본 시스템 의존성 설치
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04 AS base

# 시스템 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Python 및 필수 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
  python3.11 \
  python3.11-venv \
  python3-pip \
  git \
  gcc \
  g++ \
  libgl1-mesa-glx \
  libglib2.0-0 \
  && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# python3.11을 기본 python으로 설정
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# uv 패키지 관리자 설치
RUN pip install --no-cache-dir uv

# Builder 스테이지: Python 종속성 및 모델 준비
FROM base AS builder
WORKDIR /build

# 종속성 파일 복사
COPY sagemaker/requirements.txt .

# 가상 환경 생성 및 종속성 설치
RUN uv venv /opt/venv && \
  . /opt/venv/bin/activate && \
  uv pip sync requirements.txt --no-cache

# 모델 다운로드 스크립트 복사 및 실행
COPY sagemaker/download_model.py .
RUN mkdir -p /opt/ml/model && \
  . /opt/venv/bin/activate && \
  python download_model.py

# Production 스테이지: 최종 런타임 이미지
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

# 시스템 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/ml/code:/opt/venv/bin:${PATH}"

# 런타임에 필요한 추가 시스템 의존성 설치 (대부분 base 이미지에 포함되어 있을 수 있음)
RUN apt-get update && apt-get install -y --no-install-recommends \
  libgl1-mesa-glx \
  libglib2.0-0 \
  && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# 작업 디렉토리 및 모델 저장 디렉토리 생성
WORKDIR /opt/ml/code
RUN mkdir -p /opt/ml/model

# 빌드된 가상 환경 및 모델 파일 복사
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/ml/model /opt/ml/model

# 추론 코드 및 실행 스크립트 복사
COPY sagemaker/inference.py .
COPY sagemaker/serve.sh .
RUN chmod +x serve.sh

# SageMaker 추론 포트 노출
EXPOSE 8080

# SageMaker 엔트리포인트 설정
ENTRYPOINT ["./serve.sh", "serve"]