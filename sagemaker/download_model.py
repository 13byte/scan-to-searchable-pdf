#!/usr/bin/env python3
"""
RealESRGAN 모델 다운로드 및 검증 스크립트 (안정화 버전)
"""
import os
import hashlib
import urllib.request
import logging
from pathlib import Path

# --- 로깅 설정 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 모델 정보 (추론용 생성자 모델) ---
MODEL_CONFIG = {
    'filename': 'RealESRGAN_x4plus.pth',
    'sources': [
        {
            'url': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
            'sha256': '4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1',
            'size_mb': 64.0  # 실제 파일 크기는 약 64MB
        }
    ],
    'description': 'RealESRGAN_x4plus v0.1.0 고품질 4배 업스케일링 생성자 모델'
}

def calculate_sha256(file_path: str) -> str:
    """파일의 SHA256 해시를 계산합���다."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()

def download_file(url: str, output_path: str) -> bool:
    """간단하고 안정적인 파일 다운로드 함수."""
    try:
        logger.info(f"다운로드 시작: {url}")
        with urllib.request.urlopen(url) as response, open(output_path, 'wb') as out_file:
            if response.status != 200:
                logger.error(f"HTTP 상태 코드 {response.status}로 다운로드 실패.")
                return False
            out_file.write(response.read())
        logger.info(f"다운로드 완료: {output_path}")
        return True
    except Exception as e:
        logger.error(f"다운로드 중 예외 발생: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return False

def verify_model(file_path: str, config: dict) -> bool:
    """모델 파일의 크기와 해시를 검증합니다."""
    if not os.path.exists(file_path):
        return False
    
    # 파일 크기 검증 (Git LFS 포인터 파일 걸러내기 위함)
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb < 50: # 실제 모델은 60MB 이상이므로, 50MB 미만은 명백히 잘못된 파일
        logger.error(f"파일 크기가 너무 작습니다: {file_size_mb:.1f}MB. Git LFS 포인터일 수 있습니다.")
        return False
        
    # 해시 검증
    logger.info("파일 무결성(SHA256) 검증 중...")
    actual_sha256 = calculate_sha256(file_path)
    if actual_sha256 != config['sha256']:
        logger.error(f"SHA256 해시 불일치! 예상: {config['sha256']}, 실제: {actual_sha256}")
        return False
        
    logger.info("파일 무결성 검증 성공.")
    return True

def main():
    """메인 실행 함수"""
    model_dir = os.environ.get('MODEL_DIR', '/opt/ml/model')
    model_path = os.path.join(model_dir, MODEL_CONFIG['filename'])
    
    logger.info(f"모델 다운로드를 시작합니다. 대상 경로: {model_path}")
    Path(model_dir).mkdir(parents=True, exist_ok=True)

    # 이미 유효한 파일이 있는지 먼저 확인
    if verify_model(model_path, MODEL_CONFIG['sources'][0]):
        logger.info("✅ 유효한 모델 파일이 이미 존재합니다. 다운로드를 건너뜁니다.")
        return 0

    # 각 소스에서 다운로드 시도
    for source in MODEL_CONFIG['sources']:
        logger.info(f"소스 시도: {source['url']}")
        if download_file(source['url'], model_path):
            if verify_model(model_path, source):
                logger.info("✅ 모델 다운로드 및 검증 성공!")
                return 0
        # 실패 시, 잘못된 파일 삭제
        if os.path.exists(model_path):
            os.remove(model_path)
            
    logger.error("❌ 모든 소스에서 모델 다운로드에 실패했습니다.")
    return 1

if __name__ == "__main__":
    exit(main())