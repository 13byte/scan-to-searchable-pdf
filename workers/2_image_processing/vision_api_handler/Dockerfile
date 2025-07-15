# AWS Lambda Python 3.12 Runtime Base Image (REQUIRED for Lambda Container Compatibility)
FROM public.ecr.aws/lambda/python:3.12

# Google Vision API 및 필수 의존성 설치
COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install --no-cache-dir -r requirements.txt

# Lambda 함수 코드 복사
COPY main.py requirements.txt ./

# Lambda 런타임 핸들러 설정 (CRITICAL: Lambda Container Entry Point)
CMD ["main.handler"]
