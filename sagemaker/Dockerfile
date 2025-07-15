# SageMaker Custom Inference Container with FastAPI, Uvicorn, and uv
FROM python:3.12-slim

# 시스템 환경 변수
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/ml/code:${PATH}"

# 시스템 패키지 업데이트 및 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
  git \
  build-essential \
  libgl1-mesa-glx \
  libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/*

# uv 설치
RUN pip install uv

# 코드 및 모델 디렉토리 생성
WORKDIR /opt/ml/code
RUN mkdir -p /opt/ml/model

# 의존성 파일 복사 및 uv로 설치
# Install dependencies
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# 모델 다운로더 실행
COPY download_model.py .
# 빌드 시점에 모델을 /opt/ml/model 디렉토리에 다운로드
RUN python download_model.py

# 추론 코드 복사
COPY inference.py .

# Serve script for SageMaker
COPY serve.sh .

# SageMaker가 사용할 포트 노출
EXPOSE 8080

# 컨테이너 실행 시 Uvicorn으로 FastAPI 서버 시작
ENTRYPOINT ["bash", "serve.sh"]
