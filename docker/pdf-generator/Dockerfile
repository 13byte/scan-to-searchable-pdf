# syntax=docker/dockerfile:1
# Multi-stage build for optimized PDF generator Lambda
FROM public.ecr.aws/lambda/python:3.12-arm64 AS base

# 시스템 종속성 설치 (가장 안정적인 레이어)
RUN dnf update -y && \
    dnf install -y fontconfig freetype-devel libjpeg-turbo-devel && \
    dnf clean all && \
    rm -rf /var/cache/dnf /tmp/* /var/tmp/*

# 폰트 디렉토리 생성
RUN mkdir -p /opt/python/fonts

# uv 설치 (빌드 도구)
RUN pip install --no-cache-dir uv

# Build stage - 종속성 빌드
FROM base AS builder
WORKDIR /build

# 종속성 파일 먼저 복사 (레이어 캐싱 최적화)
COPY workers/3_finalization/pdf_generator/requirements.txt .

# 최신 uv 성능 최적화 사용
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip sync requirements.txt --no-cache

# Production stage - 최종 경량 이미지
FROM public.ecr.aws/lambda/python:3.12-arm64

# 시스템 런타임 종속성만 설치
RUN dnf update -y && \
    dnf install -y fontconfig freetype libjpeg-turbo && \
    dnf clean all && \
    rm -rf /var/cache/dnf /tmp/* /var/tmp/*

# 폰트 디렉토리 생성
RUN mkdir -p /opt/python/fonts

# 빌드된 종속성만 복사
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 한글 폰트 복사
COPY config/NotoSansKR-Regular.ttf /opt/python/fonts/

# 환경 변수 설정
ENV FONT_PATH=/opt/python/fonts/NotoSansKR-Regular.ttf

# 애플리케이션 코드 복사 (자주 변경되는 레이어를 마지막에)
COPY workers/3_finalization/pdf_generator/main.py ${LAMBDA_TASK_ROOT}/

# Lambda 핸들러 설정
CMD ["main.handler"]