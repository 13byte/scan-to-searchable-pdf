FROM public.ecr.aws/lambda/python:3.12-arm64

# System dependencies
RUN dnf update -y && \
    dnf clean all

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy requirements and install dependencies
COPY workers/1_orchestration/orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Lambda function code
COPY workers/1_orchestration/orchestrator/main.py .

# Lambda runtime handler
CMD ["main.handler"]
