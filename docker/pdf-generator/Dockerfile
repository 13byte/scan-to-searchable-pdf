FROM public.ecr.aws/lambda/python:3.12-arm64

# System dependencies installation
RUN dnf update -y && \
    dnf install -y fontconfig freetype-devel libjpeg-turbo-devel && \
    dnf clean all

# Create font directory
RUN mkdir -p /opt/python/fonts

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy requirements and install dependencies
COPY workers/3_finalization/pdf_generator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Korean font
COPY config/NotoSansKR-Regular.ttf /opt/python/fonts/

# Copy Lambda function code
COPY workers/3_finalization/pdf_generator/main.py .

# Set font path environment variable
ENV FONT_PATH=/opt/python/fonts/NotoSansKR-Regular.ttf

# Lambda runtime handler
CMD ["main.handler"]
