

import os
import io
import torch
import cv2
import numpy as np
from fastapi import FastAPI, Request, Response
from contextlib import asynccontextmanager
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet

# --- Global Variables ---
# 모델과 업스케일러를 전역 변수로 선언
upsampler = None

# --- Model Loading ---
def load_model():
    """모델을 로드하여 전역 변수에 할당"""
    global upsampler
    if upsampler is None:
        print("Loading Real-ESRGAN model...")
        # SageMaker가 모델 아티팩트를 압축 해제하는 기본 경로
        model_path = '/opt/ml/model/RealESRGAN_x4plus.pth'
        if not os.path.exists(model_path):
            # 로컬 테스트나 다른 경로에 있을 경우 대비
            model_path = 'RealESRGAN_x4plus.pth'

        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        upsampler = RealESRGANer(
            scale=4,
            model_path=model_path,
            model=model,
            tile=0,
            tile_pad=10,
            pre_pad=0,
            half=True,
            device='cuda' if torch.cuda.is_available() else 'cpu'
        )
        print("Model loaded successfully.")

# --- FastAPI Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 애플리케이션 시작 시 모델 로드
    load_model()
    yield
    # 애플리케이션 종료 시 정리 (필요 시)
    global upsampler
    upsampler = None
    print("Model cleaned up.")

# --- FastAPI App ---
app = FastAPI(lifespan=lifespan)

@app.get('/ping', status_code=200)
def ping():
    """SageMaker 헬스 체크 엔드포인트"""
    if upsampler is None:
        return Response(content='\n', status_code=503) # Service Unavailable
    return Response(content='\n', status_code=200)

@app.post('/invocations')
async def invocations(request: Request):
    """SageMaker 추론 엔드포인트"""
    if upsampler is None:
        return Response("Model is not loaded or failed to load.", status_code=500)

    if request.headers.get('content-type') != 'image/jpeg':
        return Response("Content-Type must be image/jpeg", status_code=415)

    try:
        # 요청 본문에서 이미지 데이터 비동기적으로 읽기
        img_bytes = await request.body()
        img_np = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(img_np, cv2.IMREAD_COLOR)

        # Real-ESRGAN으로 업스케일링
        output, _ = upsampler.enhance(img, outscale=4)

        # 결과를 JPEG 형식으로 인코딩
        is_success, buffer = cv2.imencode(".jpg", output)
        if not is_success:
            raise Exception("Failed to encode upscaled image.")

        return Response(content=buffer.tobytes(), media_type='image/jpeg')

    except Exception as e:
        print(f"Error during invocation: {e}")
        return Response(str(e), status_code=500)

