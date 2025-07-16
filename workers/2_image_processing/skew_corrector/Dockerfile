# Fargate 통합 프로세서 Dockerfile (Python 3.11, uv)
FROM public.ecr.aws/lambda/python:3.12

# 시스템 패키지 업데이트 및 의존성 설치 (Amazon Linux 2023/dnf 사용)
RUN dnf update -y && dnf install -y \
  mesa-libGL \
  && dnf clean all

# uv 설치
RUN pip install uv

# Install dependencies
COPY workers/2_image_processing/skew_corrector/requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# 애플리케이션 코드 복사
COPY workers/2_image_processing/skew_corrector/main.py .

# 환경 변수 설
ENV PYTHONUNBUFFERED=1

# 실행 권한 설정
RUN chmod +x main.py

# 컨테이너 실행 명령
ENTRYPOINT ["python", "main.py"]
