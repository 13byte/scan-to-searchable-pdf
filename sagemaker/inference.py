

import os
import io
import torch
import cv2
import numpy as np
from fastapi import FastAPI, Request, Response
from contextlib import asynccontextmanager
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CPU 강제 설정 (서버리스 환경)
torch.set_num_threads(2)
os.environ['CUDA_VISIBLE_DEVICES'] = ''

upsampler = None

# --- Model Loading ---
def load_model():
    """모델 로드 및 CPU 환경 최적화"""
    global upsampler
    if upsampler is None:
        try:
            logger.info("Real-ESRGAN 모델 로딩 시작")
            model_path = '/opt/ml/model/RealESRGAN_x4plus.pth'
            if not os.path.exists(model_path):
                model_path = 'RealESRGAN_x4plus.pth'
            
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"모델 파일 없음: {model_path}")

            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, 
                          num_block=23, num_grow_ch=32, scale=4)
            
            upsampler = RealESRGANer(
                scale=4,
                model_path=model_path,
                model=model,
                tile=256,
                tile_pad=10,
                pre_pad=0,
                half=False,
                device='cpu'
            )
            logger.info("모델 로딩 완료")
        except Exception as e:
            logger.error(f"모델 로딩 실패: {e}")
            raise

# --- FastAPI Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_model()
        logger.info("애플리케이션 시작 완료")
        yield
    except Exception as e:
        logger.error(f"애플리케이션 시작 실패: {e}")
        raise
    finally:
        global upsampler
        upsampler = None
        logger.info("애플리케이션 정리 완료")

# --- FastAPI App ---
app = FastAPI(lifespan=lifespan)

@app.get('/ping', status_code=200)
def ping():
    """SageMaker 헬스 체크 엔드포인트"""
    try:
        if upsampler is None:
            logger.error("모델 미로드 상태")
            return Response(content='\n', status_code=503)
        return Response(content='\n', status_code=200)
    except Exception as e:
        logger.error(f"헬스 체크 실패: {e}")
        return Response(content='\n', status_code=503)

@app.post('/invocations')
async def invocations(request: Request):
    """SageMaker 추론 엔드포인트"""
    try:
        if upsampler is None:
            logger.error("모델 미로드 상태")
            return Response("모델 미로드", status_code=500)

        if request.headers.get('content-type') != 'image/jpeg':
            return Response("Content-Type은 image/jpeg여야 함", status_code=415)

        img_bytes = await request.body()
        img_np = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(img_np, cv2.IMREAD_COLOR)
        
        if img is None:
            return Response("이미지 디코딩 실패", status_code=400)

        output, _ = upsampler.enhance(img, outscale=4)
        
        is_success, buffer = cv2.imencode(".jpg", output)
        if not is_success:
            raise Exception("업스케일 이미지 인코딩 실패")

        return Response(content=buffer.tobytes(), media_type='image/jpeg')

    except Exception as e:
        logger.error(f"추론 실패: {e}")
        return Response(str(e), status_code=500)

