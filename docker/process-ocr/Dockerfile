# Process OCR Lambda Container Image
FROM public.ecr.aws/lambda/python:3.12

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Install system dependencies for Google Cloud Vision
RUN dnf update -y && \
  dnf install -y gcc gcc-c++ make && \
  dnf clean all && \
  rm -rf /var/cache/yum

# Copy requirements and install dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install uv && uv pip install --system --no-cache -r requirements.txt

# Copy Lambda function code
COPY index.py ${LAMBDA_TASK_ROOT}/lambda_function.py

# Set the Lambda handler
CMD ["lambda_function.lambda_handler"]
