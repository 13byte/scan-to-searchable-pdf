# AWS Lambda Python 3.12 Base Image with Google Cloud Vision
FROM public.ecr.aws/lambda/python:3.12

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Install system dependencies for Google Cloud Vision
RUN dnf update -y && \
  dnf install -y gcc gcc-c++ make && \
  dnf clean all && \
  rm -rf /var/cache/yum

# Copy requirements first for better caching
COPY docker/process-ocr/requirements.txt ${LAMBDA_TASK_ROOT}/

# Install Python dependencies with Google Cloud Vision
RUN pip install uv && uv pip install --system --no-cache -r requirements.txt

# Copy secrets_cache.py
COPY workers/2_image_processing/detect_skew/secrets_cache.py ${LAMBDA_TASK_ROOT}/secrets_cache.py

# Copy function code
COPY docker/process-ocr/main.py ${LAMBDA_TASK_ROOT}/lambda_function.py

# Set the default Lambda handler
CMD ["lambda_function.lambda_handler"]