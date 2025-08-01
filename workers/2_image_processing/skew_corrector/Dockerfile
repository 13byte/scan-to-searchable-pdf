# syntax=docker/dockerfile:1
# Multi-stage build for optimized Fargate skew corrector
FROM public.ecr.aws/lambda/python:3.12 AS base

# 시스템 패키지 업데이트 및 의존성 설치 (가장 안정적인 레이어)
RUN dnf update -y && \
    dnf install -y mesa-libGL && \
    dnf clean all && \
    rm -rf /var/cache/dnf /tmp/* /var/tmp/*

# uv 설치 (빌드 도구)
RUN pip install --no-cache-dir uv

# Build stage - 종속성 빌드
FROM base AS builder
WORKDIR /build

# 종속성 파일 먼저 복사 (레이어 캐싱 최적화)
COPY workers/2_image_processing/skew_corrector/requirements.txt .

# 최신 uv sync 사용으로 성능 최적화
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip sync requirements.txt --no-cache

# Production stage - 최종 경량 이미지
FROM public.ecr.aws/lambda/python:3.12

# 런타임 시스템 종속성만 설치
RUN dnf update -y && \
    dnf install -y mesa-libGL && \
    dnf clean all && \
    rm -rf /var/cache/dnf /tmp/* /var/tmp/*

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

# 빌드된 종속성 복사
COPY --from=builder /opt/venv /opt/venv

# 애플리케이션 코드 복사 (자주 변경되는 레이어를 마지막에)
COPY workers/2_image_processing/skew_corrector/main.py .

# 실행 권한 설정
RUN chmod +x main.py

# 컨테이너 실행 명령
ENTRYPOINT ["python", "main.py"]